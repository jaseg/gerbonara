
import math
from copy import copy
from itertools import zip_longest
from dataclasses import dataclass, field, KW_ONLY

from ..utils import LengthUnit, MM, rotate_point, svg_arc
from ..layers import LayerStack
from ..graphic_objects import Line, Arc, Flash
from ..apertures import Aperture, CircleAperture, RectangleAperture, ExcellonTool


def sgn(x):
    return -1 if x < 0 else 1


class Board:
    def __init__(self):
        self.objects = set()

    def to_layer_stack(self, layer_stack):
        if layer_stack is None:
            layer_stack = LayerStack()

        for obj in self.objects:
            obj.render(stack)


@dataclass
class Positioned:
    x: float
    y: float
    _: KW_ONLY
    rotation: float = 0.0
    unit: LengthUnit = MM
    parent: object = None

    @property
    def abs_pos(self, dx, dy, da):
        x, y = rotate_point(self.x, self.y, da)

        if self.parent is None:
            px, py, pa = dx, dy, 0
        else:
            px, py, pa = self.parent.abs_pos(dx, dy, da)

        return x+px, y+py, self.rotation+da+pa


@dataclass
class Pad(Positioned):
    pass

@dataclass
class SMDPad(Pad):
    copper_aperture: Aperture
    mask_aperture: Aperture
    paste_aperture: Aperture
    silk_features: list
    side: str = 'top'

    def to_layer_stack(self, layer_stack):
        x, y, rotation = self.abs_pos
        stack[self.side, 'copper'].objects.append(Flash(x, y, self.copper_aperture.rotated(rotation), unit=self.unit))
        stack[self.side, 'mask'  ].objects.append(Flash(x, y, self.mask_aperture.rotated(rotation), unit=self.unit))
        stack[self.side, 'paste' ].objects.append(Flash(x, y, self.paste_aperture.rotated(rotation), unit=self.unit))
        stack[self.side, 'silk'  ].objects.extend([copy(feature).rotate(rotation).offset(x, y, self.unit)
                                                 for feature in self.silk_features])

    def flip(self):
        self.side = 'top' if self.side == 'bottom' else 'top'


class THTPad(Pad):
    drill_dia: float
    pad_top: SMDPad
    pad_bottom: SMDPad = None
    aperture_inner: Aperture = None
    plated: bool = True

    def __post_init__(self):
        if self.pad_bottom is None:
            self.pad_bottom = copy(self.pad_top)
            self.pad_bottom.flip()

        self.pad_top.parent = self.pad_bottom.parent = self

        if (self.pad_top.side, self.pad_bottom.side) != ('top', 'bottom'):
            raise ValueError(f'The top and bottom pads must have side set to top and bottom, respectively. Currently, the top pad side is set to {self.pad_top.side} and the bottom pad side to {self.pad_bottom.side}.')

    def to_layer_stack(self, layer_stack, x, y, rotation):
        x, y, rotation = self.abs_pos
        self.top_pad.to_layer_stack(layer_stack)
        self.bottom_pad.to_layer_stack(layer_stack)

        for (side, use), layer in layer_stack.inner_layers:
            layer.objects.append(Flash(x, y, self.aperture_inner.rotated(rotation), unit=self.unit))

        hole = Flash(self.x, self.y, ExcellonTool(self.drill_dia, plated=self.plated, unit=self.unit), unit=self.unit)
        if self.plated:
            layer_stack.drill_pth.objects.append(hole)
        else:
            layer_stack.drill_npth.objects.append(hole)


@dataclass
class Via(Positioned):
    diameter: float
    hole: float

    def to_layer_stack(self, layer_stack):
        x, y, rotation = self.abs_pos

        aperture = CircleAperture(diameter=self.diameter, unit=self.unit)
        tool = ExcellonTool(diameter=self.hole, unit=self.unit)
        
        for (side, use), layer in layer_stack.copper_layers:
            layer.objects.append(Flash(x, y, aperture, unit=self.unit))

        layer_stack.drill_pth.objects.append(Flash(x, y, tool, unit=self.unit))


@dataclass
class Trace:
    width: float
    start: object = None
    end: object = None
    side: str = 'top'
    waypoints: [(float, float)] = field(default_factory=list)
    style: str = 'direct'
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
                    yield (0, sgn(dy)*(abs(dy)-abs(dx)))
                else:
                    yield (sgn(dx)*(abs(dx)-abs(dy)), 0)
            else:
                if abs(dy) > abs(dx):
                    yield (dx, sgn(dy)*abs(dx))
                else:
                    yield (sgn(dx)*abs(dy), dy)

        else: # self.style == 'ortho'
            if p == (orientation == 'cw'):
                if abs(dy) > abs(dx):
                    yield (0, dy)
                else:
                    yield (dx, 0)
            else:
                if abs(dy) > abs(dx):
                    yield (dx, 0)
                else:
                    yield (0, dy)

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
            start = start.abs_pos
        if not isinstance(end, tuple):
            end = end.abs_pos

        aperture = CircleAperture(diameter=self.width, unit=self.unit)

        points_in = [start, *self.waypoints, end]

        points = []
        for p1, p2, orientation in zip_longest(points_in[:-1], points_in[1:], self.orientation):
            points.extend(self._route(p1, p2, orientation))
        points.append(p2)

        return self._round_over(points, aperture)

    def to_layer_stack(self, layer_stack, x, y, rotation):
        layer_stack[self.side, 'copper'].objects.extend(self._to_graphic_objects())

if __name__ == '__main__':
    from ..utils import setup_svg, Tag
    from ..newstroke import Newstroke

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

        for r in [0.0, 0.1, 0.2, 0.3]:
            tr = Trace(0.1, style='ortho', roundover=r, start=(0, 0), end=(dx, dy))
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

    print(setup_svg([Tag('g', tags, transform='scale(20 20)')], [(0, 0), (20*10*1.1 + 0.1, 20*10*1.3 + 0.1)]))


