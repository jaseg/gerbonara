
import math
from dataclasses import dataclass, KW_ONLY, astuple, replace, fields

from . import graphic_primitives as gp
from .gerber_statements import *


def convert(value, src, dst):
        if src == dst or src is None or dst is None or value is None:
            return value
        elif dst == 'mm':
            return value * 25.4
        else:
            return value / 25.4

class Length:
    def __init__(self, obj_type):
        self.type = obj_type

@dataclass
class GerberObject:
    _ : KW_ONLY
    polarity_dark : bool = True
    unit : str = None

    def converted(self, unit):
        return replace(self, 
                **{
                    f.name: convert(getattr(self, f.name), self.unit, unit)
                    for f in fields(self) if type(f.type) is Length
                    })

    def _conv(self, value, unit):
        return convert(value, src=unit, dst=self.unit)

    def with_offset(self, dx, dy, unit='mm'):
        dx, dy = self._conv(dx, unit), self._conv(dy, unit)
        return self._with_offset(dx, dy)

    def rotate(self, rotation, cx=0, cy=0, unit='mm'):
        cx, cy = self._conv(cx, unit), self._conv(cy, unit)
        self._rotate(rotation, cx, cy)

    def bounding_box(self, unit=None):
        bboxes = [ p.bounding_box() for p in self.to_primitives(unit) ]
        min_x = min(min_x for (min_x, _min_y), _ in bboxes)
        min_y = min(min_y for (_min_x, min_y), _ in bboxes)
        max_x = max(max_x for _, (max_x, _max_y) in bboxes)
        max_y = max(max_y for _, (_max_x, max_y) in bboxes)
        return ((min_x, min_y), (max_x, max_y))

    def to_primitives(self, unit=None):
        raise NotImplementedError()

@dataclass
class Flash(GerberObject):
    x : Length(float)
    y : Length(float)
    aperture : object

    def _with_offset(self, dx, dy):
        return replace(self, x=self.x+dx, y=self.y+dy)

    def _rotate(self, rotation, cx=0, cy=0):
        self.x, self.y = gp.rotate_point(self.x, self.y, rotation, cx, cy)

    def to_primitives(self, unit=None):
        conv = self.converted(unit)
        yield from self.aperture.flash(conv.x, conv.y, unit)

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

    def _with_offset(self, dx, dy):
        return Region([ (x+dx, y+dy) for x, y in self.poly.outline ],
                self.poly.arc_centers,
                polarity_dark=self.polarity_dark,
                unit=self.unit)

    def _rotate(self, angle, cx=0, cy=0):
        self.poly.outline = [ gp.rotate_point(x, y, angle, cx, cy) for x, y in self.poly.outline ]
        self.poly.arc_centers = [
                (arc[0], gp.rotate_point(*arc[1], angle, cx, cy)) if arc else None
                for arc in self.poly.arc_centers ]

    def append(self, obj):
        if obj.unit != self.unit:
            raise ValueError('Cannot append Polyline with "{obj.unit}" coords to Region with "{self.unit}" coords.')
        if not self.poly.outline:
            self.poly.outline.append(obj.p1)
        self.poly.outline.append(obj.p2)

        if isinstance(obj, Arc):
            self.poly.arc_centers.append((obj.clockwise, obj.center))
        else:
            self.poly.arc_centers.append(None)

    def to_primitives(self, unit=None):
        self.poly.polarity_dark = self.polarity_dark # FIXME: is this the right spot to do this?
        if unit == self.unit:
            yield self.poly
        else:
            conv_outline = [ (convert(x, self.unit, unit), convert(y, self.unit, unit))
                    for x, y in self.poly.outline ]
            convert_entry = lambda entry: (entry[0], (convert(entry[1][0], self.unit, unit), convert(entry[1][1], self.unit, unit)))
            conv_arc = [ None if entry is None else convert_entry(entry) for entry in self.poly.arc_centers ]

            yield gp.ArcPoly(conv_outline, conv_arc)

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
                clockwise, (cx, cy) = arc_center
                x2, y2 = point
                yield from gs.set_interpolation_mode(CircularCWModeStmt if clockwise else CircularCCWModeStmt)
                yield InterpolateStmt(x2, y2, cx-x2, cy-y2, unit=self.unit)
                gs.update_point(x2, y2, unit=self.unit)

        yield RegionEndStmt()


