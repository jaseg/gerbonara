
import math
import itertools

from dataclasses import dataclass, KW_ONLY, replace

from .gerber_statements import *


class GraphicPrimitive:
    _ : KW_ONLY
    polarity_dark : bool = True


def rotate_point(x, y, angle, cx=0, cy=0):
    """ rotate point (x,y) around (cx,cy) clockwise angle radians """

    return (cx + (x - cx) * math.cos(-angle) - (y - cy) * math.sin(-angle),
            cy + (x - cx) * math.sin(-angle) + (y - cy) * math.cos(-angle))


@dataclass
class Circle(GraphicPrimitive):
    x : float
    y : float
    r : float # Here, we use radius as common in modern computer graphics, not diameter as gerber uses.

    def bounds(self):
        return ((self.x-self.r, self.y-self.r), (self.x+self.r, self.y+self.r))


@dataclass
class Obround(GraphicPrimitive):
    x : float
    y : float
    w : float
    h : float
    rotation : float # radians!

    def decompose(self):
        ''' decompose obround to two circles and one rectangle '''

        cx = self.x + self.w/2
        cy = self.y + self.h/2

        if self.w > self.h:
            x = self.x + self.h/2
            yield Circle(x, cy, self.h/2)
            yield Circle(x + self.w, cy, self.h/2)
            yield Rectangle(x, self.y, self.w - self.h, self.h)

        elif self.h > self.w:
            y = self.y + self.w/2
            yield Circle(cx, y, self.w/2)
            yield Circle(cx, y + self.h, self.w/2)
            yield Rectangle(self.x, y, self.w, self.h - self.w)

        else:
            yield Circle(cx, cy, self.w/2)

    def bounds(self):
        return ((self.x-self.w/2, self.y-self.h/2), (self.x+self.w/2, self.y+self.h/2))


@dataclass
class ArcPoly(GraphicPrimitive):
    """ Polygon whose sides may be either straight lines or circular arcs """

    # list of (x : float, y : float) tuples. Describes closed outline, i.e. first and last point are considered
    # connected.
    outline : [(float,)]
    # list of radii of segments, must be either None (all segments are straight lines) or same length as outline.
    # Straight line segments have None entry.
    arc_centers : [(float,)]

    @property
    def segments(self):
        return itertools.zip_longest(self.outline[:-1], self.outline[1:], self.radii or [])

    def bounds(self):
        for (x1, y1), (x2, y2), radius in self.segments:
            return 

    def __len__(self):
        return len(self.outline)

    def __bool__(self):
        return bool(len(self))


@dataclass
class Line(GraphicPrimitive):
    x1 : float
    y1 : float
    x2 : float
    y2 : float
    width : float

    # FIXME bounds

@dataclass
class Arc(GraphicPrimitive):
    x1 : float
    y1 : float
    x2 : float
    y2 : float
    cx : float
    cy : float
    flipped : bool
    width : float

    # FIXME bounds

@dataclass
class Rectangle(GraphicPrimitive):
    # coordinates are center coordinates
    x : float
    y : float
    w : float
    h : float
    rotation : float # radians, around center!

    def bounds(self):
        return ((self.x, self.y), (self.x+self.w, self.y+self.h))

    @property
    def center(self):
        return self.x + self.w/2, self.y + self.h/2


class RegularPolygon(GraphicPrimitive):
    x : float
    y : float
    r : float
    n : int
    rotation : float # radians!

    def decompose(self):
        ''' convert n-sided gerber polygon to normal Region defined by outline '''

        delta = 2*math.pi / self.n

        yield Region([
                (self.x + math.cos(self.rotation + i*delta) * self.r,
                 self.y + math.sin(self.rotation + i*delta) * self.r)
                for i in range(self.n) ])

