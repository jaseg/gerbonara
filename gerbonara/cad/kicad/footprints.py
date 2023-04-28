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
from ...layers import LayerStack
from ...newstroke import Newstroke
from ...utils import MM, rotate_point, offset_bounds, sum_bounds
from ...aperture_macros.parse import GenericMacros, ApertureMacro
from ...aperture_macros import primitive as amp


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

    def render(self, variables={}, cache=None):
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

    def render(self, variables={}, cache=None):
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

    def render(self, variables=None, cache=None):
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

    def render(self, variables=None, cache=None):
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        w, h = x2-x1, y2-y1

        if self.fill == Atom.solid:
            yield go.Region.from_rectangle(x1, y1, w, h, unit=MM)

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

    def render(self, variables=None, cache=None):
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


    def render(self, variables=None, cache=None):
        mx, my = self.mid.x, self.mid.y
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        dasher = Dasher(self)
        aperture = ap.CircleAperture(dasher.width, unit=MM)

        if math.isclose(x1, x2, abs_tol=1e-6) and math.isclose(y1, y2, abs_tol=1e-6):
            cx = (x1 + mx) / 2
            cy = (y1 + my) / 2
            arc = go.Arc(x1, y1, x2, y2, cx-x1, cy-y1, clockwise=True, aperture=aperture, unit=MM)
            if dasher.solid:
                yield arc

            else:
                # use approximation from graphic object arc class 
                for line in arc.approximate():
                    dasher.segments.append((line.x1, line.y1, line.x2, line.y2))
                
                for line in dasher:
                    yield go.Line(x1, y1, x2, y2, aperture=ap.CircleAperture(dasher.width, unit=MM), unit=MM)

        else:
            # https://stackoverflow.com/questions/56224824/how-do-i-find-the-circumcenter-of-the-triangle-using-python-without-external-lib
            d = 2 * (x1 * (y2 - my) + x2 * (my - y1) + mx * (y1 - y2))
            cx = ((x1 * x1 + y1 * y1) * (y2 - my) + (x2 * x2 + y2 * y2) * (my - y1) + (mx * mx + my * my) * (y1 - y2)) / d
            cy = ((x1 * x1 + y1 * y1) * (mx - x2) + (x2 * x2 + y2 * y2) * (x1 - mx) + (mx * mx + my * my) * (x2 - x1)) / d

        # KiCad only has clockwise arcs.
        arc = go.Arc(x1, y1, x2, y2, cx-x1, cy-y1, clockwise=False, aperture=aperture, unit=MM)
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

    def render(self, variables=None, cache=None):
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

    def render(self, variables=None, cache=None):
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

    def render(self, variables=None, cache=None):
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

    def render(self, variables=None, margin=None, cache=None):
        #if self.type in (Atom.connect, Atom.np_thru_hole):
        #    return
        if self.drill and self.drill.offset:
            ox, oy = rotate_point(self.drill.offset.x, self.drill.offset.y, math.radians(self.at.rotation))
        else:
            ox, oy = 0, 0

        cache_key = id(self), margin
        if cache and cache_key in cache:
            aperture = cache[cache_key]

        elif cache is not None:
            aperture = cache[cache_key] = self.aperture(margin)

        else:
            aperture = self.aperture(margin)

        yield go.Flash(self.at.x+ox, self.at.y+oy, aperture, unit=MM)

    def aperture(self, margin=None):
        rotation = -math.radians(self.at.rotation)
        margin = margin or 0

        if self.shape == Atom.circle:
            return ap.CircleAperture(self.size.x+2*margin, unit=MM)

        elif self.shape == Atom.rect:
            if margin > 0:
                return ap.ApertureMacroInstance(GenericMacros.rounded_rect,
                        (self.size.x+2*margin, self.size.y+2*margin,
                         margin,
                         0, 0, # no hole
                         rotation), unit=MM)
            else:
                return ap.RectangleAperture(self.size.x+2*margin, self.size.y+2*margin, unit=MM).rotated(rotation)

        elif self.shape == Atom.oval:
            return ap.ObroundAperture(self.size.x+2*margin, self.size.y+2*margin, unit=MM).rotated(rotation)

        elif self.shape == Atom.trapezoid:
            # KiCad's trapezoid aperture "rect_delta" param is just weird to the point that I think it's probably
            # bugged. If you have a size of 2mm by 2mm, and set this param to 1mm, the resulting pad extends past the
            # original bounding box, and the trapezoid's base and tip length are 3mm and 1mm.

            x, y = self.size.x, self.size.y
            if self.rect_delta:
                dx, dy = self.rect_delta.x, self.rect_delta.y
            else: # RF_Antenna/Pulse_W3011 has trapezoid pads w/o rect_delta, which KiCad renders as plain rects.
                dx, dy = 0, 0

            if dx != 0:
                x, y = y, x
                dy = dx
                rotation -= math.pi/2

            if margin <= 0:
                # Note: KiCad already uses MM units, so no conversion needed here.

                alpha = math.atan(y / dy) if dy > 0 else 0
                return ap.ApertureMacroInstance(GenericMacros.isosceles_trapezoid,
                        (x+dy+2*margin*math.cos(alpha), y+2*margin,
                         2*dy,
                         0, 0, # no hole
                         rotation), unit=MM)

            else:
                return ap.ApertureMacroInstance(GenericMacros.rounded_isosceles_trapezoid,
                        (x+dy, y,
                         2*dy, margin,
                         0, 0, # no hole
                         rotation), unit=MM)

        elif self.shape == Atom.roundrect:
            x, y = self.size.x, self.size.y
            r = min(x, y) * self.roundrect_rratio
            if margin > -r:
                return ap.ApertureMacroInstance(GenericMacros.rounded_rect,
                        (x+2*margin, y+2*margin,
                         r+margin,
                         0, 0, # no hole
                         rotation), unit=MM)
            else:
                return ap.RectangleAperture(x+margin, y+margin, unit=MM).rotated(rotation)

        elif self.shape == Atom.custom:
            primitives = []

            # One round trip through the Gerbonara APIs, please!
            for obj in self.primitives.all():
                for gn_obj in obj.render():
                    if margin and isinstance(gn_obj, (go.Line, go.Arc)):
                        gn_obj = gn_obj.dilated(margin)

                    if isinstance(gn_obj, go.Region) and margin > 0:
                        for line in gn_obj.outline_objects(ap.CircleAperture(2*margin, unit=MM)):
                            primitives += line._aperture_macro_primitives()

                    new_primitives = list(gn_obj._aperture_macro_primitives()) # todo: precision params
                    primitives += new_primitives

                    # inexact, only works with convex shapes. But whatever, the only other way to do this would require
                    # an entire polygon clipping/offsetting library. Probably a bad choice to put something this complex
                    # into a file format.
                    if isinstance(gn_obj, go.Region) and margin < 0:
                        for line in gn_obj.outline_objects(ap.CircleAperture(2*margin, unit=MM)):
                            line.polarity_dark = False
                            primitives += line._aperture_macro_primitives()

            if self.options:
                if self.options.anchor == Atom.rect and self.size.x > 0 and self.size.y > 0:
                    if margin <= 0:
                        primitives.append(amp.CenterLine(MM, 1, self.size.x+2*margin, self.size.y+2*margin, 0, 0, 0))

                    else: # margin > 0
                        primitives.append(amp.CenterLine(MM, 1, self.size.x+2*margin, self.size.y, 0, 0, 0))
                        primitives.append(amp.CenterLine(MM, 1, self.size.x, self.size.y+2*margin, 0, 0, 0))
                        primitives.append(amp.Circle(MM, 1, 2*margin, -self.size.x/2, -self.size.y/2))
                        primitives.append(amp.Circle(MM, 1, 2*margin, -self.size.x/2, +self.size.y/2))
                        primitives.append(amp.Circle(MM, 1, 2*margin, +self.size.x/2, -self.size.y/2))
                        primitives.append(amp.Circle(MM, 1, 2*margin, +self.size.x/2, +self.size.y/2))

                elif self.options.anchor == Atom.circle and self.size.x > 0:
                    primitives.append(amp.Circle(MM, 1, self.size.x+2*margin, 0, 0, 0))

            macro = ApertureMacro(primitives=tuple(primitives)).rotated(rotation)
            return ap.ApertureMacroInstance(macro, unit=MM)

    def render_drill(self):
        if not self.drill:
            return

        plated = self.type != Atom.np_thru_hole
        if self.drill.oval:
            dia = self.drill.diameter
            w = self.drill.width

            if self.drill.offset:
                ox, oy = self.drill.offset.x, self.drill.offset.y
            else:
                ox, oy = 0, 0
            
            if w > dia:
                dx = 0
                dy = (w-dia)/2
            else:
                dx = (dia-w)/2
                dy = 0

            aperture = ap.ExcellonTool(min(dia, w), plated=plated, unit=MM)
            l = go.Line(ox-dx, oy-dy, ox+dx, oy+dy, aperture=aperture, unit=MM) 
            l.rotate(math.radians(self.at.rotation))
            l.offset(self.at.x, self.at.y)
            yield l

        else:
            aperture = ap.ExcellonTool(self.drill.diameter, plated=plated, unit=MM)
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

    def render(self, layer_stack, layer_map, x=0, y=0, rotation=0, text=False, side=None, variables={}, cache=None):
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
            if self.solder_mask_margin is not None:
                solder_mask_margin = self.solder_mask_margin
            elif obj.solder_mask_margin is not None:
                solder_mask_margin = obj.solder_mask_margin
            else:
                solder_mask_margin = None

            if self.solder_paste_margin is not None:
                solder_paste_margin = self.solder_paste_margin
            elif obj.solder_paste_margin_ratio is not None:
                solder_paste_margin = max(obj.size.x, obj.size.y) * obj.solder_paste_margin_ratio
            elif obj.solder_paste_margin is not None:
                solder_paste_margin = obj.solder_paste_margin
            else:
                solder_paste_margin = None

            for glob in obj.layers or []:
                for layer in fnmatch.filter(layer_map, glob):

                    if layer.endswith('.Mask'):
                        margin = solder_mask_margin
                    elif layer.endswith('.Paste'):
                        margin = solder_paste_margin
                    else:
                        margin = None

                    for fe in obj.render(margin=margin, cache=cache):
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
    
    def bounding_box(self, unit=MM):
        if not self._bounding_box:
            stack = LayerStack()
            layer_map = {kc_id: gn_id for kc_id, gn_id in LAYER_MAP_K2G.items() if gn_id in stack}
            self.render(stack, layer_map, x=0, y=0, rotation=0, side='top', text=False, variables={})
            self._bounding_box = stack.bounding_box(unit)
        return self._bounding_box

        

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
        'B.Adhes': ('bottom', 'adhesive'),
        'F.Adhes': ('top', 'adhesive'),
        'Dwgs.User': ('mechanical', 'drawings'),
        'Cmts.User': ('mechanical', 'comments'),
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

    def render(self, layer_stack, cache=None):
        x, y, rotation = self.abs_pos
        x, y = MM(x, self.unit), MM(y, self.unit)

        variables = dict(self.variables)

        if self.reference is not None:
            variables['REFERENCE'] = str(self.reference)

        if self.value is not None:
            variables['VALUE'] = str(self.value)

        layer_map = {kc_id: gn_id for kc_id, gn_id in LAYER_MAP_K2G.items() if gn_id in layer_stack}

        self.sexp.render(layer_stack, layer_map,
                         x=x, y=y, rotation=rotation,
                         side=self.side,
                         text=(not self.hide_text),
                         variables=variables, cache=cache)
    
    def bounding_box(self, unit=MM):
        return offset_bounds(self.sexp.bounding_box(unit), unit(self.x, self.unit), unit(self.y, self.unit))

if __name__ == '__main__':
    import sys
    from ...layers import LayerStack
    fp = Footprint.open_mod(sys.argv[1])
    stack = LayerStack()
    FootprintInstance(0, 0, fp, unit=MM).render(stack)
    print(stack.to_pretty_svg())
    stack.save_to_directory('/tmp/testdir')

