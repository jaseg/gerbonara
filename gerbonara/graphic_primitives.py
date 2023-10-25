#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
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

import math
import itertools

from dataclasses import dataclass, replace, field

from .utils import *

prec = lambda x: f'{float(x):.6}'


@dataclass(frozen=True)
class GraphicPrimitive:

    # hackety hack: Work around python < 3.10 not having dataclasses.KW_ONLY.
    # 
    # For details, refer to graphic_objects.py
    def __init_subclass__(cls):
        cls.polarity_dark = True

        d = {'polarity_dark': bool}
        if hasattr(cls, '__annotations__'):
            cls.__annotations__.update(d)
        else:
            cls.__annotations__ = d

    def bounding_box(self):
        """ Return the axis-aligned bounding box of this feature.

        :returns: ``((min_x, min_Y), (max_x, max_y))``
        :rtype: tuple
        """

        raise NotImplementedError()

    def to_svg(self, fg='black', bg='white', tag=Tag):
        """ Render this primitive into its SVG representation.

        :param str fg: Foreground color. Must be an SVG color name.
        :param str bg: Background color. Must be an SVG color name.
        :param function tag: Tag constructor to use.

        :rtype: str
        """

        raise NotImplementedError()


@dataclass(frozen=True)
class Circle(GraphicPrimitive):
    #: Center X coordinate
    x : float
    #: Center y coordinate
    y : float
    #: Radius, not diameter like in :py:class:`.apertures.CircleAperture`
    r : float # Here, we use radius as common in modern computer graphics, not diameter as gerber uses.

    def bounding_box(self):
        return ((self.x-self.r, self.y-self.r), (self.x+self.r, self.y+self.r))

    def to_svg(self, fg='black', bg='white', tag=Tag):
        color = fg if self.polarity_dark else bg
        return tag('circle', cx=prec(self.x), cy=prec(self.y), r=prec(self.r), fill=color)

    def to_arc_poly(self):
        return ArcPoly([(self.x-self.r, self.y), (self.x+self.r, self.y)],
                       [(True, (self.x, self.y)), (True, (self.x, self.y))])


@dataclass(frozen=True)
class ArcPoly(GraphicPrimitive):
    """ Polygon whose sides may be either straight lines or circular arcs. """

    #: list of (x : float, y : float) tuples. Describes closed outline, i.e. the first and last point are considered
    #: connected.
    outline : list
    #: Must be either None (all segments are straight lines) or same length as outline.
    #: Straight line segments have None entry. Arc segments have (clockwise, (cx, cy)) tuple with cx, cy being absolute
    #: coords.
    arc_centers : list = field(default_factory=list)

    @property
    def segments(self):
        """ Return an iterator through all *segments* of this polygon. For each outline segment (line or arc), this
        iterator will yield a ``(p1, p2, (clockwise, center))`` tuple. If the segment is a straight line, ``clockwise``
        will be ``None``.
        """
        for points, arc in itertools.zip_longest(itertools.pairwise(self.outline), self.arc_centers):
            if arc:
                if points:
                    yield *points, arc
                else:
                    yield self.outline[-1], self.outline[0], arc
                    return
            else:
                if not points:
                    break
                yield *points, (None, (None, None))

        # Close outline if necessary.
        if math.dist(self.outline[0], self.outline[-1]) > 1e-6:
            yield self.outline[-1], self.outline[0], (None, (None, None))

    def approximate_arcs(self, max_error=1e-2, clip_max_error=True):
        outline = []
        for p1, p2, (clockwise, center) in self.segments():
            if clockwise is None:
                outline.append(p1)
            else:
                outline.extend(approximate_arc(cx, cy, x1, y1, x2, y2, clockwise,
                                               max_error=max_error, clip_max_error=clip_max_error))
                outline.pop() # remove arc end point
        return type(self)(outline)

    def bounding_box(self):
        bbox = (None, None), (None, None)
        for (x1, y1), (x2, y2), (clockwise, (cx, cy)) in self.segments:
            if clockwise is None:
                line_bounds = (min(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))
                bbox = add_bounds(bbox, line_bounds)
            else:
                bbox = add_bounds(bbox, arc_bounds(x1, y1, x2, y2, cx, cy, clockwise))
        return bbox

    @classmethod
    def from_regular_polygon(kls, x:float, y:float, r:float, n:int, rotation:float=0, polarity_dark:bool=True):
        """ Convert an n-sided gerber polygon to a normal ArcPoly defined by outline """

        delta = 2*math.pi / n

        return kls([
                (x + math.cos(rotation + i*delta) * r,
                 y + math.sin(rotation + i*delta) * r)
                for i in range(n) ], polarity_dark=polarity_dark)

    def __len__(self):
        """ Return the number of points on this polygon's outline (which is also the number of segments because the
        polygon is closed). """
        return len(self.outline)

    def __bool__(self):
        """ Return ``True`` if this polygon has any outline points. """
        return bool(len(self))

    def path_d(self):
        if len(self.outline) == 0:
            return

        yield f'M {float(self.outline[0][0]):.6} {float(self.outline[0][1]):.6}'

        for old, new, (clockwise, center) in self.segments:
            if clockwise is None:
                yield f'L {float(new[0]):.6} {float(new[1]):.6}'
            else:
                yield svg_arc(old, new, center, clockwise)

    def to_svg(self, fg='black', bg='white', tag=Tag):
        color = fg if self.polarity_dark else bg
        return tag('path', d=' '.join(self.path_d()), fill=color)

    def to_arc_poly(self):
        return self


