"""
Library for handling KiCad's PCB files (`*.kicad_mod`).
"""

import math
from pathlib import Path
from dataclasses import field, KW_ONLY, fields
from itertools import chain
import re
import fnmatch
import functools

from .sexp import *
from .base_types import *
from .primitives import *
from .footprints import Footprint, Pad
from . import graphical_primitives as gr
import rtree.index

from .. import primitives as cad_pr

from ... import graphic_primitives as gp
from ... import graphic_objects as go
from ... import apertures as ap
from ...layers import LayerStack
from ...newstroke import Newstroke
from ...utils import MM, rotate_point


def match_filter(f, value):
    if isinstance(f, str) and re.fullmatch(f, value):
        return True
    return value in f

def gn_side_to_kicad(side, layer='Cu'):
    if side == 'top':
        return f'F.{layer}'
    elif side == 'bottom':
        return f'B.{layer}'
    elif side.startswith('inner'):
        return f'In{int(side[5:])}.{layer}'
    else:
        raise ValueError(f'Cannot parse gerbonara side name "{side}"')

def gn_layer_to_kicad(layer, flip=False):
    side = 'B' if flip else 'F'
    if layer == 'silk':
        return f'{side}.SilkS'
    elif layer == 'mask':
        return f'{side}.Mask'
    elif layer == 'paste':
        return f'{side}.Paste'
    elif layer == 'copper':
        return f'{side}.Cu'
    else:
        raise ValueError('Cannot translate gerbonara layer name "{layer}" to KiCad')


@sexp_type('general')
class GeneralSection:
    thickness: Named(float) = 1.60
    legacy_teardrops: Named(YesNoAtom()) = False


@sexp_type('layers')
class LayerSettings:
    index: int = 0
    canonical_name: str = None
    layer_type: AtomChoice(Atom.jumper, Atom.mixed, Atom.power, Atom.signal, Atom.user, Atom.auxiliary) = Atom.signal
    custom_name: str = None


@sexp_type('layer')
class LayerStackupSettings:
    dielectric: Flag() = False
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
    castellated_pads: Named(YesNoAtom()) = None
    edge_plating: Named(YesNoAtom()) = None


@sexp_type('pcbplotparams')
class ExportSettings:
    layerselection: Named(Atom) = None
    plot_on_all_layers_selection: Named(Atom) = None
    disableapertmacros: Named(YesNoAtom()) = False
    usegerberextensions: Named(YesNoAtom()) = True
    usegerberattributes: Named(YesNoAtom()) = True
    usegerberadvancedattributes: Named(YesNoAtom()) = True
    creategerberjobfile: Named(YesNoAtom()) = True
    dashed_line_dash_ratio: Named(float) = 12.0
    dashed_line_gap_ratio: Named(float) = 3.0
    svguseinch: Named(YesNoAtom()) = False
    svgprecision: Named(float) = 4
    excludeedgelayer: Named(YesNoAtom()) = False
    plotframeref: Named(YesNoAtom()) = False
    viasonmask: Named(YesNoAtom()) = False
    mode: Named(int) = 1
    useauxorigin: Named(YesNoAtom()) = False
    hpglpennumber: Named(int) = 1
    hpglpenspeed: Named(int) = 20
    hpglpendiameter: Named(float) = 15.0
    pdf_front_fp_property_popups: Named(YesNoAtom()) = True
    pdf_back_fp_property_popups: Named(YesNoAtom()) = True
    pdf_metadata: Named(YesNoAtom()) = True
    dxfpolygonmode: Named(YesNoAtom()) = True
    dxfimperialunits: Named(YesNoAtom()) = False
    dxfusepcbnewfont: Named(YesNoAtom()) = True
    psnegative: Named(YesNoAtom()) = False
    psa4output: Named(YesNoAtom()) = False
    plotreference: Named(YesNoAtom()) = True
    plotvalue: Named(YesNoAtom()) = True
    plotfptext: Named(YesNoAtom()) = True
    plotinvisibletext: Named(YesNoAtom()) = False
    sketchpadsonfab: Named(YesNoAtom()) = False
    plotpadnumbers: Named(YesNoAtom()) = False
    subtractmaskfromsilk: Named(YesNoAtom()) = False
    outputformat: Named(int) = 1
    mirror: Named(YesNoAtom()) = False
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
    allow_soldermask_bridges_in_footprints: Named(YesNoAtom()) = False
    tenting: Named(Array(AtomChoice(Atom.front, Atom.back))) = field(default_factory=lambda: [Atom.front, Atom.back])
    aux_axis_origin: Rename(XYCoord) = None
    grid_origin: Rename(XYCoord) = None
    export_settings: ExportSettings = field(default_factory=ExportSettings)


