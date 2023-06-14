"""
Library for handling KiCad's PCB files (`*.kicad_mod`).
"""

from pathlib import Path
from dataclasses import field
from itertools import chain
import fnmatch

from .sexp import *
from .base_types import *
from .primitives import *
from .footprints import Footprint
from . import graphical_primitives as gr

from ..primitives import Positioned

from ... import graphic_primitives as gp
from ... import graphic_objects as go
from ... import apertures as ap
from ...layers import LayerStack
from ...newstroke import Newstroke
from ...utils import MM


@sexp_type('general')
class GeneralSection:
    thickness: Named(float) = 1.60


@sexp_type('paper')
class PageSettings:
    page_format: str = 'A4'
    width: float = None
    height: float = None
    portrait: bool = False


@sexp_type('layers')
class LayerSettings:
    index: int = None
    canonical_name: str = None
    layer_type: AtomChoice(Atom.jumper, Atom.mixed, Atom.power, Atom.signal, Atom.user) = Atom.signal
    custom_name: str = None


@sexp_type('layer')
class LayerStackupSettings:
    dielectric: bool = False
    name: str = None
    index: int = None
    layer_type: Named(str, name='type') = ''
    color: Color = None
    thickness: Named(float) = None
    material: Named(str) = None
    epsilon_r: Named(float) = None
    loss_tangent: Named(float) = None


@sexp_type('stackup')
class StackupSettings:
    layers: List(LayerStackupSettings) = field(default_factory=list)
    copper_finish: Named(str) = None
    dielectric_constraints: Named(YesNoAtom()) = None
    edge_connector: Named(AtomChoice(Atom.yes, Atom.bevelled)) = None
    castellated_pads: Named(bool) = None
    edge_plating: Named(bool) = None


TFBool = YesNoAtom(yes=Atom.true, no=Atom.false)

@sexp_type('pcbplotparams')
class ExportSettings:
    layerselection: Named(Atom) = 0
    plot_on_all_layers_selection: Named(Atom) = 0
    disableapertmacros: Named(TFBool) = False
    usegerberextensions: Named(TFBool) = True
    usegerberattributes: Named(TFBool) = True
    usegerberadvancedattributes: Named(TFBool) = True
    creategerberjobfile: Named(TFBool) = True
    dashed_line_dash_ratio: Named(float) = 12.0
    dashed_line_gap_ratio: Named(float) = 3.0
    svguseinch: Named(TFBool) = False
    svgprecision: Named(float) = 4
    excludeedgelayer: Named(TFBool) = False
    plotframeref: Named(TFBool) = False
    viasonmask: Named(TFBool) = False
    mode: Named(int) = 1
    useauxorigin: Named(TFBool) = False
    hpglpennumber: Named(int) = 1
    hpglpenspeed: Named(int) = 20
    hpglpendiameter: Named(float) = 15.0
    pdf_front_fp_property_popups: Named(TFBool) = True
    pdf_back_fp_property_popups: Named(TFBool) = True
    dxfpolygonmode: Named(TFBool) = True
    dxfimperialunits: Named(TFBool) = False
    dxfusepcbnewfont: Named(TFBool) = True
    psnegative: Named(TFBool) = False
    psa4output: Named(TFBool) = False
    plotreference: Named(TFBool) = True
    plotvalue: Named(TFBool) = True
    plotinvisibletext: Named(TFBool) = False
    sketchpadsonfab: Named(TFBool) = False
    subtractmaskfromsilk: Named(TFBool) = False
    outputformat: Named(int) = 1
    mirror: Named(TFBool) = False
    drillshape: Named(int) = 0
    scaleselection: Named(int) = 1
    outputdirectory: Named(str) = "gerber"


@sexp_type('setup')
class BoardSetup:
    stackup: OmitDefault(StackupSettings) = field(default_factory=StackupSettings)
    pad_to_mask_clearance: Named(float) = None
    solder_mask_min_width: Named(float) = None
    pad_to_past_clearance: Named(float) = None
    pad_to_paste_clearance_ratio: Named(float) = None
    aux_axis_origin: Rename(XYCoord) = None
    grid_origin: Rename(XYCoord) = None
    export_settings: ExportSettings = field(default_factory=ExportSettings)


