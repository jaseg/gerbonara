"""
Library for handling KiCad's footprint files (`*.kicad_mod`).
"""

import copy
import enum
import string
import datetime
import math
import time
import fnmatch
from itertools import chain
from pathlib import Path
from dataclasses import field

from .sexp import *
from .base_types import *
from .primitives import *
from . import graphical_primitives as gr

from ..primitives import Positioned

from ... import graphic_primitives as gp
from ... import graphic_objects as go
from ... import apertures as ap
from ...newstroke import Newstroke
from ...utils import MM
from ...aperture_macros.parse import GenericMacros, ApertureMacro


@sexp_type('property')
class Property:
    key: str = ''
    value: str = ''


@sexp_type('attr')
class Attribute:
    type: AtomChoice(Atom.smd, Atom.through_hole) = None
    board_only: Flag() = False
    exclude_from_pos_files: Flag() = False
    exclude_from_bom: Flag() = False


@sexp_type('fp_text')
class Text:
    type: AtomChoice(Atom.reference, Atom.value, Atom.user) = Atom.user
    text: str = ""
    at: AtPos = field(default_factory=AtPos)
    unlocked: Flag() = False
    layer: Named(str) = None
    hide: Flag() = False
    effects: TextEffect = field(default_factory=TextEffect)
    tstamp: Timestamp = None

    def render(self, variables={}):
        if self.hide: # why
            return

        yield from gr.Text.render(self, variables=variables)


@sexp_type('fp_text_box')
class TextBox:
    locked: Flag() = False
    text: str = None
    start: Rename(XYCoord) = None
    end: Named(XYCoord) = None
    pts: PointList = None
    angle: Named(float) = 0.0
    layer: Named(str) = None
    tstamp: Timestamp = None
    effects: TextEffect = field(default_factory=TextEffect)
    stroke: Stroke = field(default_factory=Stroke)
    render_cache: RenderCache = None

    def render(self, variables={}):
        yield from gr.TextBox.render(self, variables=variables)


@sexp_type('fp_line')
class Line:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    locked: Flag() = False
    tstamp: Timestamp = None

    def render(self, variables=None):
        dasher = Dasher(self)
        dasher.move(self.start.x, self.start.y)
        dasher.line(self.end.x, self.end.y)

        for x1, y1, x2, y2 in dasher:
            yield go.Line(x1, y1, x2, y2, aperture=ap.CircleAperture(dasher.width, unit=MM), unit=MM)


@sexp_type('fp_rect')
class Rectangle:
    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    fill: Named(AtomChoice(Atom.solid, Atom.none)) = None
    locked: Flag() = False
    tstamp: Timestamp = None

    def render(self, variables=None):
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        w, h = x2-x1, y1-y2

        if self.fill == Atom.solid:
            yield go.Region.from_rectangle(x1, y1, w, y, unit=MM)

        dasher = Dasher(self)
        dasher.move(x1, y1)
        dasher.line(x1, y2)
        dasher.line(x2, y2)
        dasher.line(x2, y1)
        dasher.close()

        aperture = ap.CircleAperture(dasher.width, unit=MM)
        for x1, y1, x2, y2 in dasher:
            yield go.Line(x1, y1, x2, y2, aperture=aperture, unit=MM)


@sexp_type('fp_circle')
class Circle:
    center: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    fill: Named(AtomChoice(Atom.solid, Atom.none)) = None
    locked: Flag() = False
    tstamp: Timestamp = None

    def render(self, variables=None):
        x, y = self.center.x, self.center.y
        r = math.dist((x, y), (self.end.x, self.end.y)) # insane

        dasher = Dasher(self)
        aperture = ap.CircleAperture(dasher.width or 0, unit=MM)

        circle = go.Arc.from_circle(x, y, r, aperture=aperture, unit=MM)

        if self.fill == Atom.solid:
            yield circle.to_region()

        if dasher.solid:
            yield circle

        else: # pain
            for line in circle.approximate(): # TODO precision settings
                dasher.segments.append((line.x1, line.y1, line.x2, line.y2))

            aperture = ap.CircleAperture(dasher.width, unit=MM)
            for x1, y1, x2, y2 in dasher:
                yield go.Line(x1, y1, x2, y2, aperture=aperture, unit=MM)