@sexp_type('segment')
class TrackSegment(BBoxMixin):
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    width: Named(float) = 0.5
    layer: Named(str) = 'F.Cu'
    locked: Flag() = False
    net: Named(int) = 0
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None

    @classmethod
    def from_footprint_line(kls, line, flip=False):
        # FIXME flip
        return kls(line.start, line.end, line.width or line.stroke.width, line.layer, line.locked, tstamp=line.tstamp)

    def __post_init__(self):
        self.start = XYCoord(self.start)
        self.end = XYCoord(self.end)

    @property
    def layer_mask(self):
        return layer_mask([self.layer])

    def render(self, variables=None, cache=None):
        if not self.width:
            return

        aperture = ap.CircleAperture(self.width, unit=MM)
        yield go.Line(self.start.x, -self.start.y, self.end.x, -self.end.y, aperture=aperture, unit=MM)

    def rotate(self, angle, cx=None, cy=None):
        if cx is None or cy is None:
            cx, cy = self.start.x, self.start.y

        self.start.x, self.start.y = rotate_point(self.start.x, self.start.y, angle, cx, cy)
        self.end.x, self.end.y = rotate_point(self.end.x, self.end.y, angle, cx, cy)

    def offset(self, x=0, y=0):
        self.start = self.start.with_offset(x, y)
        self.end = self.end.with_offset(x, y)


@sexp_type('arc')
class TrackArc(BBoxMixin):
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    mid: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    width: Named(float) = 0.5
    layer: Named(str) = 'F.Cu'
    locked: Flag() = False
    net: Named(int) = 0
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None
    _: SEXP_END = None
    center: XYCoord = None

    def __post_init__(self):
        self.start = XYCoord(self.start)
        self.end = XYCoord(self.end)
        self.mid = XYCoord(self.mid) if self.center is None else center_arc_to_kicad_mid(XYCoord(self.center), self.start, self.end)
        self.center = None

    @property
    def layer_mask(self):
        return layer_mask([self.layer])

    def render(self, variables=None, cache=None):
        if not self.width:
            return

        aperture = ap.CircleAperture(self.width, unit=MM)
        cx, cy = self.mid.x, self.mid.y
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        yield go.Arc(x1, -y1, x2, -y2, cx-x1, -(cy-y1), aperture=aperture, clockwise=True, unit=MM)

    def rotate(self, angle, cx=None, cy=None):
        self.start.x, self.start.y = rotate_point(self.start.x, self.start.y, angle, cx, cy)
        self.mid.x, self.mid.y = rotate_point(self.mid.x, self.mid.y, angle, cx, cy)
        self.end.x, self.end.y = rotate_point(self.end.x, self.end.y, angle, cx, cy)

    def offset(self, x=0, y=0):
        self.start = self.start.with_offset(x, y)
        self.mid = self.mid.with_offset(x, y)
        self.end = self.end.with_offset(x, y)