@sexp_type('net')
class Net:
    index: int = 0
    name: str = ''


@sexp_type('image')
class Image:
    at: AtPos = field(default_factory=AtPos)
    scale: Named(float) = None
    layer: Named(str) = None
    uuid: UUID = field(default_factory=UUID)
    data: str = ''


@sexp_type('segment')
class TrackSegment:
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    width: Named(float) = 0.5
    layer: Named(str) = 'F.Cu'
    locked: bool = False
    net: Named(int) = 0
    tstamp: Timestamp = field(default_factory=Timestamp)

    def render(self, variables=None, cache=None):
        if not self.width:
            return

        aperture = ap.CircleAperture(self.width, unit=MM)
        yield go.Line(self.start.x, self.start.y, self.end.x, self.end.y, aperture=aperture, unit=MM)


@sexp_type('arc')
class TrackArc:
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    mid: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    width: Named(float) = 0.5
    layer: Named(str) = 'F.Cu'
    locked: bool = False
    net: Named(int) = 0
    tstamp: Timestamp = field(default_factory=Timestamp)

    def render(self, variables=None, cache=None):
        if not self.width:
            return

        aperture = ap.CircleAperture(self.width, unit=MM)
        cx, cy = self.mid.x, self.mid.y
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        yield go.Arc(x1, y1, x2, y2, cx-x1, cy-y1, aperture=aperture, clockwise=True, unit=MM)


@sexp_type('via')
class Via:
    via_type: AtomChoice(Atom.blind, Atom.micro) = None
    locked: bool = False
    at: AtPos = field(default_factory=AtPos)
    size: Named(float) = 0.8
    drill: Named(float) = 0.4
    layers: Named(Array(str)) = field(default_factory=list)
    remove_unused_layers: bool = False
    keep_end_layers: bool = False
    free: Wrap(Flag()) = False
    net: Named(int) = 0
    tstamp: Timestamp = field(default_factory=Timestamp)

    def render_drill(self):
        aperture = ap.ExcellonTool(self.drill, plated=True, unit=MM)
        yield go.Flash(self.at.x, self.at.y, aperture=aperture, unit=MM) 

    def render(self, variables=None, cache=None):
        aperture = ap.CircleAperture(self.size, unit=MM)
        yield go.Flash(self.at.x, self.at.y, aperture, unit=MM)


SUPPORTED_FILE_FORMAT_VERSIONS = [20210108, 20211014, 20221018, 20230517]
@sexp_type('kicad_pcb')
class Board:
    _version: Named(int, name='version') = 20210108
    generator: Named(Atom) = Atom.gerbonara
    general: GeneralSection = field(default_factory=GeneralSection)
    page: PageSettings = field(default_factory=PageSettings)
    layers: Named(Array(LayerSettings)) = field(default_factory=list)
    setup: BoardSetup = field(default_factory=BoardSetup)
    properties: List(Property) = field(default_factory=list)
    nets: List(Net) = field(default_factory=list)
    footprints: List(Footprint) = field(default_factory=list)
    # Graphical elements
    texts: List(gr.Text) = field(default_factory=list)
    text_boxes: List(gr.TextBox) = field(default_factory=list)
    lines: List(gr.Line) = field(default_factory=list)
    rectangles: List(gr.Rectangle) = field(default_factory=list)
    circles: List(gr.Circle) = field(default_factory=list)
    arcs: List(gr.Arc) = field(default_factory=list)
    polygons: List(gr.Polygon) = field(default_factory=list)
    curves: List(gr.Curve) = field(default_factory=list)
    dimensions: List(gr.Dimension) = field(default_factory=list)
    images: List(Image) = field(default_factory=list)
    # Tracks
    track_segments: List(TrackSegment) = field(default_factory=list)
    vias: List(Via) = field(default_factory=list)
    track_arcs: List(TrackArc) = field(default_factory=list)
    # Other stuff
    zones: List(Zone) = field(default_factory=list)
    groups: List(Group) = field(default_factory=list)

    _ : SEXP_END = None
    original_filename: str = None
    _bounding_box: tuple = None

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        if value not in SUPPORTED_FILE_FORMAT_VERSIONS:
            raise FormatError(f'File format version {value} is not supported. Supported versions are {", ".join(map(str, SUPPORTED_FILE_FORMAT_VERSIONS))}.')

    def write(self, filename=None):
        with open(filename or self.original_filename, 'w') as f:
            f.write(build_sexp(sexp(self)))

    @classmethod
    def open(kls, pcb_file, *args, **kwargs):
        return kls.load(Path(pcb_file).read_text(), *args, **kwargs, original_filename=pcb_file)

    @classmethod
    def load(kls, data, *args, **kwargs):
        return kls.parse(data, *args, **kwargs)

    @property
    def single_sided(self):
        raise NotImplementedError()