@sexp_type('fp_arc')
class Arc:
    start: Rename(XYCoord) = None
    mid: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    locked: Flag() = False
    tstamp: Timestamp = None


    def render(self, variables=None):
        cx, cy = self.mid.x, self.mid.y
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        dasher = Dasher(self)

        # KiCad only has clockwise arcs.
        arc = go.Arc(x1, y1, x2, y2, cx-x1, cy-y1, clockwise=True, aperture=ap.CircleAperture(dasher.width, unit=MM), unit=MM)
        if dasher.solid:
            yield arc

        else:
            # use approximation from graphic object arc class 
            for line in arc.approximate():
                dasher.segments.append((line.x1, line.y1, line.x2, line.y2))
            
            for line in dasher:
                yield go.Line(x1, y1, x2, y2, aperture=ap.CircleAperture(dasher.width, unit=MM), unit=MM)


@sexp_type('fp_poly')
class Polygon:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    fill: Named(AtomChoice(Atom.solid, Atom.none)) = None
    locked: Flag() = False
    tstamp: Timestamp = None

    def render(self, variables=None):
        if len(self.pts.xy) < 2:
            return

        dasher = Dasher(self)
        start = self.pts.xy[0]
        dasher.move(start.x, start.y)
        for point in self.pts.xy[1:]:
            dasher.line(point.x, point.y)

        aperture = ap.CircleAperture(dasher.width, unit=MM)
        for x1, y1, x2, y2 in dasher:
            yield go.Line(x1, y1, x2, y2, aperture=aperture, unit=MM)

        if self.fill == Atom.solid:
            yield go.Region([(pt.x, pt.y) for pt in self.pts.xy], unit=MM)


@sexp_type('fp_curve')
class Curve:
    pts: PointList = field(default_factory=PointList)
    layer: Named(str) = None
    width: Named(float) = None
    stroke: Stroke = None
    locked: Flag() = False
    tstamp: Timestamp = None

    def render(self, variables=None):
        raise NotImplementedError('Bezier rendering is not yet supported. Please raise an issue and provide an example file.')


@sexp_type('format')
class DimensionFormat:
    prefix: Named(str) = None
    suffix: Named(str) = None
    units: Named(int) = 3
    units_format: Named(int) = 0
    precision: Named(int) = 3
    override_value: Named(str) = None
    suppress_zeros: Flag() = False


@sexp_type('style')
class DimensionStyle:
    thickness: Named(float) = None
    arrow_length: Named(float) = None
    text_position_mode: Named(int) = 0
    extension_height: Named(float) = None
    text_frame: Named(int) = 0
    extension_offset: Named(str) = None
    keep_text_aligned: Flag() = False


@sexp_type('dimension')
class Dimension:
    locked: Flag() = False
    type: AtomChoice(Atom.aligned, Atom.leader, Atom.center, Atom.orthogonal, Atom.radial) = None
    layer: Named(str) = None
    tstamp: Timestamp = None
    pts: PointList = field(default_factory=PointList)
    height: Named(float) = None
    orientation: Named(int) = 0
    leader_length: Named(float) = None
    gr_text: Named(Text) = None
    format: DimensionFormat = field(default_factory=DimensionFormat)
    style: DimensionStyle = field(default_factory=DimensionStyle)

    def render(self, variables=None):
        raise NotImplementedError()


@sexp_type('drill')
class Drill:
    oval: Flag() = False
    diameter: float = 0
    width: float = None
    offset: Rename(XYCoord) = None


@sexp_type('net')
class NetDef:
    number: int = None
    name: str = None


