
import math
import itertools

from dataclasses import dataclass, KW_ONLY, replace


@dataclass
class GraphicPrimitive:
    _ : KW_ONLY
    polarity_dark : bool = True


def rotate_point(x, y, angle, cx=0, cy=0):
    """ rotate point (x,y) around (cx,cy) clockwise angle radians """

    return (cx + (x - cx) * math.cos(-angle) - (y - cy) * math.sin(-angle),
            cy + (x - cx) * math.sin(-angle) + (y - cy) * math.cos(-angle))

def min_none(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)

def max_none(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)

def add_bounds(b1, b2):
    (min_x_1, min_y_1), (max_x_1, max_y_1) = b1
    (min_x_2, min_y_2), (max_x_2, max_y_2) = b2
    min_x, min_y = min_none(min_x_1, min_x_2), min_none(min_y_1, min_y_2)
    max_x, max_y = max_none(max_x_1, max_x_2), max_none(max_y_1, max_y_2)
    return ((min_x, min_y), (max_x, max_y))

def rad_to_deg(x):
    return x/math.pi * 180

@dataclass
class Circle(GraphicPrimitive):
    x : float
    y : float
    r : float # Here, we use radius as common in modern computer graphics, not diameter as gerber uses.

    def bounding_box(self):
        return ((self.x-self.r, self.y-self.r), (self.x+self.r, self.y+self.r))

    def to_svg(self, tag, fg, bg):
        color = fg if self.polarity_dark else bg
        return tag('circle', cx=self.x, cy=self.y, r=self.r, style=f'fill: {color}')


@dataclass
class Obround(GraphicPrimitive):
    x : float
    y : float
    w : float
    h : float
    rotation : float # radians!

    def to_line(self):
        if self.w > self.h:
            w, a, b = self.h, self.w-self.h, 0
        else:
            w, a, b = self.w, 0, self.h-self.w
        return Line(
                *rotate_point(self.x-a/2, self.y-b/2, self.rotation, self.x, self.y),
                *rotate_point(self.x+a/2, self.y+b/2, self.rotation, self.x, self.y),
                w, polarity_dark=self.polarity_dark)

    def bounding_box(self):
        return self.to_line().bounding_box()

    def to_svg(self, tag, fg, bg):
        return self.to_line().to_svg(tag, fg, bg)


def arc_bounds(x1, y1, x2, y2, cx, cy, clockwise):
    # This is one of these problems typical for computer geometry where out of nowhere a seemingly simple task just
    # happens to be anything but in practice.
    #
    # Online there are a number of algorithms to be found solving this problem. Often, they solve the more general
    # problem for elliptic arcs. We can keep things simple here since we only have circular arcs.
    # 
    # This solution manages to handle circular arcs given in gerber format (with explicit center and endpoints, plus
    # sweep direction instead of a format with e.g. angles and radius) without any trigonometric functions (e.g. atan2).
    #
    # cx, cy are relative to p1.

    # Center arc on cx, cy
    cx += x1
    cy += y1
    x1 -= cx
    x2 -= cx
    y1 -= cy
    y2 -= cy
    clockwise = bool(clockwise) # bool'ify for XOR/XNOR below

    # Calculate radius
    r = math.sqrt(x1**2 + y1**2)

    # Calculate in which half-planes (north/south, west/east) P1 and P2 lie.
    # Note that we assume the y axis points upwards, as in Gerber and maths.
    # SVG has its y axis pointing downwards.
    p1_west = x1 < 0
    p1_north = y1 > 0
    p2_west = x2 < 0
    p2_north = y2 > 0

    # Calculate bounding box of P1 and P2
    min_x = min(x1, x2)
    min_y = min(y1, y2)
    max_x = max(x1, x2)
    max_y = max(y1, y2)

    #               North
    #                 ^
    #                 |
    #                 |(0,0)
    #      West <-----X-----> East
    #                 |
    #  +Y             |
    #   ^             v
    #   |           South
    #   |
    #   +-----> +X
    #
    # Check whether the arc sweeps over any coordinate axes. If it does, add the intersection point to the bounding box.
    # Note that, since this intersection point is at radius r, it has coordinate e.g. (0, r) for the north intersection.
    # Since we know that the points lie on either side of the coordinate axis, the '0' coordinate of the intersection
    # point will not change the bounding box in that axis--only its 'r' coordinate matters. We also know that the
    # absolute value of that coordinate will be greater than or equal to the old coordinate in that direction since the
    # intersection with the axis is the point where the full circle is tangent to the AABB. Thus, we can blindly set the
    # corresponding coordinate of the bounding box without min()/max()'ing first.

    # Handle north/south halfplanes
    if p1_west != p2_west: # arc starts in west half-plane, ends in east half-plane
        if p1_west == clockwise: # arc is clockwise west -> east or counter-clockwise east -> west
            max_y = r # add north to bounding box
        else: # arc is counter-clockwise west -> east or clockwise east -> west
            min_y = -r # south
    else: # Arc starts and ends in same halfplane west/east
        # Since both points are on the arc (at same radius) in one halfplane, we can use the y coord as a proxy for
        # angle comparisons. 
        small_arc_is_north_to_south = y1 > y2
        small_arc_is_clockwise = small_arc_is_north_to_south == p1_west
        if small_arc_is_clockwise != clockwise:
            min_y, max_y = -r, r # intersect aabb with both north and south

    # Handle west/east halfplanes
    if p1_north != p2_north:
        if p1_north == clockwise:
            max_x = r # east
        else:
            min_x = -r # west
    else:
        small_arc_is_west_to_east = x1 < x2
        small_arc_is_clockwise = small_arc_is_west_to_east == p1_north
        if small_arc_is_clockwise != clockwise:
            min_x, max_x = -r, r # intersect aabb with both north and south

    return (min_x+cx, min_y+cy), (max_x+cx, max_y+cy)


