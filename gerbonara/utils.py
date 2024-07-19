#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
# Copyright 2022 Jan Sebastian Götte <gerbonara@jaseg.de>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""
gerber.utils
============
**Gerber and Excellon file handling utilities**

This module provides utility functions for working with Gerber and Excellon files.
"""

from dataclasses import dataclass
import os
import re
import textwrap
from functools import reduce
from enum import Enum
import math

class UnknownStatementWarning(Warning):
    """ Gerbonara found an unknown Gerber or Excellon statement. """
    pass

class RegexMatcher:
    """ Internal parsing helper """
    def __init__(self):
        self.mapping = {}

    def match(self, regex):
        def wrapper(fun):
            nonlocal self
            self.mapping[regex] = fun
            return fun
        return wrapper

    def handle(self, inst, line):
        for regex, handler in self.mapping.items():
            if (match := re.fullmatch(regex, line)):
                handler(inst, match)
                return True
        else:
            return False


@dataclass(frozen=True, slots=True)
class LengthUnit:
    """ Convenience length unit class. Used in :py:class:`.GraphicObject` and :py:class:`.Aperture` to store lenght
    information. Provides a number of useful unit conversion functions.

    Singleton, use only global instances ``utils.MM`` and ``utils.Inch``.
    """

    name: str
    shorthand: str
    this_in_mm: float

    def convert_from(self, unit, value):
        """ Convert ``value`` from ``unit`` into this unit.

        :param unit: ``MM``, ``Inch`` or one of the strings ``"mm"`` or ``"inch"``
        :param float value: 
        :rtype: float
        """

        if isinstance(unit, str):
            unit = units[unit]

        if unit == self or unit is None or value is None:
            return value

        return value * unit.this_in_mm / self.this_in_mm

    def convert_to(self, unit, value):
        """ :py:meth:`.LengthUnit.convert_from` but in reverse. """

        if isinstance(unit, str):
            unit = to_unit(unit)

        if unit is None:
            return value

        return unit.convert_from(self, value)

    def convert_bounds_from(self, unit, value):
        """ :py:meth:`.LengthUnit.convert_from` but for ((min_x, min_y), (max_x, max_y)) bounding box tuples. """

        if value is None:
            return None

        (min_x, min_y), (max_x, max_y) = value
        min_x = self.convert_from(unit, min_x)
        min_y = self.convert_from(unit, min_y)
        max_x = self.convert_from(unit, max_x)
        max_y = self.convert_from(unit, max_y)
        return (min_x, min_y), (max_x, max_y)

    def convert_bounds_to(self, unit, value):
        """ :py:meth:`.LengthUnit.convert_to` but for ((min_x, min_y), (max_x, max_y)) bounding box tuples. """

        if value is None:
            return None

        (min_x, min_y), (max_x, max_y) = value
        min_x = self.convert_to(unit, min_x)
        min_y = self.convert_to(unit, min_y)
        max_x = self.convert_to(unit, max_x)
        max_y = self.convert_to(unit, max_y)
        return (min_x, min_y), (max_x, max_y)

    def format(self, value):
        """ Return a human-readdable string representing value in this unit.

        :param float value:
        :returns: something like "3mm"
        :rtype: str
        """

        return f'{value:.3f}{self.shorthand}' if value is not None else ''

    def __call__(self, value, unit):
        """ Convenience alias for :py:meth:`.LengthUnit.convert_from` """
        return self.convert_from(unit, value)

    def __eq__(self, other):
        if isinstance(other, str):
            return other.lower() in (self.name, self.shorthand)
        else:
            return id(self) == id(other)

    # This class is a singleton, we don't want copies around
    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __str__(self):
        return self.shorthand

    def __repr__(self):
        return f'<LengthUnit {self.name}>'


MILLIMETERS_PER_INCH = 25.4
Inch = LengthUnit('inch', 'in', MILLIMETERS_PER_INCH)
MM = LengthUnit('millimeter', 'mm', 1)
units = {'inch': Inch, 'mm': MM, None: None}

def _raise_error(*args, **kwargs):
    raise SystemError('LengthUnit is a singleton. Use gerbonara.utils.MM or gerbonara.utils.Inch. Please do not invent '
                      'your own length units, the imperial system is already messed up enough.')
LengthUnit.__init__ = _raise_error

def to_unit(name):
    """ Convert string ``name`` into a registered length unit. Returns ``None`` if the argument cannot be converted.

    :param str name: ``'mm'`` or ``'inch'``
    :returns: ``MM``, ``Inch`` or ``None``
    :rtype: :py:class:`.LengthUnit` or ``None``
    """

    if name is None:
        return None

    if isinstance(name, LengthUnit):
        return name

    if isinstance(name, str):
        name = name.lower()
        if name in units:
            return units[name]

    raise ValueError(f'Invalid unit {name!r}. Should be either "mm", "inch" or None for no unit.')


class InterpMode(Enum):
    """ Gerber / Excellon interpolation mode. """
    #: straight line 
    LINEAR = 0
    #: clockwise circular arc
    CIRCULAR_CW = 1
    #: counterclockwise circular arc
    CIRCULAR_CCW = 2


def decimal_string(value, precision=6, padding=False):
    """ Convert float to string with limited precision

    Parameters
    ----------
    value : float
        A floating point value.

    precision :
        Maximum number of decimal places to print

    Returns
    -------
    value : string
        The specified value as a  string.

    """
    floatstr = '%0.10g' % value
    integer = None
    decimal = None
    if '.' in floatstr:
        integer, decimal = floatstr.split('.')
    elif ',' in floatstr:
        integer, decimal = floatstr.split(',')
    else:
        integer, decimal = floatstr, "0"

    if len(decimal) > precision:
        decimal = decimal[:precision]
    elif padding:
        decimal = decimal + (precision - len(decimal)) * '0'

    if integer or decimal:
        return ''.join([integer, '.', decimal])
    else:
        return int(floatstr)


def rotate_point(x, y, angle, cx=0, cy=0):
    """ Rotate point (x,y) around (cx,cy) by ``angle`` radians clockwise. """

    return (cx + (x - cx) * math.cos(-angle) - (y - cy) * math.sin(-angle),
            cy + (x - cx) * math.sin(-angle) + (y - cy) * math.cos(-angle))


def sweep_angle(cx, cy, x1, y1, x2, y2, clockwise):
    """ Calculate absolute sweep angle of arc. This is always a positive number.

    :returns: Angle in clockwise radian between ``0`` and ``2*math.pi``
    :rtype: float
    """
    x1, y1 = x1-cx, y1-cy
    x2, y2 = x2-cx, y2-cy

    a1, a2 = math.atan2(y1, x1), math.atan2(y2, x2)
    f = abs(a2 - a1)
    if not clockwise:
        if a2 > a1:
            return a2 - a1
        else:
            return 2*math.pi - abs(a2 - a1)
    else:
        if a1 > a2:
            return a1 - a2
        else:
            return 2*math.pi - abs(a1 - a2)


def approximate_arc(cx, cy, x1, y1, x2, y2, clockwise, max_error=1e-2, clip_max_error=True):
    # TODO the max_angle calculation below is a bit off -- we over-estimate the error, and thus produce finer
    # results than necessary. Fix this.
        
    r = math.dist((x1, y1), (cx, cy))

    if clip_max_error:
        # 1 - math.sqrt(1 - 0.5*math.sqrt(2))
        max_error = min(max_error, r*0.4588038998538031)

    elif max_error >= r:
        yield (x1, y1)
        yield (x2, y2)
        return

    # see https://www.mathopenref.com/sagitta.html
    l = math.sqrt(r**2 - (r - max_error)**2)

    angle_max = math.asin(l/r)
    alpha = sweep_angle(cx, cy, x1, y1, x2, y2, clockwise)
    num_segments = math.ceil(alpha / angle_max)
    angle = alpha / num_segments

    if not clockwise:
        angle = -angle

    for i in range(num_segments + 1):
        yield rotate_point(x1, y1, i*angle, cx, cy)


def min_none(a, b):
    """ Like the ``min(..)`` builtin, but if either value is ``None``, returns the other. """
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def max_none(a, b):
    """ Like the ``max(..)`` builtin, but if either value is ``None``, returns the other. """
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def add_bounds(b1, b2):
    """ Add/union multiple bounding boxes.

    :param tuple b1: ``((min_x, min_y), (max_x, max_y))``
    :param tuple b2: ``((min_x, min_y), (max_x, max_y))``

    :returns: ``((min_x, min_y), (max_x, max_y))``
    :rtype: tuple
    """

    return sum_bounds((b1, b2))


def offset_bounds(bounds, dx=0, dy=0):
    (min_x, min_y), (max_x, max_y) = bounds
    return (min_x+dx, min_y+dy), (max_x+dx, max_y+dy)


def sum_bounds(bounds, *, default=None):
    """ Add/union multiple bounding boxes.

    :param bounds: each arg is one bounding box in ``((min_x, min_y), (max_x, max_y))`` format

    :returns: ``((min_x, min_y), (max_x, max_y))``
    :rtype: tuple
    """

    bounds = iter([ b for b in bounds if b is not None ])

    for (min_x, min_y), (max_x, max_y) in bounds:
        break
    else:
        return default

    for (min_x_2, min_y_2), (max_x_2, max_y_2) in bounds:
        min_x, min_y = min_none(min_x, min_x_2), min_none(min_y, min_y_2)
        max_x, max_y = max_none(max_x, max_x_2), max_none(max_y, max_y_2)

    return ((min_x, min_y), (max_x, max_y))


class Tag:
    """ Helper class to ease creation of SVG. All API functions that create SVG allow you to substitute this with your
    own implementation by passing a ``tag`` parameter. """

    def __init__(self, name, children=None, root=False, **attrs):
        if (fill := attrs.get('fill')) and isinstance(fill, tuple):
            attrs['fill'], attrs['fill-opacity'] = fill
        if (stroke := attrs.get('stroke')) and isinstance(stroke, tuple):
            attrs['stroke'], attrs['stroke-opacity'] = stroke
        self.name, self.attrs = name, attrs
        self.children = children or []
        self.root = root

    def __str__(self):
        prefix = '<?xml version="1.0" encoding="utf-8"?>\n' if self.root else ''
        opening = ' '.join([self.name] + [f'{key.replace("__", ":").replace("_", "-")}="{value}"' for key, value in self.attrs.items()])
        if self.children:
            children = '\n'.join(textwrap.indent(str(c), '  ') for c in self.children)
            return f'{prefix}<{opening}>\n{children}\n</{self.name}>'
        else:
            return f'{prefix}<{opening}/>'


def arc_bounds(x1, y1, x2, y2, cx, cy, clockwise):
    """ Calculate bounding box of a circular arc given in Gerber notation (i.e. with center relative to first point).

    :returns: ``((x_min, y_min), (x_max, y_max))``
    """
    # This is one of these problems typical for computer geometry where out of nowhere a seemingly simple task just
    # happens to be anything but in practice.
    #
    # Online there are a number of algorithms to be found solving this problem. Often, they solve the more general
    # problem for elliptic arcs. We can keep things simple here since we only have circular arcs.
    # 
    # This solution manages to handle circular arcs given in gerber format (with explicit center and endpoints, plus
    # sweep direction instead of a format with e.g. angles and radius) without any trigonometric functions (e.g. atan2).
    #
    # cx, cy are in absolute coordinates.

    # Center arc on cx, cy
    x1 -= cx
    x2 -= cx
    y1 -= cy
    y2 -= cy
    clockwise = bool(clockwise) # bool'ify for XOR/XNOR below

    # Calculate radius
    r = math.sqrt(x1**2 + y1**2)

    # Special case: Gerber defines an arc with p1 == p2 as a full circle.
    if math.isclose(x1, x2) and math.isclose(y1, y2):
        return (cx-r, cy-r), (cx+r, cy+r)

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
        small_arc_is_clockwise = small_arc_is_north_to_south != p1_west
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


def convex_hull(points):
    '''
    Returns points on convex hull in CCW order according to Graham's scan algorithm. 
    By Tom Switzer <thomas.switzer@gmail.com>.
    '''
    # https://gist.github.com/arthur-e/5cf52962341310f438e96c1f3c3398b8
    TURN_LEFT, TURN_RIGHT, TURN_NONE = (1, -1, 0)

    def cmp(a, b):
        return (a > b) - (a < b)

    def turn(p, q, r):
        return cmp((q[0] - p[0])*(r[1] - p[1]) - (r[0] - p[0])*(q[1] - p[1]), 0)

    def keep_left(hull, r):
        while len(hull) > 1 and turn(hull[-2], hull[-1], r) != TURN_LEFT:
            hull.pop()
        if not len(hull) or hull[-1] != r:
            hull.append(r)
        return hull

    points = sorted(points)
    l = reduce(keep_left, points, [])
    u = reduce(keep_left, reversed(points), [])
    return l.extend(u[i] for i in range(1, len(u) - 1)) or l


def point_line_distance(l1, l2, p):
    """ Calculate distance between infinite line through l1 and l2, and point p. """
    # https://en.wikipedia.org/wiki/Distance_from_a_point_to_a_line
    x1, y1 = l1
    x2, y2 = l2
    x0, y0 = p
    length = math.dist(l1, l2)
    if math.isclose(length, 0):
        return math.dist(l1, p)
    return ((x2-x1)*(y1-y0) - (x1-x0)*(y2-y1)) / length


def svg_arc(old, new, center, clockwise):
    """ Format an SVG circular arc "A" path data entry given an arc in Gerber notation (but with center in absolute
    coordinates).

    :rtype: str
    """
    r = float(math.dist(old, center))
    # invert sweep flag since the svg y axis is mirrored
    sweep_flag = int(not clockwise)
    # In the degenerate case where old == new, we always take the long way around. To represent this "full-circle arc"
    # in SVG, we have to split it into two.
    if math.isclose(math.dist(old, new), 0):
        intermediate = old[0] + 2*(center[0]-old[0]), old[1] + 2*(center[1]-old[1])
        # Note that we have to preserve the sweep flag to avoid causing self-intersections by flipping the direction of
        # a circular cutin
        return f'A {r:.6} {r:.6} 0 1 {sweep_flag} {float(intermediate[0]):.6} {float(intermediate[1]):.6} ' +\
               f'A {r:.6} {r:.6} 0 1 {sweep_flag} {float(new[0]):.6} {float(new[1]):.6}'

    else: # normal case
        d = point_line_distance(old, new, (center[0], center[1]))
        large_arc = int((d < 0) == clockwise)
        return f'A {r:.6} {r:.6} 0 {large_arc} {sweep_flag} {float(new[0]):.6} {float(new[1]):.6}'


def svg_rotation(angle_rad, cx=0, cy=0):
    if math.isclose(angle_rad, 0.0, abs_tol=1e-3):
        return {}
    else:
        return {'transform': f'rotate({float(math.degrees(angle_rad)):.4} {float(cx):.6} {float(cy):.6})'}

def setup_svg(tags, bounds, margin=0, arg_unit=MM, svg_unit=MM, pagecolor='white', tag=Tag, inkscape=False):
    (min_x, min_y), (max_x, max_y) = bounds

    if margin:
        margin = svg_unit(margin, arg_unit)
        min_x -= margin
        min_y -= margin
        max_x += margin
        max_y += margin

    w, h = max_x - min_x, max_y - min_y
    w = 1.0 if math.isclose(w, 0.0) else w
    h = 1.0 if math.isclose(h, 0.0) else h

    if inkscape:
        tags.insert(0, tag('sodipodi:namedview', [], id='namedview1', pagecolor=pagecolor,
                inkscape__document_units=svg_unit.shorthand))
        namespaces = dict(
            xmlns="http://www.w3.org/2000/svg",
            xmlns__xlink="http://www.w3.org/1999/xlink",
            xmlns__sodipodi='http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd',
            xmlns__inkscape='http://www.inkscape.org/namespaces/inkscape')

    else:
        namespaces = dict(
            xmlns="http://www.w3.org/2000/svg",
            xmlns__xlink="http://www.w3.org/1999/xlink")

    svg_unit = 'in' if svg_unit == 'inch' else 'mm'
    # TODO export apertures as <uses> where reasonable.
    return tag('svg', tags,
            width=f'{w}{svg_unit}', height=f'{h}{svg_unit}',
            viewBox=f'{min_x} {min_y} {w} {h}',
            style=f'background-color:{pagecolor}',
            **namespaces,
            root=True)


def point_in_polygon(point, poly):
    # https://stackoverflow.com/questions/217578/how-can-i-determine-whether-a-2d-point-is-within-a-polygon
    # https://wrfranklin.org/Research/Short_Notes/pnpoly.html

    if not poly:
        return False

    res = False
    tx, ty = point
    xp, yp = poly[-1]
    for x, y in poly:
        if yp == ty == y and ((x > tx) != (xp > tx)): # test point on horizontal segment
            return True
        if xp == tx == x and ((y > ty) != (yp > ty)): # test point on vertical segment
            return True
        if ((y > ty) != (yp > ty)):
            tmp = ((xp-x) * (ty-y) / (yp-y) + x)
            if tx == tmp: # test point on diagonal segment
                return True
            elif tx < tmp:
                res = not res
        xp, yp = x, y

    return res


def bbox_intersect(a, b):
    if a is None or b is None:
        return False

    (xa_min, ya_min), (xa_max, ya_max) = a
    (xb_min, yb_min), (xb_max, yb_max) = b

    x_overlap = not (xa_max < xb_min or xb_max < xa_min)
    y_overlap = not (ya_max < yb_min or yb_max < ya_min)

    return x_overlap and y_overlap


def bbox_contains(outer, inner):
    if outer is None or inner is None:
        return False

    (xa_min, ya_min), (xa_max, ya_max) = outer
    (xb_min, yb_min), (xb_max, yb_max) = inner

    contained_x = xa_min < xb_min and xb_max < xa_max
    contained_y = ya_min < yb_min and yb_max < ya_max

    return contained_x and contained_y