@sexp_type('options')
class CustomPadOptions:
    clearance: Named(AtomChoice(Atom.outline, Atom.convexhull)) = Atom.outline
    anchor: Named(AtomChoice(Atom.rect, Atom.circle)) = Atom.rect


@sexp_type('primitives')
class CustomPadPrimitives:
    annotation_bboxes: List(gr.AnnotationBBox) = field(default_factory=list)
    lines: List(gr.Line) = field(default_factory=list)
    rectangles: List(gr.Rectangle) = field(default_factory=list)
    circles: List(gr.Circle) = field(default_factory=list)
    arcs: List(gr.Arc) = field(default_factory=list)
    polygons: List(gr.Polygon) = field(default_factory=list)
    curves: List(gr.Curve) = field(default_factory=list)
    width: Named(float) = None
    fill: Named(YesNoAtom()) = True

    def all(self):
        yield from self.lines
        yield from self.rectangles
        yield from self.circles
        yield from self.arcs
        yield from self.polygons
        yield from self.curves


@sexp_type('chamfer')
class Chamfer:
    top_left: Flag() = False
    top_right: Flag() = False
    bottom_left: Flag() = False
    bottom_right: Flag() = False


@sexp_type('pad')
class Pad:
    number: str = None
    type: AtomChoice(Atom.thru_hole, Atom.smd, Atom.connect, Atom.np_thru_hole) = None
    shape: AtomChoice(Atom.circle, Atom.rect, Atom.oval, Atom.trapezoid, Atom.roundrect, Atom.custom) = None
    at: AtPos = field(default_factory=AtPos)
    locked: Wrap(Flag()) = False
    size: Rename(XYCoord) = field(default_factory=XYCoord)
    drill: Drill = None
    layers: Named(Array(str)) = field(default_factory=list)
    properties: List(Property) = field(default_factory=list)
    remove_unused_layers: Wrap(Flag()) = False
    keep_end_layers: Wrap(Flag()) = False
    rect_delta: Rename(XYCoord) = None
    roundrect_rratio: Named(float) = None
    thermal_bridge_angle: Named(int) = 45
    chamfer_ratio: Named(float) = None
    chamfer: Chamfer = None
    net: NetDef = None
    tstamp: Timestamp = None
    pin_function: Named(str) = None
    pintype: Named(str) = None
    die_length: Named(float) = None
    solder_mask_margin: Named(float) = None
    solder_paste_margin: Named(float) = None
    solder_paste_margin_ratio: Named(float) = None
    clearance: Named(float) = None
    zone_connect: Named(int) = None
    thermal_width: Named(float) = None
    thermal_gap: Named(float) = None
    options: OmitDefault(CustomPadOptions) = None
    primitives: OmitDefault(CustomPadPrimitives) = None

    def render(self, variables=None):
        if self.type in (Atom.connect, Atom.np_thru_hole):
            return

        yield go.Flash(self.at.x, self.at.y, self.aperture().rotated(math.radians(self.at.rotation)), unit=MM)

    def aperture(self):
        if self.shape == Atom.circle:
            return ap.CircleAperture(self.size.x, unit=MM)

        elif self.shape == Atom.rect:
            return ap.RectangleAperture(self.size.x, self.size.y, unit=MM)

        elif self.shape == Atom.oval:
            return ap.ObroundAperture(self.size.x, self.size.y, unit=MM)

        elif self.shape == Atom.trapezoid:
            # KiCad's trapezoid aperture "rect_delta" param is just weird to the point that I think it's probably
            # bugged. If you have a size of 2mm by 2mm, and set this param to 1mm, the resulting pad extends past the
            # original bounding box, and the trapezoid's base and tip length are 3mm and 1mm.

            x, y = self.size.x, self.size.y
            dx, dy = self.rect_delta.x, self.rect_delta.y

            # Note: KiCad already uses MM units, so no conversion needed here.
            return ap.ApertureMacroInstance(GenericMacros.isosceles_trapezoid,
                    [x+dx, y+dy,
                     2*max(dx, dy),
                     0, 0, # no hole
                     math.radians(self.at.rotation)], unit=MM)

        elif self.shape == Atom.roundrect:
            x, y = self.size.x, self.size.y
            r = min(x, y) * self.roundrect_rratio
            return ap.ApertureMacroInstance(GenericMacros.rounded_rect,
                    [x, y,
                     r,
                     0, 0, # no hole
                     math.radians(self.at.rotation)], unit=MM)

        elif self.shape == Atom.custom:
            primitives = []
            # One round trip through the Gerbonara APIs, please!
            for obj in self.primitives.all():
                for gn_obj in obj.render():
                    primitives += gn_obj._aperture_macro_primitives() # todo: precision params
            macro = ApertureMacro(primitives=primitives)
            return ap.ApertureMacroInstance(macro, unit=MM)

    def render_drill(self):
        if not self.drill:
            return

        plated = self.type != Atom.np_thru_hole
        aperture = ap.ExcellonTool(self.drill.diameter, plated=plated, unit=MM)
        if self.drill.oval:
            w = self.drill.width / 2
            l = go.Line(-w, 0, w, 0, aperture=aperture, unit=MM) 
            l.rotate(math.radians(self.at.rotation))
            l.offset(self.at.x, self.at.y)
            yield l
        else:
            yield go.Flash(self.at.x, self.at.y, aperture=aperture, unit=MM) 


