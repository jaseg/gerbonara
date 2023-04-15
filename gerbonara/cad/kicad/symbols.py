"""
Library for processing KiCad's symbol files.
"""

import json
import string
import math
import re
import sys
import itertools
from fnmatch import fnmatch
from collections import defaultdict
from dataclasses import field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sexp import *
from .sexp_mapper import *
from .base_types import *


PIN_ETYPE = AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive, Atom.free,
                       Atom.unspecified, Atom.power_in, Atom.power_out, Atom.open_collector, Atom.open_emitter,
                       Atom.no_connect)


PIN_STYLE = AtomChoice(Atom.line, Atom.inverted, Atom.clock, Atom.inverted_clock, Atom.input_low, Atom.clock_low,
                       Atom.output_low, Atom.edge_clock_high, Atom.non_logic)


@sexp_type('alternate')
class AltFunction:
    name: str = None
    etype: PIN_ETYPE = Atom.unspecified
    shape: PIN_STYLE = Atom.line


@sexp_type('__styled_text')
class StyledText:
    value: str = None
    effects: TextEffect = field(default_factory=TextEffect)


@sexp_type('pin')
class Pin:
    etype: PIN_ETYPE = Atom.unspecified
    style: PIN_STYLE = Atom.line
    at: AtPos = field(default_factory=AtPos)
    length: Named(float) = 2.54
    hide: Flag() = False
    name: Rename(StyledText) = field(default_factory=StyledText)
    number: Rename(StyledText) = field(default_factory=StyledText)
    alternates: List(AltFunction) = field(default_factory=list)

    @property
    def direction(self):
        return {0: 'R', 90: 'U', 180: 'L', 270: 'D'}.get(self.at.rotation, 'R')

    @direction.setter
    def direction(self, value):
        self.at.rotation = {0: 'R', 90: 'U', 180: 'L', 270: 'D'}[value[0].upper()]


@sexp_type('fill')
class Fill:
    type: Named(AtomChoice(Atom.none, Atom.outline, Atom.background)) = Atom.none


@sexp_type('circle')
class Circle:
    center: Rename(XYCoord) = field(default_factory=XYCoord)
    radius: Named(float) = 0.0
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)


@sexp_type('arc')
class Arc:
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    mid: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    # TODO add function to calculate center, bounding box


@sexp_type('polyline')
class Polyline:
    pts: PointList = field(default_factory=PointList)
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    @property
    def points(self):
        return self.pts.xy

    @points.setter
    def points(self, value):
        self.pts.xy = value

    @property
    def closed(self):
        # if the last and first point are the same, we consider the polyline closed
        # a closed triangle will have 4 points (A-B-C-A) stored in the list of points
        return len(self.points) > 3 and self.points[0] == self.points[-1]

    @property
    def bbox(self):
        if not self.points:
            return (0.0, 0.0, 0.0, 0.0)

        return (min(p.x for p in self.points),
                min(p.y for p in self.points),
                max(p.x for p in self.points),
                max(p.y for p in self.points))

    def as_rectangle(self):
        (maxx, maxy, minx, miny) = self.get_boundingbox()
        return Rectangle(
            minx,
            maxy,
            maxx,
            miny,
            self.stroke_width,
            self.stroke_color,
            self.fill_type,
            self.fill_color,
            unit=self.unit,
            demorgan=self.demorgan,
        )

    def get_center_of_boundingbox(self):
        (maxx, maxy, minx, miny) = self.get_boundingbox()
        return ((minx + maxx) / 2, ((miny + maxy) / 2))

    def is_rectangle(self):
        # a rectangle has 5 points and is closed
        if len(self.points) != 5 or not self.is_closed():
            return False

        # construct lines between the points
        p0 = self.points[0]
        for p1_idx in range(1, len(self.points)):
            p1 = self.points[p1_idx]
            dx = p1.x - p0.x
            dy = p1.y - p0.y
            if dx != 0 and dy != 0:
                # if a line is neither horizontal or vertical its not
                # part of a rectangle
                return False
            # select next point
            p0 = p1

        return True


@sexp_type('at')
class TextPos(XYCoord):
    x: float = 0 # in millimeter
    y: float = 0 # in millimeter
    rotation: int = 0  # in degrees

    def __after_parse__(self, parent):
        self.rotation = self.rotation / 10

    def __before_sexp__(self):
        self.rotation = round((self.rotation % 360) * 10)

    @property
    def rotation_rad(self):
        return math.radians(self.rotation)

    @rotation_rad.setter
    def rotation_rad(self, value):
        self.rotation = math.degrees(value)


