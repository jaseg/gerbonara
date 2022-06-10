#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2022 Jan Götte <code@jaseg.de>
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

from dataclasses import dataclass, KW_ONLY, replace

from .utils import *

prec = lambda x: f'{float(x):.6}'


@dataclass
class GraphicPrimitive:
    _ : KW_ONLY
    polarity_dark : bool = True

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


@dataclass
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
        return tag('circle', cx=prec(self.x), cy=prec(self.y), r=prec(self.r), style=f'fill: {color}')


@dataclass
class ArcPoly(GraphicPrimitive):
    """ Polygon whose sides may be either straight lines or circular arcs. """

    #: list of (x : float, y : float) tuples. Describes closed outline, i.e. the first and last point are considered
    #: connected.
    outline : list
    #: Must be either None (all segments are straight lines) or same length as outline.
    #: Straight line segments have None entry.
    arc_centers : list = None

    @property
    def segments(self):
        """ Return an iterator through all *segments* of this polygon. For each outline segment (line or arc), this
        iterator will yield a ``(p1, p2, center)`` tuple. If the segment is a straight line, ``center`` will be
        ``None``.
        """
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

    def to_svg(self, fg='black', bg='white', tag=Tag):
        color = fg if self.polarity_dark else bg
        return tag('path', d=' '.join(self._path_d()), style=f'fill: {color}')


@dataclass
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
        return tag('path', d=f'M {self.x1:.6} {self.y1:.6} L {self.x2:.6} {self.y2:.6}',
                style=f'fill: none; stroke: {color}; stroke-width: {width}; stroke-linecap: round')

@dataclass
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
    #: Center X coordinate relative to ``x1``
    cx : float
    #: Center Y coordinate relative to ``y1``
    cy : float
    #: ``True`` if this arc is clockwise from start to end. Selects between the large arc and the small arc given this
    #: start, end and center
    clockwise : bool
    #: Line width of this arc.
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

    def to_svg(self, fg='black', bg='white', tag=Tag):
        color = fg if self.polarity_dark else bg
        arc = svg_arc((self.x1, self.y1), (self.x2, self.y2), (self.cx, self.cy), self.clockwise)
        width = f'{self.width:.6}' if not math.isclose(self.width, 0) else '0.01mm'
        return tag('path', d=f'M {self.x1:.6} {self.y1:.6} {arc}',
                style=f'fill: none; stroke: {color}; stroke-width: {width}; stroke-linecap: round; fill: none')

@dataclass
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
                transform=svg_rotation(self.rotation, self.x, self.y), style=f'fill: {color}')