@sexp_type('via')
class Via(BBoxMixin):
    via_type: AtomChoice(Atom.blind, Atom.micro) = None
    locked: Flag() = False
    at: Rename(XYCoord) = field(default_factory=XYCoord)
    size: Named(float) = 0.8
    drill: Named(float) = 0.4
    layers: Named(Array(str)) = field(default_factory=lambda: ['F.Cu', 'B.Cu'])
    remove_unused_layers: Flag() = False
    keep_end_layers: Flag() = False
    free: Named(YesNoAtom()) = False
    net: Named(int) = 0
    uuid: UUID = field(default_factory=UUID)
    tstamp: Timestamp = None

    @classmethod
    def from_pad(kls, pad):
        if pad.type != Atom.thru_hole or pad.shape != Atom.circle:
            raise ValueError('Can only convert circular through-hole pads to vias.')

        if pad.drill and (pad.drill.oval or pad.drill.offset):
            raise ValueError('Can only convert pads with centered, circular drills to vias.')

        x, y, rot, _flip = pad.abs_pos
        return kls(locked=pad.locked,
                   at=XYCoord(x, y),
                   size=max(pad.size.x, pad.size.y),
                   drill=pad.drill.diameter if pad.drill else 0,
                   layers=[l for l in pad.layers if l.endswith('.Cu')],
                   free=True,
                   net=pad.net.number if pad.net else 0,
                   tstamp=pad.tstamp)

    @property
    def abs_pos(self):
        return self.at.x, self.at.y, 0, False

    @property
    def layer_mask(self):
        return layer_mask(self.layers)

    @property
    def width(self):
        return self.size

    def __post_init__(self):
        self.at = XYCoord(self.at)

    def render_drill(self):
        aperture = ap.ExcellonTool(self.drill, plated=True, unit=MM)
        yield go.Flash(self.at.x, -self.at.y, aperture=aperture, unit=MM) 

    def render(self, variables=None, cache=None):
        aperture = ap.CircleAperture(self.size, unit=MM)
        yield go.Flash(self.at.x, -self.at.y, aperture, unit=MM)

    def rotate(self, angle, cx=None, cy=None):
        if cx is None or cy is None:
            return

        self.at.x, self.at.y = rotate_point(self.at.x, self.at.y, angle, cx, cy)

    def offset(self, x=0, y=0):
        self.at = self.at.with_offset(x, y)