@sexp_type('text')
class Text:
    text: str = None
    at: TextPos = field(default_factory=TextPos)
    rotation: float = None
    effects: TextEffect = field(default_factory=TextEffect)


@sexp_type('rectangle')
class Rectangle:
    """
    Some v6 symbols use rectangles, newer ones encode them as polylines.
    At some point in time we can most likely remove this class since its not used anymore
    """

    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    def as_polyline(self):
        x1, y1 = self.start
        x2, y2 = self.end
        return Polyline([Point(x1, y1), Point(x2, y1), Point(x2, y2), Point(x1, y2), Point(x1, y1)],
                        self.stroke, self.fill)


@sexp_type('property')
class Property:
    name: str = None
    value: str = None
    id: Named(int) = None
    at: AtPos = field(default_factory=AtPos)
    effects: TextEffect = field(default_factory=TextEffect)


@sexp_type('pin_numbers')
class PinNumberSpec:
    hide: Flag() = False


@sexp_type('pin_names')
class PinNameSpec:
    offset: OmitDefault(Named(float)) = 0.508
    hide: Flag() = False


@sexp_type('symbol')
class Unit:
    name: str = None
    circles: List(Circle) = field(default_factory=list)
    arcs: List(Arc) = field(default_factory=list)
    polylines: List(Polyline) = field(default_factory=list)
    rectangles: List(Rectangle) = field(default_factory=list)
    texts: List(Text) = field(default_factory=list)
    pins: List(Pin) = field(default_factory=list)
    unit_name: Named(str) = None
    _ : SEXP_END = None
    global_units: list = field(default_factory=list)
    unit_global: Flag() = False
    style_global: Flag() = False
    demorgan_style: int = 1
    unit_index: int = 1
    symbol = None

    def __after_parse__(self, parent):
        self.symbol = parent

        if not (m := re.fullmatch(r'(.*)_([0-9]+)_([0-9]+)', self.name)):
            raise FormatError(f'Invalid unit name "{self.name}"')
        sym_name, unit_index, demorgan_style = m.groups()
        if sym_name != self.symbol.name:
            raise FormatError(f'Unit name "{self.name}" does not match symbol name "{self.symbol.name}"')
        self.demorgan_style = int(demorgan_style)
        self.unit_index = int(unit_index)
        self.style_global = self._demorgan_style == 0
        self.unit_global = self.unit_index == 0

    def __before_sexp__(self):
        self.name = f'{self.symbol.name}_{self.unit_index}_{self.demorgan_style}'

    def __getattr__(self, name):
        if name.startswith('all_'):
            name = name[4:]
            return itertools.chain(getattr(self.global_units, name, []), getattr(self, name, []))

    def pin_stacks(self):
        stacks = defaultdict(lambda: set())
        for pin in self.all_pins():
            stacks[(pin.at.x, pin.at.y)].add(pin)
        return stacks