def point_line_distance(l1, l2, p):
    # https://en.wikipedia.org/wiki/Distance_from_a_point_to_a_line
    x1, y1 = l1
    x2, y2 = l2
    x0, y0 = p
    length = math.dist(l1, l2)
    if math.isclose(length, 0):
        return math.dist(l1, p)
    return ((x2-x1)*(y1-y0) - (x1-x0)*(y2-y1)) / length

def svg_arc(old, new, center, clockwise):
    r = math.hypot(*center)
    # invert sweep flag since the svg y axis is mirrored
    sweep_flag = int(not clockwise)
    # In the degenerate case where old == new, we always take the long way around. To represent this "full-circle arc"
    # in SVG, we have to split it into two.
    if math.isclose(math.dist(old, new), 0):
        intermediate = old[0] + 2*center[0], old[1] + 2*center[1]
        # Note that we have to preserve the sweep flag to avoid causing self-intersections by flipping the direction of
        # a circular cutin
        return f'A {r:.6} {r:.6} 0 1 {sweep_flag} {intermediate[0]:.6} {intermediate[1]:.6} ' +\
               f'A {r:.6} {r:.6} 0 1 {sweep_flag} {new[0]:.6} {new[1]:.6}'

    else: # normal case
        d = point_line_distance(old, new, (old[0]+center[0], old[1]+center[1]))
        large_arc = int((d < 0) == clockwise)
        return f'A {r:.6} {r:.6} 0 {large_arc} {sweep_flag} {new[0]:.6} {new[1]:.6}'

@dataclass
class ArcPoly(GraphicPrimitive):
    """ Polygon whose sides may be either straight lines or circular arcs """

    # list of (x : float, y : float) tuples. Describes closed outline, i.e. first and last point are considered
    # connected.
    outline : [(float,)]
    # must be either None (all segments are straight lines) or same length as outline.
    # Straight line segments have None entry.
    arc_centers : [(float,)] = None

    @property
    def segments(self):
        ol = self.outline
        return itertools.zip_longest(ol, ol[1:] + [ol[0]], self.arc_centers or [])

    def bounding_box(self):
        bbox = (None, None), (None, None)
        for (x1, y1), (x2, y2), arc in self.segments:
            if arc:
                clockwise, (cx, cy) = arc
                bbox = add_bounds(bbox, arc_bounds(x1, y1, x2, y2, cx, cy, clockwise))

            else:
                line_bounds = (min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))
                bbox = add_bounds(bbox, line_bounds)
        return bbox

    def __len__(self):
        return len(self.outline)

    def __bool__(self):
        return bool(len(self))

    def _path_d(self):
        if len(self.outline) == 0:
            return

        yield f'M {self.outline[0][0]:.6} {self.outline[0][1]:.6}'

        for old, new, arc in self.segments:
            if not arc:
                yield f'L {new[0]:.6} {new[1]:.6}'
            else:
                clockwise, center = arc
                yield svg_arc(old, new, center, clockwise)

    def to_svg(self, tag, fg, bg):
        color = fg if self.polarity_dark else bg
        return tag('path', d=' '.join(self._path_d()), style=f'fill: {color}')

class Polyline:
    def __init__(self, *lines):
        self.coords = []
        self.polarity_dark = None
        self.width = None

        for line in lines:
            self.append(line)

    def append(self, line):
        assert isinstance(line, Line)
        if not self.coords:
            self.coords.append((line.x1, line.y1))
            self.coords.append((line.x2, line.y2))
            self.polarity_dark = line.polarity_dark
            self.width = line.width
            return True

        else:
            x, y = self.coords[-1]
            if self.polarity_dark == line.polarity_dark and self.width == line.width \
                    and math.isclose(line.x1, x) and math.isclose(line.y1, y):
                self.coords.append((line.x2, line.y2))
                return True

            else:
                return False

    def to_svg(self, tag, fg, bg):
        color = fg if self.polarity_dark else bg
        if not self.coords:
            return None

        (x0, y0), *rest = self.coords
        d = f'M {x0:.6} {y0:.6} ' + ' '.join(f'L {x:.6} {y:.6}' for x, y in rest)
        width = f'{self.width:.6}' if not math.isclose(self.width, 0) else '0.01mm'
        return tag('path', d=d, style=f'fill: none; stroke: {color}; stroke-width: {width}; stroke-linejoin: round; stroke-linecap: round')

