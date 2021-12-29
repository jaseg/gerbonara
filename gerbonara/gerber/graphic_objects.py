
from dataclasses import dataclass, KW_ONLY

from . import graphic_primitives as gp
from .gerber_statements import *

@dataclass
class GerberObject:
    _ : KW_ONLY
    polarity_dark : bool = True

    def to_primitives(self):
        raise NotImplementedError()

@dataclass
class Flash(GerberObject):
    x : float
    y : float
    aperture : object

    def with_offset(self, dx, dy):
        return replace(self, x=self.x+dx, y=self.y+dy)

    def rotate(self, rotation, cx=None, cy=None):
        self.x, self.y = gp.rotate_point(self.x, self.y, rotation, cx, cy)

    def to_primitives(self):
        yield from self.aperture.flash(self.x, self.y)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)
        yield FlashStmt(self.x, self.y)

class Region(GerberObject):
    def __init__(self, outline=[], arc_centers=None, *, polarity_dark):
        super().__init__(self, polarity_dark=polarity_dark)
        self.poly = gp.ArcPoly()

    def with_offset(self, dx, dy):
        return Region([ (x+dx, y+dy) for x, y in outline ], radii, polarity_dark=self.polarity_dark)

    def rotate(self, angle, cx=0, cy=0):
        self.poly.outline = [ gp.rotate_point(x, y, angle, cx, cy) for x, y in self.poly.outline ]
        self.poly.arc_centers = [ gp.rotate_point(x, y, angle, cx, cy) for x, y in self.poly.arc_centers ]

    def append(self, obj):
        if not self.outline:
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
        yield RegionStartStmt()

        yield from gs.set_current_point(self.poly.outline[0])

        for point, arc_center in zip(self.poly.outline, self.poly.arc_centers):
            if arc_center is None:
                yield from gs.set_interpolation_mode(LinearModeStmt)
                yield InterpolateStmt(*point)

            else:
                cx, cy = arc_center
                x2, y2 = point
                yield from gs.set_interpolation_mode(CircularCCWModeStmt)
                yield InterpolateStmt(x2, y2, cx-x2, cy-y2)

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

    def rotate(self, rotation, cx=None, cy=None):
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
        yield gp.Line(*self.p1, *self.p2, self.aperture.equivalent_width, polarity_dark=self.polarity_dark)

    def to_statements(self, gs):
        yield from gs.set_aperture(self.aperture)
        yield from gs.set_interpolation_mode(LinearModeStmt)
        yield from gs.set_current_point(self.p1)
        yield InterpolateStmt(*self.p2)


@dataclass
class Drill(GerberObject):
    x : float
    y : float
    diameter : float

    def with_offset(self, dx, dy):
        return replace(self, x=self.x+dx, y=self.y+dy)

    def rotate(self, angle, cx=None, cy=None):
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

    def rotate(self, rotation, cx=None, cy=None):
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


class Arc(GerberObject):
    x : float
    y : float
    r : float
    angle1 : float # radians!
    angle2 : float # radians!
    aperture : object

    @classmethod
    def from_coords(kls, start, end, center_delta, aperture, flipped=False, polarity_dark=True):
        x0, y0 = start
        x1, y1 = end
        dx, dy = center_delta
        cx, cy = x0+dx, y0+dy
        angle1 = math.atan2(y0-cy, x0-cx)
        angle2 = math.atan2(y1-cy, x1-cx)
        aperture = self.aperture
        if flipped:
            angle1, angle2 = angle2, angle1
        r = math.sqrt(dx**2 + dy**2)
        # r should be approximately (depending on coordinate resolution) equal for center->start and center->end
        return kls(cx, cy, r, angle1, angle2, polarity_dark=polarity_dark)

    def with_offset(self, dx, dy):
        return replace(self, x=self.x+dx, y=self.y+dy)

    @property
    def p1(self):
        return self.x + self.r*sin(self.angle1), self.y + self.r*cos(self.angle1)

    @property
    def p2(self):
        return self.x + self.r*sin(self.angle2), self.y + self.r*cos(self.angle2)

    @property
    def center(self):
        return (self.x, self.y)

    def rotate(self, rotation, cx=None, cy=None):
        self.x, self.y = gp.rotate_point(self.x, self.y, rotation, cx, cy)
        self.angle1 = (self.angle1+rotation) % (2*math.pi)
        self.angle2 = (self.angle2+rotation) % (2*math.pi)

    def to_primitives(self):
        yield gp.Arc(self.x, self.y, self.r, self.angle1, self.angle2, self.aperture.equivalent_width, polarity_dark=self.polarity_dark)

    def to_statements(self, gs):
        yield from gs.set_aperture(self.aperture)
        yield from gs.set_interpolation_mode(CircularCCWModeStmt)
        yield from gs.set_current_point(self.p1)
        x2, y2 = self.p2
        yield InterpolateStmt(x2, y2, self.x-x2, self.y-y2)