@sexp_type('group')
class Group:
    name: str = ""
    id: Named(str) = ""
    members: Named(List(str)) = field(default_factory=list)


@sexp_type('model')
class Model:
    name: str = ''
    at: Named(XYZCoord) = field(default_factory=XYZCoord)
    offset: Named(XYZCoord) = field(default_factory=XYZCoord)
    scale: Named(XYZCoord) = field(default_factory=XYZCoord)
    rotate: Named(XYZCoord) = field(default_factory=XYZCoord)


SUPPORTED_FILE_FORMAT_VERSIONS = [20210108, 20211014, 20221018]
@sexp_type('footprint')
class Footprint:
    name: str = None
    _version: Named(int, name='version') = 20210108
    generator: Named(Atom) = Atom.kicad_library_utils
    locked: Flag() = False
    placed: Flag() = False
    layer: Named(str) = 'F.Cu'
    tedit: EditTime = field(default_factory=EditTime)
    tstamp: Timestamp = None
    at: AtPos = field(default_factory=AtPos)
    descr: Named(str) = None
    tags: Named(str) = None
    properties: List(Property) = field(default_factory=list)
    path: Named(str) = None
    autoplace_cost90: Named(float) = None
    autoplace_cost180: Named(float) = None
    solder_mask_margin: Named(float) = None
    solder_paste_margin: Named(float) = None
    solder_paste_ratio: Named(float) = None
    clearance: Named(float) = None
    zone_connect: Named(int) = None
    thermal_width: Named(float) = None
    thermal_gap: Named(float) = None
    attributes: List(Attribute) = field(default_factory=list)
    private_layers: Named(str) = None
    net_tie_pad_groups: Named(str) = None
    texts: List(Text) = field(default_factory=list)
    text_boxes: List(TextBox) = field(default_factory=list)
    lines: List(Line) = field(default_factory=list)
    rectangles: List(Rectangle) = field(default_factory=list)
    circles: List(Circle) = field(default_factory=list)
    arcs: List(Arc) = field(default_factory=list)
    polygons: List(Polygon) = field(default_factory=list)
    curves: List(Curve) = field(default_factory=list)
    dimensions: List(Dimension) = field(default_factory=list)
    pads: List(Pad) = field(default_factory=list)
    zones: List(Zone) = field(default_factory=list)
    groups: List(Group) = field(default_factory=list)
    models: List(Model) = field(default_factory=list)
    _ : SEXP_END = None
    original_filename: str = None

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
    def open_pretty(kls, pretty_dir, fp_name, *args, **kwargs):
        pretty_dir = Path(pretty_dir) / f'{fp_name}.kicad_mod'
        return kls.open_mod(pretty_dir / mod_name, *args, **kwargs)

    @classmethod
    def open_mod(kls, mod_file, *args, **kwargs):
        return kls.load(Path(mod_file).read_text(), *args, **kwargs, original_filename=mod_file)

    @classmethod
    def open_system(kls, fp_path):
        raise NotImplementedError()

    @classmethod
    def open_download(kls, fp_path):
        raise NotImplementedError()

    @classmethod
    def load(kls, data, *args, **kwargs):
        return kls.parse(data, *args, **kwargs)

    @property
    def single_sided(self):
        raise NotImplementedError()

    def objects(self, text=False, pads=True):
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
                (self.pads if pads else []))

    def render(self, layer_stack, layer_map, x=0, y=0, rotation=0, text=False, side=None, variables={}):
        x += self.at.x
        y += self.at.y
        rotation += math.radians(self.at.rotation)
        flip = (side != 'top') if side else (self.layer != 'F.Cu')

        for obj in self.objects(pads=False, text=text):
            if not (layer := layer_map.get(obj.layer)):
                continue

            for fe in obj.render(variables=variables):
                fe.rotate(rotation)
                fe.offset(x, y, MM)
                layer_stack[layer].objects.append(fe)

        for obj in self.pads:
            for glob in obj.layers or []:
                for layer in fnmatch.filter(layer_map, glob):
                    for fe in obj.render():
                        fe.rotate(rotation)
                        fe.offset(x, y, MM)
                        if isinstance(fe, go.Flash) and fe.aperture:
                            fe.aperture = fe.aperture.rotated(rotation)
                        layer_stack[layer_map[layer]].objects.append(fe)

        for obj in self.pads:
            for fe in obj.render_drill():
                fe.rotate(rotation)
                fe.offset(x, y, MM)

                if obj.type == Atom.np_thru_hole:
                    layer_stack.drill_npth.append(fe)
                else:
                    layer_stack.drill_pth.append(fe)