@dataclass
class Line(GerberObject):
    # Line with *round* end caps.
    x1 : Length(float)
    y1 : Length(float)
    x2 : Length(float)
    y2 : Length(float)
    aperture : object

    def _with_offset(self, dx, dy):
        return replace(self, x1=self.x1+dx, y1=self.y1+dy, x2=self.x2+dx, y2=self.y2+dy)

    def _rotate(self, rotation, cx=0, cy=0):
        self.x1, self.y1 = gp.rotate_point(self.x1, self.y1, rotation, cx, cy)
        self.x2, self.y2 = gp.rotate_point(self.x2, self.y2, rotation, cx, cy)

    @property
    def p1(self):
        return self.x1, self.y1

    @property
    def p2(self):
        return self.x2, self.y2

    def to_primitives(self, unit=None):
        conv = self.converted(unit)
        yield gp.Line(*conv.p1, *conv.p2, self.aperture.equivalent_width(unit), polarity_dark=self.polarity_dark)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)
        yield from gs.set_interpolation_mode(LinearModeStmt)
        yield from gs.set_current_point(self.p1, unit=self.unit)
        yield InterpolateStmt(*self.p2, unit=self.unit)
        gs.update_point(*self.p2, unit=self.unit)


@dataclass
class Drill(GerberObject):
    x : Length(float)
    y : Length(float)
    diameter : Length(float)

    def _with_offset(self, dx, dy):
        return replace(self, x=self.x+dx, y=self.y+dy)

    def _rotate(self, angle, cx=0, cy=0):
        self.x, self.y = gp.rotate_point(self.x, self.y, angle, cx, cy)

    def to_primitives(self, unit=None):
        conv = self.converted(unit)
        yield gp.Circle(conv.x, conv.y, conv.diameter/2)


@dataclass
class Slot(GerberObject):
    x1 : Length(float)
    y1 : Length(float)
    x2 : Length(float)
    y2 : Length(float)
    width : Length(float)

    def _with_offset(self, dx, dy):
        return replace(self, x1=self.x1+dx, y1=self.y1+dy, x2=self.x2+dx, y2=self.y2+dy)

    def _rotate(self, rotation, cx=0, cy=0):
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

    def to_primitives(self, unit=None):
        conv = self.converted(unit)
        yield gp.Line(*conv.p1, *conv.p2, conv.width, polarity_dark=self.polarity_dark)


@dataclass
class Arc(GerberObject):
    x1 : Length(float)
    y1 : Length(float)
    x2 : Length(float)
    y2 : Length(float)
    # relative to (x1, x2)
    cx : Length(float)
    cy : Length(float)
    clockwise : bool
    aperture : object

    def _with_offset(self, dx, dy):
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

    def _rotate(self, rotation, cx=0, cy=0):
        # rotate center first since we need old x1, y1 here
        new_cx, new_cy = gp.rotate_point(*self.center, rotation, cx, cy)
        self.x1, self.y1 = gp.rotate_point(self.x1, self.y1, rotation, cx, cy)
        self.x2, self.y2 = gp.rotate_point(self.x2, self.y2, rotation, cx, cy)
        self.cx, self.cy = new_cx - self.x1, new_cy - self.y1

    def to_primitives(self, unit=None):
        conv = self.converted(unit)
        yield gp.Arc(x1=conv.x1, y1=conv.y1,
                x2=conv.x2, y2=conv.y2,
                cx=conv.cx+conv.x1, cy=conv.cy+conv.y1,
                clockwise=self.clockwise,
                width=self.aperture.equivalent_width(unit),
                polarity_dark=self.polarity_dark)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)
        yield from gs.set_interpolation_mode(CircularCCWModeStmt)
        yield from gs.set_current_point(self.p1, unit=self.unit)
        yield InterpolateStmt(self.x2, self.y2, self.cx, self.cy, unit=self.unit)
        gs.update_point(*self.p2, unit=self.unit)


