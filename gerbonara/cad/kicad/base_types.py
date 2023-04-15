from .sexp import *
from .sexp_mapper import *
import time

from dataclasses import field
import math
import uuid
from contextlib import contextmanager
from itertools import cycle


@sexp_type('color')
class Color:
    r: int = None
    g: int = None
    b: int = None
    a: int = None


@sexp_type('stroke')
class Stroke:
    width: Named(float) = 0.254
    type: Named(AtomChoice(Atom.dash, Atom.dot, Atom.dash_dot_dot, Atom.dash_dot, Atom.default, Atom.solid)) = Atom.default
    color: Color = None
    

class Dasher:
    def __init__(self, stroke):
        self.width = stroke.width
        gap = 4*stroke.width
        dot = 0
        gap = 11*stroke.width
        self.pattern = {
                Atom.dash: [dash, gap],
                Atom.dot: [dot, gap],
                Atom.dash_dot_dot: [dash, gap, dot, gap, dot, gap],
                Atom.dash_dot: [dash, gap, dot, gap],
                Atom.default: [1e99],
                Atom.solid: [1e99]}[stroke.type]
        self.start_x, self.start_y = None, None
        self.cur_x, self.cur_y = None, None
        self.segments = []

    def move(self, x, y):
        self.start_x, self.start_y = x, y

    def line(x, y):
        if x is None or y is None:
            raise ValueError('line() called before move()')
        self.segments.append((self.cur_x, self.cur_y, x, y))
        cur_x, cur_y = x, y

    def close():
        self.segments.append((self.cur_x, self.cur_y, start_x, start_y))

    def __iter__(self):
        offset = 0
        for length, stroked in cycle(zip(self.pattern, cycle([True, False]))):
            for x1, y1, x2, y2 in segments:
                segment_length = math.dist((x1, y1), (x2, y2))



@sexp_type('xy')
class XYCoord:
    x: float = 0
    y: float = 0

    def isclose(self, other, tol=1e-6):
        return math.isclose(self.x, other.x, tol) and math.isclose(self.y, other.y, tol)


@sexp_type('pts')
class PointList:
    xy : List(XYCoord) = field(default_factory=list)


@sexp_type('xyz')
class XYZCoord:
    x: float = 0
    y: float = 0
    z: float = 0


@sexp_type('at')
class AtPos(XYCoord):
    x: float = 0 # in millimeter
    y: float = 0 # in millimeter
    rotation: int = 0  # in degrees, can only be 0, 90, 180 or 270.
    unlocked: Flag() = False

    def __before_sexp__(self):
        self.rotation = int(round(self.rotation % 360))

    @property
    def rotation_rad(self):
        return math.radians(self.rotation)

    @rotation_rad.setter
    def rotation_rad(self, value):
        self.rotation = math.degrees(value)


@sexp_type('font')
class FontSpec:
    face: Named(str) = None
    size: Rename(XYCoord) = field(default_factory=lambda: XYCoord(1.27, 1.27))
    thickness: Named(float) = None
    bold: Flag() = False
    italic: Flag() = False
    line_spacing: Named(float) = None


@sexp_type('justify')
class Justify:
    h: AtomChoice(Atom.left, Atom.right) = None
    v: AtomChoice(Atom.top, Atom.bottom) = None
    mirror: Flag() = False


@sexp_type('effects')
class TextEffect:
    font: FontSpec = field(default_factory=FontSpec)
    justify: OmitDefault(Justify) = field(default_factory=Justify)
    hide: Flag() = False


@sexp_type('tstamp')
class Timestamp:
    value: str = field(default_factory=uuid.uuid4)

    def __after_parse__(self, parent):
        self.value = str(self.value)

    def before_sexp(self):
        self.value = Atom(str(self.value))

    def bump(self):
        self.value = uuid.uuid4()

@sexp_type('tedit')
class EditTime:
    value: str = field(default_factory=time.time)

    def __after_parse__(self, parent):
        self.value = int(str(self.value), 16)

    def __before_sexp__(self):
        self.value = Atom(f'{int(self.value):08X}')

    def bump(self):
        self.value = time.time()