@sexp_type('symbol')
class Symbol:
    name: str = None
    extends: Named(str) = None
    power: Wrap(Flag()) = False
    pin_numbers: OmitDefault(PinNumberSpec) = field(default_factory=PinNumberSpec)
    pin_names: OmitDefault(PinNameSpec) = field(default_factory=PinNameSpec)
    in_bom: Named(YesNoAtom()) = True
    on_board: Named(YesNoAtom()) = True
    properties: List(Property) = field(default_factory=list)
    raw_units: List(Unit) = field(default_factory=list)
    _ : SEXP_END = None
    styles: {str: {str: Unit}} = None
    global_units: {str: {str: Unit}} = None
    library = None

    def __after_parse__(self, parent):
        self.library = parent

        self.global_units = {}
        self.styles = {}

        if self.extends:
            self.in_bom = None
            self.on_board = None

        self.properties = {prop.name: prop for prop in self.properties}
        if (prop := self.properties.get('ki_fp_filters')):
            prop.value = prop.value.split() if prop.value else []

        for unit in self.raw_units:
            if unit.unit_global or unit.style_global:
                d = self.global_units.get(unit.demorgan_style, {})
                d[unit.name] = unit
                self.global_units[unit.demorgan_style] = d

                for other in self.raw_units:
                    if other.unit_global or other.style_global or other == unit:
                        continue
                    if not (unit.unit_global or other.name == unit.name):
                        continue
                    if not (unit.style_global or other.demorgan_style == unit.demorgan_style):
                        continue
                    other.global_units.append(unit)

            else:
                d = self.styles.get(unit.demorgan_style, {})
                d[unit.name] = unit
                self.styles[unit.demorgan_style] = d

    def __before_sexp__(self):
        self.raw_units = ([unit for style in self.global_units.values() for unit in style.values()] +
                            [unit for style in self.styles.values() for unit in style.values()])
        if (prop := self.properties.get('ki_fp_filters')):
            if not isinstance(prop.value, str):
                prop.value = ' '.join(prop.value)
        self.properties = list(self.properties.values())

    def default_properties(self):
        for i, (name, value, hide) in enumerate([
            ('Reference',       'U',        False),
            ('Value',           None,       False),
            ('Footprint',       None,       True),
            ('Datasheet',       None,       True),
            ('ki_locked',       None,       True),
            ('ki_keywords',     None,       True),
            ('ki_description',  None,       True),
            ('ki_fp_filters',   None,       False),
            ]):
            self.properties[name] = Property(name=name, value=value, id=i, effects=TextEffect(hide=hide))

    def units(self, demorgan_style=None):
        if self.extends:
            return self.library[self.extends].units(demorgan_style)
        else:
            return self.styles.get(demorgan_style or 'default', {})

    def get_center_rectangle(self, units):
        # return a polyline for the requested unit that is a rectangle
        # and is closest to the center
        candidates = {}
        # building a dict with floats as keys.. there needs to be a rule against that^^
        pl_rects = [i.as_polyline() for i in self.rectangles]
        pl_rects.extend(pl for pl in self.polylines if pl.is_rectangle())
        for pl in pl_rects:
            if pl.unit in units:
                # extract the center, calculate the distance to origin
                (x, y) = pl.get_center_of_boundingbox()
                dist = math.sqrt(x * x + y * y)
                candidates[dist] = pl

        if candidates:
            # sort the list return the first (smallest) item
            return candidates[sorted(candidates.keys())[0]]
        return None

    def is_graphic_symbol(self):
        return self.extends is None and (
            not self.pins or self.get_property("Reference").value == "#SYM"
        )

    def pins_by_name(self, demorgan_style=None):
        pins = defaultdict(lambda: set())
        for unit in self.units(demorgan_style):
            for pin in unit.all_pins:
                pins[pin.name].add(pin)
        return pins

    def pins_by_number(self, demorgan_style=None):
        pins = defaultdict(lambda: set())
        for unit in self.units(demorgan_style):
            for pin in unit.all_pins:
                pins[pin.number].add(pin)
        return pins

    def __getattr__(self, name):
        if name.startswith('all_'):
            return itertools.chain(getattr(unit, name) for unit in self.raw_units)

    def filter_pins(self, name=None, direction=None, electrical_type=None):
        for pin in self.all_pins:
            if name and not fnmatch(pin.name, name):
                continue
            if direction and not pin.direction in direction:
                continue
            if electrical_type and not pin.etype in electical_type:
                continue
            yield pin

    def heuristically_small(self):
        """ Heuristically try to determine whether this is a "small" component like a resistor, capacitor, LED, diode,
        or transistor etc. When we have at most two pins, or there is no filled rectangle as symbol outline and we have
        3 or 4 pins, we assume this is a small symbol.
        """
        if len(self.all_pins) <= 2:
            return True
        if len(self.all_pins) > 4:
            return False
        return bool(self.get_center_rectangle(range(self.unit_count)))


SUPPORTED_FILE_FORMAT_VERSIONS = [20211014, 20220914]
@sexp_type('kicad_symbol_lib')
class Library:
    _version: Named(int, name='version') = 20211014
    generator: Named(Atom) = Atom.kicad_library_utils
    symbols: List(Symbol) = field(default_factory=list)
    _ : SEXP_END = None
    original_filename: str = None

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        if value not in SUPPORTED_FILE_FORMAT_VERSIONS:
            raise FormatError(f'File format version {value} is not supported. Supported versions are {", ".join(map(str, SUPPORTED_FILE_FORMAT_VERSIONS))}.')

    @classmethod
    def open(cls, filename: str):
        with open(filename) as f:
            return cls.parse(f.read())

    def write(self, filename=None):
        with open(filename or self.original_filename, 'w') as f:
            f.write(build_sexp(sexp(self)))


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        a = Library.open(sys.argv[1])
        print(build_sexp(sexp(a)))
    else:
        print("pass a .kicad_sym file please")