@dataclass(frozen=True)
class Line(GraphicPrimitive):
    """ Straight line with round end caps. """
    #: Start X coordinate. As usual in modern graphics APIs, this is at the center of the half-circle capping off this
    #: line.
    x1 : float
    #: Start Y coordinate
    y1 : float
    #: End X coordinate
    x2 : float
    #: End Y coordinate
    y2 : float
    #: Line width
    width : float

    def flip(self):
        return replace(self, x1=self.x2, y1=self.y2, x2=self.x1, y2=self.y1)

    @classmethod
    def from_obround(kls, x:float, y:float, w:float, h:float, rotation:float=0, polarity_dark:bool=True):
        """ Convert a gerber obround into a :py:class:`~.graphic_primitives.Line`. """
        if w > h:
            w, a, b = h, w-h, 0
        else:
            w, a, b = w, 0, h-w

        return kls(
                *rotate_point(x-a/2, y-b/2, rotation, x, y),
                *rotate_point(x+a/2, y+b/2, rotation, x, y),
                w, polarity_dark=polarity_dark)

    def bounding_box(self):
        r = self.width / 2
        return add_bounds(Circle(self.x1, self.y1, r).bounding_box(), Circle(self.x2, self.y2, r).bounding_box())

    def to_svg(self, fg='black', bg='white', tag=Tag):
        color = fg if self.polarity_dark else bg
        width = f'{self.width:.6}' if not math.isclose(self.width, 0) else '0.01mm'
        return tag('path', d=f'M {float(self.x1):.6} {float(self.y1):.6} L {float(self.x2):.6} {float(self.y2):.6}',
                fill='none', stroke=color, stroke_width=str(width))

    def to_arc_poly(self):
        l = math.dist((self.x1, self.y1), (self.x2, self.y2))
        dx, dy = self.x2-self.x1, self.y2-self.y1
        nx, ny = -dy/l, dx/l
        rx, ry = nx*self.width/2, ny*self.width/2
        return ArcPoly([
                    (self.x1+rx, self.y1+ry),
                    (self.x1-rx, self.y1-ry),
                    (self.x2-rx, self.y2-ry),
                    (self.x2+rx, self.y2+ry),
                ], [
                    (True, (self.x1, self.y1)),
                    None,
                    (True, (self.x2, self.y2)),
                    None,
                ])


@dataclass(frozen=True)
class Arc(GraphicPrimitive):
    """ Circular arc with line width ``width`` going from ``(x1, y1)`` to ``(x2, y2)`` around center at ``(cx, cy)``. """
    #: Start X coodinate
    x1 : float
    #: Start Y coodinate
    y1 : float
    #: End X coodinate
    x2 : float
    #: End Y coodinate
    y2 : float
    #: Center X coordinate (absolute)
    cx : float
    #: Center Y coordinate (absolute)
    cy : float
    #: ``True`` if this arc is clockwise from start to end. Selects between the large arc and the small arc given this
    #: start, end and center
    clockwise : bool
    #: Line width of this arc.
    width : float

    @property
    def is_circle(self):
        return math.isclose(self.x1, self.x2, abs_tol=1e-6) and math.isclose(self.y1, self.y2, abs_tol=1e-6)

    def flip(self):
        return replace(self, x1=self.x2, y1=self.y2, x2=self.x1, y2=self.y1, clockwise=not self.clockwise)

    def bounding_box(self):
        r = self.width/2
        (min_x, min_y), (max_x, max_y) = arc_bounds(self.x1, self.y1, self.x2, self.y2, self.cx, self.cy, self.clockwise)
        return (min_x-r, min_y-r), (max_x+r, max_y+r)

    def to_svg(self, fg='black', bg='white', tag=Tag):
        color = fg if self.polarity_dark else bg
        arc = svg_arc((self.x1, self.y1), (self.x2, self.y2), (self.cx, self.cy), self.clockwise)
        width = f'{self.width:.6}' if not math.isclose(self.width, 0) else '0.01mm'
        return tag('path', d=f'M {float(self.x1):.6} {float(self.y1):.6} {arc}',
                fill='none', stroke=color, stroke_width=width)

    def to_arc_poly(self):
        r = math.dist((self.x1, self.y1), (self.cx, self.cy))
        dx1, dy1 = self.x1-self.cx, self.y1-self.cy
        nx1, ny1 = dx1/r * self.width/2, dy1/r * self.width/2
        dx2, dy2 = self.x2-self.cx, self.y2-self.cy
        nx2, ny2 = dx2/r * self.width/2, dy2/r * self.width/2
        return ArcPoly([
                    (self.x1+nx1, self.y1+nx1),
                    (self.x1-nx1, self.y1-nx1),
                    (self.x2-nx2, self.y2-nx2),
                    (self.x2+nx2, self.y2+nx2),
                ], [
                    (self.clockwise, (self.x1, self.y1)),
                    (self.clockwise, (self.cx, self.cy)),
                    (self.clockwise, (self.x2, self.y2)),
                    (self.clockwise, (self.cx, self.cy)),
                ])


@dataclass(frozen=True)
class Rectangle(GraphicPrimitive):
    #: **Center** X coordinate
    x : float
    #: **Center** Y coordinate
    y : float
    #: width
    w : float
    #: height
    h : float
    #: rotation around center in radians
    rotation : float

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

    def to_svg(self, fg='black', bg='white', tag=Tag):
        color = fg if self.polarity_dark else bg
        x, y = self.x - self.w/2, self.y - self.h/2
        return tag('rect', x=prec(x), y=prec(y), width=prec(self.w), height=prec(self.h),
                **svg_rotation(self.rotation, self.x, self.y), fill=color)