@dataclass
class Line(GraphicPrimitive):
    x1 : float
    y1 : float
    x2 : float
    y2 : float
    width : float

    def bounding_box(self):
        r = self.width / 2
        return add_bounds(Circle(self.x1, self.y1, r).bounding_box(), Circle(self.x2, self.y2, r).bounding_box())

    def to_svg(self, tag, fg, bg):
        color = fg if self.polarity_dark else bg
        width = f'{self.width:.6}' if not math.isclose(self.width, 0) else '0.01mm'
        return tag('path', d=f'M {self.x1:.6} {self.y1:.6} L {self.x2:.6} {self.y2:.6}',
                style=f'fill: none; stroke: {color}; stroke-width: {width}; stroke-linecap: round')

@dataclass
class Arc(GraphicPrimitive):
    x1 : float
    y1 : float
    x2 : float
    y2 : float
    # absolute coordinates
    cx : float
    cy : float
    clockwise : bool
    width : float

    def bounding_box(self):
        r = self.width/2
        endpoints = add_bounds(Circle(self.x1, self.y1, r).bounding_box(), Circle(self.x2, self.y2, r).bounding_box())

        arc_r = math.dist((self.cx, self.cy), (self.x1, self.y1))

        # extend C -> P1 line by line width / 2 along radius
        dx, dy = self.x1 - self.cx, self.y1 - self.cy
        x1 = self.x1 + dx/arc_r * r
        y1 = self.y1 + dy/arc_r * r

        # same for C -> P2
        dx, dy = self.x2 - self.cx, self.y2 - self.cy
        x2 = self.x2 + dx/arc_r * r
        y2 = self.y2 + dy/arc_r * r

        arc = arc_bounds(x1, y1, x2, y2, self.cx, self.cy, self.clockwise)
        return add_bounds(endpoints, arc) # FIXME add "include_center" switch

    def to_svg(self, tag, fg, bg):
        color = fg if self.polarity_dark else bg
        arc = svg_arc((self.x1, self.y1), (self.x2, self.y2), (self.cx, self.cy), self.clockwise)
        width = f'{self.width:.6}' if not math.isclose(self.width, 0) else '0.01mm'
        return tag('path', d=f'M {self.x1:.6} {self.y1:.6} {arc}',
                style=f'fill: none; stroke: {color}; stroke-width: {width}; stroke-linecap: round; fill: none')

def svg_rotation(angle_rad, cx=0, cy=0):
    return f'rotate({float(rad_to_deg(angle_rad)):.4} {float(cx):.6} {float(cy):.6})'

@dataclass
class Rectangle(GraphicPrimitive):
    # coordinates are center coordinates
    x : float
    y : float
    w : float
    h : float
    rotation : float # radians, around center!

    def bounding_box(self):
        return self.to_arc_poly().bounding_box()

    def to_arc_poly(self):
        sin, cos = math.sin(self.rotation), math.cos(self.rotation)
        sw, cw = sin*self.w/2, cos*self.w/2
        sh, ch = sin*self.h/2, cos*self.h/2
        x, y = self.x, self.y
        return ArcPoly([
            (x - (cw+sh), y - (ch+sw)),
            (x - (cw+sh), y + (ch+sw)),
            (x + (cw+sh), y + (ch+sw)),
            (x + (cw+sh), y - (ch+sw)),
            ])

    @property
    def center(self):
        return self.x + self.w/2, self.y + self.h/2

    def to_svg(self, tag, fg, bg):
        color = fg if self.polarity_dark else bg
        x, y = self.x - self.w/2, self.y - self.h/2
        return tag('rect', x=x, y=y, width=self.w, height=self.h,
                transform=svg_rotation(self.rotation, self.x, self.y), style=f'fill: {color}')

@dataclass
class RegularPolygon(GraphicPrimitive):
    x : float
    y : float
    r : float
    n : int
    rotation : float # radians!

    def to_arc_poly(self):
        ''' convert n-sided gerber polygon to normal ArcPoly defined by outline '''

        delta = 2*math.pi / self.n

        return ArcPoly([
                (self.x + math.cos(self.rotation + i*delta) * self.r,
                 self.y + math.sin(self.rotation + i*delta) * self.r)
                for i in range(self.n) ])

    def bounding_box(self):
        return self.to_arc_poly().bounding_box()

    def to_svg(self, tag, fg, bg):
        return self.to_arc_poly().to_svg(tag, fg, bg)