# FIXME vvv
    def graphic_objects(self, text=False, images=False):
        return chain(
                (self.texts if text else []),
                (self.text_boxes if text else []),
                self.lines,
                self.rectangles,
                self.circles,
                self.arcs,
                self.polygons,
                self.curves,
                (self.dimensions if text else []),
                (self.images if images else []))


    def tracks(self, vias=True):
        return chain(self.track_segments, self.track_arcs, (self.vias if vias else []))


    def objects(self, vias=True, text=False, images=False):
        return chain(self.graphic_objects(text=text, images=images), self.tracks(vias=vias))


    def render(self, layer_stack, layer_map, x=0, y=0, rotation=0, text=False, flip=False, variables={}, cache=None):
        for obj in self.objects(images=False, vias=False, text=text):
            if not (layer := layer_map.get(obj.layer)):
                continue

            for fe in obj.render(variables=variables):
                fe.rotate(rotation)
                fe.offset(x, y, MM)
                layer_stack[layer].objects.append(fe)

        for obj in self.vias:
            for glob in obj.layers or []:
                for layer in fnmatch.filter(layer_map, glob):
                    for fe in obj.render(cache=cache):
                        fe.rotate(rotation)
                        fe.offset(x, y, MM)
                        fe.aperture = fe.aperture.rotated(rotation)
                        layer_stack[layer_map[layer]].objects.append(fe)

            for fe in obj.render_drill():
                fe.rotate(rotation)
                fe.offset(x, y, MM)
                layer_stack.drill_pth.append(fe)

    def bounding_box(self, unit=MM):
        if not self._bounding_box:
            stack = LayerStack()
            layer_map = {kc_id: gn_id for kc_id, gn_id in LAYER_MAP_K2G.items() if gn_id in stack}
            self.render(stack, layer_map, x=0, y=0, rotation=0, flip=False, text=False, variables={})
            self._bounding_box = stack.bounding_box(unit)
        return self._bounding_box

 
@dataclass
class BoardInstance(Positioned):
    sexp: Board = None
    variables: dict = field(default_factory=lambda: {})

    def render(self, layer_stack, cache=None):
        x, y, rotation, flip = self.abs_pos
        x, y = MM(x, self.unit), MM(y, self.unit)

        variables = dict(self.variables)

        layer_map = {kc_id: gn_id for kc_id, gn_id in LAYER_MAP_K2G.items() if gn_id in layer_stack}

        self.sexp.render(layer_stack, layer_map,
                         x=x, y=y, rotation=rotation,
                         flip=flip,
                         variables=variables, cache=cache)
    
    def bounding_box(self, unit=MM):
        return offset_bounds(self.sexp.bounding_box(unit), unit(self.x, self.unit), unit(self.y, self.unit))


if __name__ == '__main__':
    import sys
    from ...layers import LayerStack
    fp = Board.open(sys.argv[1])
    stack = LayerStack()
    BoardInstance(0, 0, fp, unit=MM).render(stack)
    print(stack.to_pretty_svg())
    stack.save_to_directory('/tmp/testdir')