SUPPORTED_FILE_FORMAT_VERSIONS = [20210108, 20211014, 20221018, 20230517]
@sexp_type('kicad_pcb')
class Board:
    _version: Named(int, name='version') = 20230517
    generator: Named(str) = Atom.gerbonara
    generator_version: Named(str) = Atom.gerbonara
    general: GeneralSection = None
    page: PageSettings = None
    layers: Named(Array(Untagged(LayerSettings))) = field(default_factory=list)
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
    images: List(gr.Image) = field(default_factory=list)
    # Tracks
    track_segments: List(TrackSegment) = field(default_factory=list)
    track_arcs: List(TrackArc) = field(default_factory=list)
    vias: List(Via) = field(default_factory=list)
    # Other stuff
    zones: List(Zone) = field(default_factory=list)
    groups: List(Group) = field(default_factory=list)
    embedded_fonts: Named(YesNoAtom()) = False

    _ : SEXP_END = None
    original_filename: str = None
    _trace_index: rtree.index.Index = None
    _trace_index_map: dict = None


    @classmethod
    def empty_board(kls, inner_layers=0, **kwargs):
        if 'setup' not in kwargs:
            kwargs['setup'] = None
        b = Board(**kwargs)
        b.init_default_layers(inner_layers)
        b.__after_parse__(None)
        return b


    def init_default_layers(self, inner_layers=0):
        inner = [(i, f'In{i}.Cu', 'signal', None) for i in range(1, inner_layers+1)]
        self.layers = [LayerSettings(idx, name, Atom(ltype)) for idx, name, ltype, cname in [
            (0, 'F.Cu', 'signal', None),
            *inner,
            (31, 'B.Cu', 'signal', None),
            (32, 'B.Adhes', 'user', 'B.Adhesive'),
            (33, 'F.Adhes', 'user', 'F.Adhesive'),
            (34, 'B.Paste', 'user', None),
            (35, 'F.Paste', 'user', None),
            (36, 'B.SilkS', 'user', 'B.Silkscreen'),
            (37, 'F.SilkS', 'user', 'F.Silkscreen'),
            (38, 'B.Mask', 'user', None),
            (39, 'F.Mask', 'user', None),
            (40, 'Dwgs.User', 'user', 'User.Drawings'),
            (41, 'Cmts.User', 'user', 'User.Comments'),
            (42, 'Eco1.User', 'user', 'User.Eco1'),
            (43, 'Eco2.User', 'user', 'User.Eco2'),
            (44, 'Edge.Cuts', 'user', None),
            (45, 'Margin', 'user', None),
            (46, 'B.CrtYd', 'user', 'B.Courtyard'),
            (47, 'F.CrtYd', 'user', 'F.Courtyard'),
            (48, 'B.Fab', 'user', None),
            (49, 'F.Fab', 'user', None),
            (50, 'User.1', 'auxiliary', None),
            (51, 'User.2', 'auxiliary', None),
            (52, 'User.3', 'auxiliary', None),
            (53, 'User.4', 'auxiliary', None),
            (54, 'User.5', 'auxiliary', None),
            (55, 'User.6', 'auxiliary', None),
            (56, 'User.7', 'auxiliary', None),
            (57, 'User.8', 'auxiliary', None),
            (58, 'User.9', 'auxiliary', None)]]


    def rebuild_trace_index(self):
        idx = self._trace_index = rtree.index.Index()
        id_map = self._trace_index_map = {}
        for obj in chain(self.track_segments, self.track_arcs):
            for i, field in enumerate(('start', 'end')):
                obj_id = id(obj) + i
                coord = getattr(obj, field)
                id_map[obj_id] = obj, field, obj.width, obj.layer_mask
                idx.insert(obj_id, (coord.x, coord.y, coord.x, coord.y))

        for fp in self.footprints:
            for pad in fp.pads:
                obj_id = id(pad)
                id_map[obj_id] = pad, 'at', 0, pad.layer_mask
                idx.insert(obj_id, (pad.at.x, pad.at.y, pad.at.x, pad.at.y))

        for via in self.vias:
            obj_id = id(via)
            id_map[obj_id] = via, 'at', via.size, via.layer_mask
            idx.insert(obj_id, (via.at.x, via.at.y, via.at.x, via.at.y))
    

    @staticmethod
    def _require_trace_index(fun):
        @functools.wraps(fun)
        def wrapper(self, *args, **kwargs):
            if self._trace_index is None:
                self.rebuild_trace_index()

            return fun(self, *args, **kwargs)
        return wrapper


    @_require_trace_index
    def query_trace_index_nearest(self, point, layers='*.Cu', n=1):
        layers = layer_mask(layers)

        x, y = point
        for obj_id in self._trace_index.nearest((x, y, x, y), n):
            entry = obj, attr, size, mask = self._trace_index_map[obj_id]
            if layers & mask:
                yield entry


    @_require_trace_index
    def query_trace_index_tolerance(self, point, layers='*.Cu', tol=10e-6):
        layers = layer_mask(layers)

        x, y = point
        for obj_id in self._trace_index.intersection((x-tol, y-tol, x+tol, y+tol)):
            entry = obj, attr, size, mask = self._trace_index_map[obj_id]
            attr = getattr(obj, attr)
            if layers & mask and math.dist((attr.x, attr.y), (x, y)) <= tol:
                yield entry


    def find_connected_traces(self, obj, layers='*.Cu', tol=10e-6):
        search_frontier = []
        visited = set()
        def enqueue(obj):
            visited.add(id(obj))

            if isinstance(obj, (TrackSegment, TrackArc)):
                search_frontier.append((obj.start, obj.width, obj.layer_mask))
                search_frontier.append((obj.end, obj.width, obj.layer_mask))

            elif isinstance(obj, Via):
                search_frontier.append((obj.at, obj.size, obj.layer_mask))

            elif isinstance(obj, Pad):
                search_frontier.append((obj.at, max(obj.size.x, obj.size.y), obj.layer_mask))

            elif isinstance(obj, (Footprint)):
                for pad in obj.pads:
                    search_frontier.append((pad.at, max(pad.size.x, pad.size.y), pad.layer_mask))

            else:
                raise TypeError(f'Finding connected traces for {type(obj)} objects is not (yet) supported.')

        enqueue(obj)
        yield obj

        filter_layers = layer_mask(layers)
        while search_frontier:
            coord, size, layers = search_frontier.pop()
            x, y = coord.x, coord.y

            # First, find all bounding box intersections
            found = []
            for cand, attr, cand_size, cand_mask in self.query_trace_index_tolerance((x, y), layers&filter_layers, size):
                cand_coord = getattr(cand, attr)
                dist = math.dist((x, y), (cand_coord.x, cand_coord.y))
                if dist <= size/2 + cand_size/2 and layers&cand_mask:
                    found.append((dist, cand))

            if not found:
                continue

            # Second, filter to match only objects that are within tolerance of closest
            min_dist = min(e[0] for e in found)
            for dist, cand in found:
                if dist < min_dist+tol and id(cand) not in visited:
                    enqueue(cand)
                    yield cand


    def __after_parse__(self, parent):
        self.properties = {prop.key: prop.value for prop in self.properties}

        for fp in self.footprints:
            fp.board = self

        self.nets = {net.index: net.name for net in self.nets}


    def __before_sexp__(self):
        self.properties = [Property(key, value) for key, value in self.properties.items()]
        self.nets = [Net(index, name) for index, name in self.nets.items()]


    def remove(self, obj):
        match obj:
            case gr.Text():
                self.texts.remove(obj)
            case gr.TextBox():
                self.text_boxes.remove(obj)
            case gr.Line():
                self.lines.remove(obj)
            case gr.Rectangle():
                self.rectangles.remove(obj)
            case gr.Circle():
                self.circles.remove(obj)
            case gr.Arc():
                self.arcs.remove(obj)
            case gr.Polygon():
                self.polygons.remove(obj)
            case gr.Curve():
                self.curves.remove(obj)
            case gr.Dimension():
                self.dimensions.remove(obj)
            case gr.Image():
                self.images.remove(obj)
            case TrackSegment():
                self.track_segments.remove(obj)
            case TrackArc():
                self.track_arcs.remove(obj)
            case Via():
                self.vias.remove(obj)
            case Zone():
                self.zones.remove(obj)
            case Group():
                self.groups.remove(obj)
            case Footprint():
                self.footprints.remove(obj)
            case _:
                raise TypeError('Can only remove KiCad objects, cannot map generic gerbonara.cad objects for removal')


    def remove_many(self, iterable):
        iterable = {id(obj) for obj in iterable}
        for field in fields(self):
            if field.default_factory is list and field.name not in ('nets', 'properties'):
                setattr(self, field.name, [obj for obj in getattr(self, field.name) if id(obj) not in iterable])


    def add(self, obj):
        match obj:
            case gr.Text():
                self.texts.append(obj)
            case gr.TextBox():
                self.text_boxes.append(obj)
            case gr.Line():
                self.lines.append(obj)
            case gr.Rectangle():
                self.rectangles.append(obj)
            case gr.Circle():
                self.circles.append(obj)
            case gr.Arc():
                self.arcs.append(obj)
            case gr.Polygon():
                self.polygons.append(obj)
            case gr.Curve():
                self.curves.append(obj)
            case gr.Dimension():
                self.dimensions.append(obj)
            case gr.Image():
                self.images.append(obj)
            case TrackSegment():
                self.track_segments.append(obj)
            case TrackArc():
                self.track_arcs.append(obj)
            case Via():
                self.vias.append(obj)
            case Zone():
                self.zones.append(obj)
            case Group():
                self.groups.append(obj)
            case Footprint():
                self.footprints.append(obj)
                obj.board = self
            case _:
                for elem in self.map_gn_cad(obj):
                    self.add(elem)


    def map_gn_cad(self, obj, locked=False, net_name=None):
        match obj:
            case cad_pr.Trace():
                for elem in obj.to_graphic_objects():
                    elem.convert_to(MM)
                    match elem:
                        case go.Arc(x1, y1, x2, y2, xc, yc, cw, ap):
                            yield TrackArc(
                                start=XYCoord(x1, y1),
                                mid=XYCoord(x1+xc, y1+yc),
                                end=XYCoord(x2, y2),
                                width=ap.equivalent_width(MM),
                                layer=gn_side_to_kicad(obj.side),
                                locked=locked, 
                                net=self.net_id(net_name))

                        case go.Line(x1, y1, x2, y2, ap):
                            yield TrackSegment(
                                start=XYCoord(x1, y1),
                                end=XYCoord(x2, y2),
                                width=ap.equivalent_width(MM),
                                layer=gn_side_to_kicad(obj.side),
                                locked=locked,
                                net=self.net_id(net_name))

            case cad_pr.Via(pad_stack=cad_pr.ThroughViaStack(hole, dia, unit=st_unit)):
                x, y, _a, _f = obj.abs_pos
                x, y = MM(x, st_unit), MM(y, obj.unit)
                yield Via(
                    locked=locked,
                    at=XYCoord(x, y),
                    size=MM(dia, st_unit),
                    drill=MM(hole, st_unit),
                    layers='*.Cu',
                    net=self.net_id(net_name))

            case cad_pr.Text(_x, _y, text, font_size, stroke_width, h_align, v_align, layer, dark):
                x, y, a, flip = obj.abs_pos
                x, y = MM(x, st_unit), MM(y, st_unit)
                size = MM(size, unit)
                yield gr.Text(
                    text, 
                    AtPos(x, y, -math.degrees(a)),
                    layer=gr.TextLayer(gn_layer_to_kicad(layer, flip), not dark),
                    effects=TextEffect(font=FontSpec(
                            size=XYCoord(size, size),
                            thickness=stroke_width),
                        justify=Justify(h=Atom(h_align) if h_align != 'center' else None,
                                        v=Atom(v_align) if v_align != 'middle' else None,
                                        mirror=flip)))


    def unfill_zones(self):
        for zone in self.zones:
            zone.unfill()


    def find_pads(self, net=None):
        for fp in self.footprints:
            for pad in fp.pads:
                if net and not match_filter(net, pad.net.name):
                    continue
                yield pad


    def find_footprints(self, value=None, reference=None, name=None, net=None, sheetname=None, sheetfile=None):
        for fp in self.footprints:
            if name and not match_filter(name, fp.name):
                continue
            if value and not match_filter(value, fp.value):
                continue
            if reference and not match_filter(reference, fp.reference):
                continue
            if net and not any(pad.net and match_filter(net, pad.net.name) for pad in fp.pads):
                continue
            if sheetname and not match_filter(sheetname, fp.sheetname):
                continue
            if sheetfile and not match_filter(sheetfile, fp.sheetfile):
                continue
            yield fp


    def find_traces(self, net=None, include_vias=True):
        net_id = self.net_id(net, create=False)
        match = lambda obj: obj.net == net_id
        for obj in chain(self.track_segments, self.track_arcs, self.vias):
            if obj.net == net_id:
                yield obj


    @property
    def version(self):
        return self._version


    @version.setter
    def version(self, value):
        if value not in SUPPORTED_FILE_FORMAT_VERSIONS:
            raise FormatError(f'File format version {value} is not supported. Supported versions are {", ".join(map(str, SUPPORTED_FILE_FORMAT_VERSIONS))}.')


    def write(self, filename=None):
        with open(filename or self.original_filename, 'w') as f:
            f.write(self.serialize())


    def serialize(self):
        return build_sexp(sexp(type(self), self)[0])


    @classmethod
    def open(kls, pcb_file, *args, **kwargs):
        return kls.load(Path(pcb_file).read_text(), *args, **kwargs, original_filename=pcb_file)


    @classmethod
    def load(kls, data, *args, **kwargs):
        return kls.parse(data, *args, **kwargs)


    @property
    def single_sided(self):
        raise NotImplementedError()


    def net_id(self, name, create=True):
        if name is None:
            return None

        for i, n in self.nets.items():
            if n == name:
                return i

        if create:
            index = max(self.nets.keys()) + 1
            self.nets[index] = name
            return index

        else:
            raise IndexError(f'No such net: "{name}"')


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
        return chain(self.graphic_objects(text=text, images=images), self.tracks(vias=vias), self.footprints, self.zones, self.groups)


    def render(self, layer_stack, layer_map, x=0, y=0, rotation=0, text=False, flip=False, variables={}, cache=None):
        for obj in self.objects(images=False, vias=False, text=text):
            if not (layer := layer_map.get(obj.layer)):
                continue

            for fe in obj.render(variables=variables):
                fe.rotate(rotation)
                fe.offset(x, -y, MM)
                layer_stack[layer].objects.append(fe)

        for obj in self.vias:
            for glob in obj.layers or []:
                for layer in fnmatch.filter(layer_map, glob):
                    for fe in obj.render(cache=cache):
                        fe.rotate(rotation)
                        fe.offset(x, -y, MM)
                        fe.aperture = fe.aperture.rotated(rotation)
                        layer_stack[layer_map[layer]].objects.append(fe)

            for fe in obj.render_drill():
                fe.rotate(rotation)
                fe.offset(x, -y, MM)
                layer_stack.drill_pth.append(fe)

@dataclass
class BoardInstance(cad_pr.Positioned):
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

