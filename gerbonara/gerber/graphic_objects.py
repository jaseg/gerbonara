
import math
from dataclasses import dataclass, KW_ONLY, astuple, replace

from . import graphic_primitives as gp
from .gerber_statements import *

@dataclass
class GerberObject:
    _ : KW_ONLY
    polarity_dark : bool = True
    unit : str = None

    def to_primitives(self):
        raise NotImplementedError()

@dataclass
class Flash(GerberObject):
    x : float
    y : float
    aperture : object

    def with_offset(self, dx, dy):
        return replace(self, x=self.x+dx, y=self.y+dy)

    def rotate(self, rotation, cx=0, cy=0):
        self.x, self.y = gp.rotate_point(self.x, self.y, rotation, cx, cy)

    def to_primitives(self):
        yield from self.aperture.flash(self.x, self.y)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)
        yield FlashStmt(self.x, self.y, unit=self.unit)
        gs.update_point(self.x, self.y, unit=self.unit)

class Region(GerberObject):
    def __init__(self, outline=None, arc_centers=None, *, unit, polarity_dark):
        super().__init__(unit=unit, polarity_dark=polarity_dark)
        outline = [] if outline is None else outline
        arc_centers = [] if arc_centers is None else arc_centers
        self.poly = gp.ArcPoly(outline, arc_centers)

    def __len__(self):
        return len(self.poly)

    def __bool__(self):
        return bool(self.poly)

    def with_offset(self, dx, dy):
        return Region([ (x+dx, y+dy) for x, y in self.poly.outline ],
                self.poly.arc_centers,
                polarity_dark=self.polarity_dark,
                unit=self.unit)

    def rotate(self, angle, cx=0, cy=0):
        self.poly.outline = [ gp.rotate_point(x, y, angle, cx, cy) for x, y in self.poly.outline ]
        self.poly.arc_centers = [
                gp.rotate_point(*center, angle, cx, cy) if center else None
                for center in self.poly.arc_centers ]

    def append(self, obj):
        if not self.poly.outline:
            self.poly.outline.append(obj.p1)
        self.poly.outline.append(obj.p2)

        if isinstance(obj, Arc):
            self.poly.arc_centers.append(obj.center)
        else:
            self.poly.arc_centers.append(None)

    def to_primitives(self):
        self.poly.polarity_dark = polarity_dark
        yield self.poly

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield RegionStartStmt()

        yield from gs.set_current_point(self.poly.outline[0], unit=self.unit)

        for point, arc_center in zip(self.poly.outline[1:], self.poly.arc_centers):
            if arc_center is None:
                yield from gs.set_interpolation_mode(LinearModeStmt)
                yield InterpolateStmt(*point, unit=self.unit)
                gs.update_point(*point, unit=self.unit)

            else:
                cx, cy = arc_center
                x2, y2 = point
                yield from gs.set_interpolation_mode(CircularCCWModeStmt)
                yield InterpolateStmt(x2, y2, cx-x2, cy-y2, unit=self.unit)
                gs.update_point(x2, y2, unit=self.unit)

        yield RegionEndStmt()


@dataclass
class Line(GerberObject):
    # Line with *round* end caps.
    x1 : float
    y1 : float
    x2 : float
    y2 : float
    aperture : object

    def with_offset(self, dx, dy):
        return replace(self, x1=self.x1+dx, y1=self.y1+dy, x2=self.x2+dx, y2=self.y2+dy)

    def rotate(self, rotation, cx=0, cy=0):
        self.x1, self.y1 = gp.rotate_point(self.x1, self.y1, rotation, cx, cy)
        self.x2, self.y2 = gp.rotate_point(self.x2, self.y2, rotation, cx, cy)

    @property
    def p1(self):
        return self.x1, self.y1

    @property
    def p2(self):
        return self.x2, self.y2

    def to_primitives(self):
        yield gp.Line(*self.p1, *self.p2, self.aperture.equivalent_width, polarity_dark=self.polarity_dark)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)
        yield from gs.set_interpolation_mode(LinearModeStmt)
        yield from gs.set_current_point(self.p1, unit=self.unit)
        yield InterpolateStmt(*self.p2, unit=self.unit)
        gs.update_point(*self.p2, unit=self.unit)


@dataclass
class Drill(GerberObject):
    x : float
    y : float
    diameter : float

    def with_offset(self, dx, dy):
        return replace(self, x=self.x+dx, y=self.y+dy)

    def rotate(self, angle, cx=0, cy=0):
        self.x, self.y = gp.rotate_point(self.x, self.y, angle, cx, cy)

    def to_primitives(self):
        yield gp.Circle(self.x, self.y, self.diameter/2)


@dataclass
class Slot(GerberObject):
    x1 : float
    y1 : float
    x2 : float
    y2 : float
    width : float

    def with_offset(self, dx, dy):
        return replace(self, x1=self.x1+dx, y1=self.y1+dy, x2=self.x2+dx, y2=self.y2+dy)

    def rotate(self, rotation, cx=0, cy=0):
        if cx is None:
            cx = (self.x1 + self.x2) / 2
            cy = (self.y1 + self.y2) / 2
        self.x1, self.y1 = gp.rotate_point(self.x1, self.y1, rotation, cx, cy)
        self.x2, self.y2 = gp.rotate_point(self.x2, self.y2, rotation, cx, cy)

    @property
    def p1(self):
        return self.x1, self.y1

    @property
    def p2(self):
        return self.x2, self.y2

    def to_primitives(self):
        yield gp.Line(*self.p1, *self.p2, self.width, polarity_dark=self.polarity_dark)


@dataclass
class Arc(GerberObject):
    x1 : float
    y1 : float
    x2 : float
    y2 : float
    cx : float
    cy : float
    flipped : bool
    aperture : object

    def with_offset(self, dx, dy):
        return replace(self, x1=self.x1+dx, y1=self.y1+dy, x2=self.x2+dx, y2=self.y2+dy)

    @property
    def p1(self):
        return self.x1, self.y1

    @property
    def p2(self):
        return self.x2, self.y2

    @property
    def center(self):
        return self.cx + self.x1, self.cy + self.y1

    def rotate(self, rotation, cx=0, cy=0):
        # rotate center first since we need old x1, y1 here
        new_cx, new_cy = gp.rotate_point(*self.center, rotation, cx, cy)
        self.x1, self.y1 = gp.rotate_point(self.x1, self.y1, rotation, cx, cy)
        self.x2, self.y2 = gp.rotate_point(self.x2, self.y2, rotation, cx, cy)
        self.cx, self.cy = new_cx - self.x1, new_cy - self.y1

    def to_primitives(self):
        yield gp.Arc(*astuple(self)[:7], width=self.aperture.equivalent_width, polarity_dark=self.polarity_dark)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)
        yield from gs.set_interpolation_mode(CircularCCWModeStmt)
        yield from gs.set_current_point(self.p1, unit=self.unit)
        yield InterpolateStmt(self.x2, self.y2, self.cx, self.cy, unit=self.unit)
        gs.update_point(*self.p2, unit=self.unit)


