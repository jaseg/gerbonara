
import sys
import math
import warnings
from copy import copy
from itertools import zip_longest, chain
from dataclasses import dataclass, field, KW_ONLY
from collections import defaultdict

from ..utils import LengthUnit, MM, rotate_point, svg_arc, sum_bounds, bbox_intersect, Tag
from ..layers import LayerStack
from ..graphic_objects import Line, Arc, Flash
from ..apertures import Aperture, CircleAperture, ObroundAperture, RectangleAperture, ExcellonTool
from ..newstroke import Newstroke


def sgn(x):
    return -1 if x < 0 else 1


class KeepoutError(ValueError):
    def __init__(self, obj, keepout, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.obj = obj
        self.keepout = keepout


newstroke_font = None


class Board:
    def __init__(self, w=None, h=None, corner_radius=1.5, center=False, default_via_hole=0.4, default_via_diameter=0.8, x=0, y=0, rotation=0, unit=MM):
        self.x, self.y = x, y
        self.rotation = 0
        self.objects = []
        self.outline = []
        self.extra_silk_top = []
        self.extra_silk_bottom = []
        self.keepouts = []
        self.default_via_hole = MM(default_via_hole, unit)
        self.default_via_diameter = MM(default_via_diameter, unit)
        self.unit = unit
        if w or h:
            if w and h:
                self.rounded_rect_outline(w, h, r=corner_radius, center=center)
                self.w, self.h = w, h
            else:
                raise ValueError('Either both, w and h, or neither of them must be given.')
        else:
            self.w = self.h = None

    @property
    def abs_pos(self):
        return self.x, self.y, self.rotation

    def add_silk(self, side, obj):
        if side not in ('top', 'bottom'):
            raise ValueError('side must be one of "top" or "bottom".')

        if side == 'top':
            self.extra_silk_top.append(obj)
        else:
            self.extra_silk_bottom.append(obj)

    def add_text(self, *args, **kwargs):
        self.objects.append(Text(*args, **kwargs))

    def add_keepout(self, bbox, unit=MM):
        ((_x_min, _y_min), (_x_max, _y_max)) = bbox
        self.keepouts.append(MM.convert_bounds_from(unit, bbox))

    def add(self, obj, keepout_errors='raise'):
        if keepout_errors not in ('ignore', 'raise', 'warn', 'skip'):
            raise ValueError('keepout_errors must be one of "ignore", "raise", "warn" or "skip".')

        if keepout_errors != 'ignore':
            for ko in self.keepouts:
                if obj.overlaps(ko, unit=MM):
                    if keepout_errors == 'warn':
                        warnings.warn(msg)
                    elif keepout_errors == 'raise':
                        raise KeepoutError(obj, ko, msg)
                    return

        obj.parent = self
        self.objects.append(obj)

    def via(self, x, y, diameter=None, hole=None, keepout_errors='raise', unit=MM):
        diameter = diameter or unit(self.default_via_dia, MM)
        hole = hole or unit(self.default_via_hole, MM)
        obj = Via(x, y, diameter, hole, unit=unit, keepout_errors=keepout_errors)
        self.add(obj)
        return obj

    def rounded_rect_outline(self, w, h, r=0, x0=None, y0=None, center=False, unit=MM):
        if x0 is None:
            x0 = -w/2 if center else 0
        if y0 is None:
            y0 = -h/2 if center else 0

        ap = CircleAperture(0.05, unit=MM)

        self.outline.append(Line(x0+r, y0, x0+w-r, y0, ap, unit=unit))
        if r:
            self.outline.append(Arc(x0+w-r, y0, x0+w, y0+r, 0, r, False, ap, unit=unit))
        self.outline.append(Line(x0+w, y0+r, x0+w, y0+h-r, ap, unit=unit))
        if r:
            self.outline.append(Arc(x0+w, y0+h-r, x0+w-r, y0+h, -r, 0, False, ap, unit=unit))
        self.outline.append(Line(x0+w-r, y0+h, x0+r, y0+h, ap, unit=unit))
        if r:
            self.outline.append(Arc(x0+r, y0+h, x0, y0+h-r, 0, -r, False, ap, unit=unit))
        self.outline.append(Line(x0, y0+h-r, x0, y0+r, ap, unit=unit))
        if r:
            self.outline.append(Arc(x0, y0+r, x0+r, y0, r, 0, False, ap, unit=unit))

    def layer_stack(self, layer_stack=None):
        if layer_stack is None:
            layer_stack = LayerStack()

        for obj in chain(self.objects):
            obj.render(layer_stack)

        layer_stack['mechanical', 'outline'].objects.extend(self.outline)
        layer_stack['top', 'silk'].objects.extend(self.extra_silk_top)
        layer_stack['bottom', 'silk'].objects.extend(self.extra_silk_bottom)

        return layer_stack

    def svg(self, margin=0, arg_unit=MM, svg_unit=MM, force_bounds=None):
        return self.layer_stack().to_svg(margin=margin, arg_unit=arg_unit, svg_unit=svg_unit,
                                                 force_bounds=force_bounds)

    def pretty_svg(self, side='top', margin=0, arg_unit=MM, svg_unit=MM, force_bounds=None, inkscape=False, colors=None):
        return self.layer_stack().to_pretty_svg(side=side, margin=margin, arg_unit=arg_unit, svg_unit=svg_unit,
                                                   force_bounds=force_bounds, inkscape=inkscape, colors=colors)


@dataclass
class Positioned:
    x: float
    y: float
    _: KW_ONLY
    rotation: float = 0.0
    side: str = 'top'
    unit: LengthUnit = MM
    parent: object = None

    def flip(self):
        self.side = 'top' if self.side == 'bottom' else 'bottom'

    @property
    def abs_pos(self):
        if self.parent is None:
            px, py, pa = 0, 0, 0
        else:
            px, py, pa = self.parent.abs_pos

        return self.x+px, self.y+py, self.rotation+pa

    def bounding_box(self, unit=MM):
        stack = LayerStack()
        self.render(stack)
        objects = chain(*(l.objects for l in stack.graphic_layers.values()),
                        stack.drill_pth.objects, stack.drill_npth.objects)
        objects = list(objects)
        #print('foo', type(self).__name__,
        #      [(type(obj).__name__, [prim.bounding_box() for prim in obj.to_primitives(unit)]) for obj in objects], file=sys.stderr)
        return sum_bounds(prim.bounding_box() for obj in objects for prim in obj.to_primitives(unit))

    def overlaps(self, bbox, unit=MM):
        return bbox_intersect(self.bounding_box(unit), bbox)

    @property
    def single_sided(self):
        return True


@dataclass
class ObjectGroup(Positioned):
    top_copper: list = field(default_factory=list)
    top_mask: list = field(default_factory=list)
    top_silk: list = field(default_factory=list)
    top_paste: list = field(default_factory=list)
    bottom_copper: list = field(default_factory=list)
    bottom_mask: list = field(default_factory=list)
    bottom_silk: list = field(default_factory=list)
    bottom_paste: list = field(default_factory=list)
    drill_npth: list = field(default_factory=list)
    drill_pth: list = field(default_factory=list)
    objects: list = field(default_factory=list)

    def render(self, layer_stack):
        x, y, rotation = self.abs_pos
        top, bottom = ('bottom', 'top') if self.side == 'bottom' else ('top', 'bottom')

        for obj in self.objects:
            obj.parent = self
            obj.render(layer_stack)

        for target, source in [
                (layer_stack[top, 'copper'],    self.top_copper),
                (layer_stack[top, 'mask'],      self.top_mask),
                (layer_stack[top, 'silk'],      self.top_silk),
                (layer_stack[top, 'paste'],     self.top_paste),
                (layer_stack[bottom, 'copper'], self.bottom_copper),
                (layer_stack[bottom, 'mask'],   self.bottom_mask),
                (layer_stack[bottom, 'silk'],   self.bottom_silk),
                (layer_stack[bottom, 'paste'],  self.bottom_paste),
                (layer_stack.drill_pth,         self.drill_pth),
                (layer_stack.drill_npth,        self.drill_npth)]:

            for fe in source:
                fe = copy(fe)
                fe.rotate(rotation)
                fe.offset(x, y, self.unit)
                target.objects.append(fe)

    @property
    def single_sided(self):
        any_top = self.top_copper or self.top_mask or self.top_paste or self.top_silk
        any_bottom = self.bottom_copper or self.bottom_mask or self.bottom_paste or self.bottom_silk
        any_drill = self.drill_npth or self.drill_pth
        return not (any_drill or (any_top and any_bottom))


@dataclass
class Text(Positioned):
    text: str
    font_size: float = 2.5
    stroke_width: float = 0.25
    h_align: str = 'left'
    v_align: str = 'bottom'
    layer: str = 'silk'
    polarity_dark: bool = True

    def render(self, layer_stack):
        obj_x, obj_y, rotation = self.abs_pos
        global newstroke_font

        if newstroke_font is None:
            newstroke_font = Newstroke()

        strokes = list(newstroke_font.render(self.text, size=self.font_size))
        if not strokes:
            return

        xs = [x for points in strokes for x, _y in points]
        ys = [y for points in strokes for _x, y in points]
        min_x, min_y, max_x, max_y = min(xs), min(ys), max(xs), max(ys)

        if self.h_align == 'left':
            x0 = 0
        elif self.h_align == 'center':
            x0 = -max_x/2
        elif self.h_align == 'right':
            x0 = -max_x
        else:
            raise ValueError('h_align must be one of "left", "center", or "right".')

        if self.v_align == 'top':
            y0 = -(max_y - min_y)
        elif self.v_align == 'middle':
            y0 = -(max_y - min_y)/2
        elif self.v_align == 'bottom':
            y0 = 0
        else:
            raise ValueError('v_align must be one of "top", "middle", or "bottom".')

        if self.side == 'bottom':
            x0 += min_x + max_x
            x_sign = -1
        else:
            x_sign = 1

        ap = CircleAperture(self.stroke_width, unit=self.unit)

        for stroke in strokes:
            for (x1, y1), (x2, y2) in zip(stroke[:-1], stroke[1:]):
                obj = Line(x0+x_sign*x1, y0-y1, x0+x_sign*x2, y0-y2, aperture=ap, unit=self.unit, polarity_dark=self.polarity_dark)
                obj.rotate(rotation)
                obj.offset(obj_x, obj_y)
                layer_stack[self.side, self.layer].objects.append(obj)


@dataclass
class Pad(Positioned):
    pass


@dataclass
class SMDPad(Pad):
    copper_aperture: Aperture
    mask_aperture: Aperture
    paste_aperture: Aperture
    silk_features: list = field(default_factory=list)

    def render(self, layer_stack):
        x, y, rotation = self.abs_pos
        layer_stack[self.side, 'copper'].objects.append(Flash(x, y, self.copper_aperture.rotated(rotation), unit=self.unit))
        layer_stack[self.side, 'mask'  ].objects.append(Flash(x, y, self.mask_aperture.rotated(rotation), unit=self.unit))
        if self.paste_aperture:
            layer_stack[self.side, 'paste' ].objects.append(Flash(x, y, self.paste_aperture.rotated(rotation), unit=self.unit))
        layer_stack[self.side, 'silk'  ].objects.extend([copy(feature).rotate(rotation).offset(x, y, self.unit)
                                                 for feature in self.silk_features])

    @classmethod
    def rect(kls, x, y, w, h, rotation=0, side='top', mask_expansion=0.0, paste_expansion=0.0, paste=True, unit=MM):
        ap_c = RectangleAperture(w, h, unit=unit)
        ap_m = RectangleAperture(w+2*mask_expansion, h+2*mask_expansion, unit=unit)
        ap_p = RectangleAperture(w+2*paste_expansion, h+2*paste_expansion, unit=unit) if paste else None
        return kls(x, y, side=side, copper_aperture=ap_c, mask_aperture=ap_m, paste_aperture=ap_p, rotation=rotation,
                      unit=unit)

    @classmethod
    def circle(kls, x, y, dia, side='top', mask_expansion=0.0, paste_expansion=0.0, paste=True, unit=MM):
        ap_c = CircleAperture(dia, unit=unit)
        ap_m = CircleAperture(dia+2*mask_expansion, unit=unit)
        ap_p = CircleAperture(dia+2*paste_expansion, unit=unit) if paste else None
        return kls(x, y, side=side, copper_aperture=ap_c, mask_aperture=ap_m, paste_aperture=ap_p, unit=unit)
    

@dataclass
class THTPad(Pad):
    drill_dia: float
    pad_top: SMDPad
    pad_bottom: SMDPad = None
    aperture_inner: Aperture = None
    plated: bool = True

    def __post_init__(self):
        if self.pad_bottom is None:
            import sys
            self.pad_bottom = copy(self.pad_top)
            self.pad_bottom.flip()

        self.pad_top.parent = self.pad_bottom.parent = self

        if (self.pad_top.side, self.pad_bottom.side) != ('top', 'bottom'):
            raise ValueError(f'The top and bottom pads must have side set to top and bottom, respectively. Currently, the top pad side is set to "{self.pad_top.side}" and the bottom pad side to "{self.pad_bottom.side}".')

    def render(self, layer_stack):
        x, y, rotation = self.abs_pos
        self.pad_top.parent = self
        self.pad_top.render(layer_stack)
        if self.pad_bottom:
            self.pad_bottom.parent = self
            self.pad_bottom.render(layer_stack)

        if self.aperture_inner is None:
            (x_min, y_min), (x_max, y_max) = self.pad_top.bounding_box(MM)
            w_top = x_max - x_min
            h_top = y_max - y_min
            if self.pad_bottom:
                (x_min, y_min), (x_max, y_max) = self.pad_bottom.bounding_box(MM)
                w_bottom = x_max - x_min
                h_bottom = y_max - y_min
                w_top = min(w_top, w_bottom)
                h_top = min(h_top, h_bottom)
            self.aperture_inner = CircleAperture(min(w_top, h_top), unit=MM)

        for (side, use), layer in layer_stack.inner_layers:
            layer.objects.append(Flash(x, y, self.aperture_inner.rotated(rotation), unit=self.unit))

        hole = Flash(x, y, ExcellonTool(self.drill_dia, plated=self.plated, unit=self.unit), unit=self.unit)
        if self.plated:
            layer_stack.drill_pth.objects.append(hole)
        else:
            layer_stack.drill_npth.objects.append(hole)

    @property
    def single_sided(self):
        return False

    @classmethod
    def rect(kls, x, y, hole_dia, w, h=None, rotation=0, mask_expansion=0.0, paste_expansion=0.0, paste=True, plated=True, unit=MM):
        if h is None:
            h = w
        pad = SMDPad.rect(0, 0, w, h, mask_expansion=mask_expansion, paste_expansion=paste_expansion, paste=paste, unit=unit)
        return kls(x, y, hole_dia, pad, rotation=rotation, plated=plated, unit=unit)

    @classmethod
    def circle(kls, x, y, hole_dia, dia, mask_expansion=0.0, paste_expansion=0.0, paste=True, plated=True, unit=MM):
        pad = SMDPad.circle(0, 0, dia, mask_expansion=mask_expansion, paste_expansion=paste_expansion, paste=paste, unit=unit)
        return kls(x, y, hole_dia, pad, plated=plated, unit=unit)

    @classmethod
    def obround(kls, x, y, hole_dia, w, h, rotation=0, mask_expansion=0.0, paste_expanson=0.0, paste=True, plated=True, unit=MM):
        ap_c = ObroundAperture(w, h, unit=unit)
        ap_m = ObroundAperture(w+2*mask_expansion, h+2*mask_expansion, unit=unit)
        ap_p = ObroundAperture(w, h, unit=unit) if paste else None
        pad = SMDPad(0, 0, side='top', copper_aperture=ap_c, mask_aperture=ap_m, paste_aperture=ap_p, unit=unit)
        return kls(x, y, hole_dia, pad, rotation=rotation, plated=plated, unit=unit)


@dataclass
class Hole(Positioned):
    diameter: float
    mask_copper_margin: float = 0.2

    def render(self, layer_stack):
        x, y, rotation = self.abs_pos

        hole = Flash(x, y, ExcellonTool(self.diameter, plated=False, unit=self.unit), unit=self.unit)
        layer_stack.drill_npth.objects.append(hole)

        if self.mask_copper_margin > 0:
            mask = Flash(x, y, CircleAperture(self.mask_copper_margin, unit=self.unit), polarity_dark=False, unit=self.unit)
            layer_stack['top', 'copper'].objects.append(mask)
            layer_stack['bottom', 'copper'].objects.append(mask)
    
    @property
    def single_sided(self):
        return False


@dataclass
class Via(Positioned):
    diameter: float
    hole: float

    def render(self, layer_stack):
        x, y, rotation = self.abs_pos

        aperture = CircleAperture(diameter=self.diameter, unit=self.unit)
        tool = ExcellonTool(diameter=self.hole, unit=self.unit)
        
        for (side, use), layer in layer_stack.copper_layers:
            layer.objects.append(Flash(x, y, aperture, unit=self.unit))

        layer_stack.drill_pth.objects.append(Flash(x, y, tool, unit=self.unit))

    @property
    def single_sided(self):
        return False


@dataclass
class Trace:
    width: float
    start: object = None
    end: object = None
    waypoints: [(float, float)] = field(default_factory=list)
    style: str = 'oblique'
    orientation: [str] = tuple() # 'top' or 'bottom'
    roundover: float = 0
    unit: LengthUnit = MM
    parent: object = None

    DIRECT = 'direct'
    OBLIQUE = 'oblique'
    ORTHO = 'ortho'

    CW = 'cw'
    CCW = 'ccw'

    def _route(self, p1, p2, orientation):
        x1, y1 = p1
        x2, y2 = p2
        dx = x2-x1
        dy = y2-y1

        yield p1

        if self.style == 'direct' or \
                math.isclose(x1, x2, abs_tol=1e-6) or math.isclose(y1, y2, abs_tol=1e-6) or \
                (self.style == 'oblique' and math.isclose(dx, dy, abs_tol=1e-6)):
            return

        p = (abs(dy) > abs(dx)) == ((dx >= 0) == (dy >= 0))
        if self.style == 'oblique':
            if p == (orientation == 'cw'):
                if abs(dy) > abs(dx):
                    yield (x1, y1+sgn(dy)*(abs(dy)-abs(dx)))
                else:
                    yield (x1+sgn(dx)*(abs(dx)-abs(dy)), y1)
            else:
                if abs(dy) > abs(dx):
                    yield (x2, y1+sgn(dy)*abs(dx))
                else:
                    yield (x1+sgn(dx)*abs(dy), y2)

        else: # self.style == 'ortho'
            if p == (orientation == 'cw'):
                if abs(dy) > abs(dx):
                    yield (x1, y2)
                else:
                    yield (x2, y1)
            else:
                if abs(dy) > abs(dx):
                    yield (x2, y1)
                else:
                    yield (x1, y2)

    @classmethod
    def _midpoint(kls, p1, p2):
        x1, y1 = p1
        x2, y2 = p2
        dx = x2 - x1
        dy = y2 - y1
        xm = x1 + dx / 2
        ym = y1 + dy / 2
        return (xm, ym)

    @classmethod
    def _point_on_line(kls, p1, p2, dist_from_p1):
        x1, y1 = p1
        x2, y2 = p2
        dx = x2 - x1
        dy = y2 - y1
        dist = math.dist(p1, p2)
        if math.isclose(dist, 0, abs_tol=1e-6):
            return p2
        xm = x1 + dx / dist * dist_from_p1
        ym = y1 + dy / dist * dist_from_p1
        return (xm, ym)

    @classmethod
    def _angle_between(kls, p1, p2, p3):
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        x1, y1 = x1 - x2, y1 - y2
        x3, y3 = x3 - x2, y3 - y2
        dot_product = x1*x3 + y1*y3
        l1 = math.hypot(x1, y1)
        l2 = math.hypot(x3, y3)
        norm = dot_product / l1 / l2
        return math.acos(min(1, max(-1, norm)))

    def _round_over(self, points, aperture):
        if math.isclose(self.roundover, 0, abs_tol=1e-6) or len(points) <= 2:
            import sys
            for p1, p2 in zip(points[:-1], points[1:]):
                yield Line(*p1, *p2, aperture=aperture, unit=self.unit)
            return
        # here: len(points) >= 3

        line_b = Line(*points[0], *self._midpoint(points[0], points[1]), aperture=aperture, unit=self.unit)

        for p1, p2, p3 in zip(points[:-2], points[1:-1], points[2:]):
            x1, y1 = p1
            x2, y2 = p2
            x3, y3 = p3
            xa, ya = pa = self._midpoint(p1, p2)
            xb, yb = pb = self._midpoint(p2, p3)
            la = math.dist(pa, p2)
            lb = math.dist(p2, pb)

            alpha = self._angle_between(p1, p2, p3)
            if alpha == 0:
                l = Line(line_b.x1, line_b.y1, *p2, aperture=aperture, unit=self.unit)
                line_b = Line(*p2, *pb, aperture=aperture, unit=self.unit)
                yield l
                continue
            tr = self.roundover/math.tan(alpha/2)
            t = min(la, lb, tr)
            r = t*math.tan(alpha/2)

            xs, ys = ps = self._point_on_line(p2, pa, t)
            xe, ye = pe = self._point_on_line(p2, pb, t)

            if math.isclose(t, la, abs_tol=1e-6):
                if not math.isclose(line_b.curve_length(), 0, abs_tol=1e-6):
                    yield line_b
                xs, ys = ps = pa
            else:
                yield Line(line_b.x1, line_b.y1, xs, ys, aperture=aperture, unit=self.unit)

            if math.isclose(t, lb, abs_tol=1e-6):
                xe, ye = pe = pb
            line_b = Line(*pe, *pb, aperture=aperture, unit=self.unit)

            if math.isclose(r, 0, abs_tol=1e-6):
                continue

            xc = -(y2 - ys) / t * r
            yc = +(x2 - xs) / t * r

            xsr = xs - x2
            ysr = ys - y2
            xer = xe - x2
            yer = ye - y2
            cross_product_z = xsr * yer - ysr * xer

            clockwise = cross_product_z > 0
            if clockwise:
                xc, yc = -xc, -yc
            
            yield Arc(*ps, *pe, xc, yc, clockwise, aperture=aperture, unit=self.unit)

        yield Line(line_b.x1, line_b.y1, x3, y3, aperture=aperture, unit=self.unit)
        
    def _to_graphic_objects(self):
        start, end = self.start, self.end

        if not isinstance(start, tuple):
            *start, _rotation = start.abs_pos
        if not isinstance(end, tuple):
            *end, _rotation = end.abs_pos

        aperture = CircleAperture(diameter=self.width, unit=self.unit)

        points_in = [start, *self.waypoints, end]

        points = []
        for p1, p2, orientation in zip_longest(points_in[:-1], points_in[1:], self.orientation):
            points.extend(self._route(p1, p2, orientation))
        points.append(p2)

        return self._round_over(points, aperture)

    def render(self, layer_stack):
        layer_stack[self.side, 'copper'].objects.extend(self._to_graphic_objects())

def _route_demo():
    from ..utils import setup_svg, Tag

    def pd_obj(objs):
        objs = list(objs)
        yield f'M {objs[0].x1}, {objs[0].y1}'
        for obj in objs:
            if isinstance(obj, Line):
                yield f'L {obj.x2}, {obj.y2}'
            else:
                assert isinstance(obj, Arc)
                yield svg_arc(obj.p1, obj.p2, obj.center_relative, obj.clockwise)

    pd = lambda points: f'M {points[0][0]}, {points[0][1]} ' + ' '.join(f'L {x}, {y}' for x, y in points[1:])

    font = Newstroke()

    tags = []
    for n in range(0, 8*6):
        theta = 2*math.pi / (8*6) * n
        dx, dy = math.cos(theta), math.sin(theta)

        strokes = list(font.render(f'α={n/(8*6)*360}', size=0.2))
        xs = [x for st in strokes for x, _y in st]
        ys = [y for st in strokes for _x, y in st]
        min_x, min_y, max_x, max_y = min(xs), min(ys), max(xs), max(ys)

        xf = f'translate({n//6*1.1 + 0.1} {n%6*1.3 + 0.3}) scale(0.5 0.5) translate(1 1)'
        txf = f'{xf} translate(0 -1.2) translate({-(max_x-min_x)/2} {-max_y})'

        tags.append(Tag('circle', cx='0', cy='0', r='1',
                        fill='none', stroke='black', opacity='0.5', stroke_width='0.01',
                        transform=xf))
        tags.append(Tag('path',
                        fill='none',
                        stroke='black', opacity='0.5', stroke_width='0.02', stroke_linejoin='round', stroke_linecap='round',
                        transform=txf, d=' '.join(pd(points) for points in strokes)))

        #for r in [0.0, 0.1, 0.2, 0.3]:
        for r in [0, 0.2]:
            #tr = Trace(0.1, style='ortho', roundover=r, start=(0, 0), end=(dx, dy))
            tr = Trace(0.1, style='oblique', roundover=r, start=(dx, dy), end=(0, 0))
            #points_cw = list(tr._route((0, 0), (dx, dy), 'cw')) + [(dx, dy)]
            #points_ccw = list(tr._route((0, 0), (dx, dy), 'ccw')) + [(dx, dy)]
            tr.orientation = ['cw']
            objs_cw = tr._to_graphic_objects()
            tr.orientation = ['ccw']
            objs_ccw = tr._to_graphic_objects()

            tags.append(Tag('path',
                            fill='none',
                            stroke='red', stroke_width='0.01', stroke_linecap='round',
                            transform=xf, d=' '.join(pd_obj(objs_cw))))
            tags.append(Tag('path',
                            fill='none',
                            stroke='blue', stroke_width='0.01', stroke_linecap='round',
                            transform=xf, d=' '.join(pd_obj(objs_ccw))))
            #tags.append(Tag('path',
            #                fill='none',
            #                stroke='red', stroke_width='0.01', stroke_linecap='round',
            #                transform=xf, d=pd(points_cw)))
            #tags.append(Tag('path',
            #                fill='none',
            #                stroke='blue', stroke_width='0.01', stroke_linecap='round',
            #                transform=xf, d=pd(points_ccw)))


    print(setup_svg([Tag('g', tags, transform='scale(20 20)')], [(0, 0), (20*10*1.1 + 0.1, 20*10*1.3 + 0.1)]))


def _board_demo():
    b = Board(100, 80)
    p1 = THTPad.rect(10, 10, 0.9, 1.8)
    b.add(p1)
    p2 = THTPad.rect(20, 15, 0.9, 1.8)
    b.add(p2)
    b.add(Trace(0.5, p1, p2, style='ortho', roundover=1.5))
    b.add_text(50, 50, 'Foobar')
    print(b.pretty_svg())
    b.layer_stack().save_to_directory('/tmp/testdir')


if __name__ == '__main__':
    _board_demo()
    #_route_demo()