LAYER_MAP_K2G = {
        'F.Cu': ('top', 'copper'),
        'B.Cu': ('bottom', 'copper'),
        'F.SilkS': ('top', 'silk'),
        'B.SilkS': ('bottom', 'silk'),
        'F.Paste': ('top', 'paste'),
        'B.Paste': ('bottom', 'paste'),
        'F.Mask': ('top', 'mask'),
        'B.Mask': ('bottom', 'mask'),
        'B.CrtYd': ('bottom', 'courtyard'),
        'F.CrtYd': ('top', 'courtyard'),
        'B.Fab': ('bottom', 'fabrication'),
        'F.Fab': ('top', 'fabrication'),
        'Edge.Cuts': ('mechanical', 'outline'),
        }

LAYER_MAP_G2K = {v: k for k, v in LAYER_MAP_K2G.items()}


@dataclass
class FootprintInstance(Positioned):
    sexp: Footprint = None
    hide_text: bool = True 
    reference: str = 'REF**'
    value: str = None
    variables: dict = field(default_factory=lambda: {})

    def render(self, layer_stack):
        x, y, rotation = self.abs_pos
        x, y = MM(x, self.unit), MM(y, self.unit)

        variables = dict(self.variables)

        if self.reference is not None:
            variables['REFERENCE'] = str(self.reference)

        if self.value is not None:
            variables['VALUE'] = str(self.value)

        self.sexp.render(layer_stack, LAYER_MAP_K2G,
                         x=x, y=y, rotation=rotation,
                         side=self.side,
                         text=(not self.hide_text),
                         variables=variables)

if __name__ == '__main__':
    import sys
    from ...layers import LayerStack
    fp = Footprint.open_mod(sys.argv[1])
    stack = LayerStack()
    FootprintInstance(0, 0, fp, unit=MM).render(stack)
    print(stack.to_pretty_svg())
    stack.save_to_directory('/tmp/testdir')

