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
from ...utils import rotate_point, Tag, arc_bounds
from ... import __version__
from ...newstroke import Newstroke
from .schematic_colors import *
from .primitives import kicad_mid_to_center_arc


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
    _: SEXP_END = None
    unit: object = None

    def __after_parse__(self, parent=None):
        self.unit = parent

    @property
    def direction(self):
        return {0: 'R', 90: 'U', 180: 'L', 270: 'D'}.get(self.at.rotation, 'R')

    @direction.setter
    def direction(self, value):
        self.at.rotation = {0: 'R', 90: 'U', 180: 'L', 270: 'D'}[value[0].upper()]

    def bounding_box(self, default=None):
        font = Newstroke.load()
        strokes = list(font.render(self.name, size=2.54))
        min_x = min(x for st in strokes for x, y in st)
        min_y = min(y for st in strokes for x, y in st)
        max_x = max(x for st in strokes for x, y in st)
        max_y = max(y for st in strokes for x, y in st)
        w, h = max_x - min_x, max_y - min_y
        l = self.length + 0.2 + w

        x1, y1 = x2, y2 = self.at.x, self.at.y
        if self.at.rotation == 0:
            x2 += w
            y1 -= h/2
            y2 += h/2
        if self.at.rotation == 90:
            y2 += w
            x1 -= h/2
            x2 += h/2
        if self.at.rotation == 180:
            x1 -= w
            y1 -= h/2
            y2 += h/2
        if self.at.rotation == 270:
            y1 -= w
            x1 -= h/2
            x2 += h/2
        else:
            raise ValueError(f'Invalid pin rotation {self.at.rotation}')

        return (x1, y1), (x2, y2)

    def to_svg(self, colorscheme, p_mirror, p_rotation):
        if self.hide:
            return

        psx, psy = (-1 if p_mirror.x else 1), (-1 if p_mirror.y else 1)
        x1, y1 = self.at.x, self.at.y
        x2, y2 = self.at.x+self.length, self.at.y
        if p_mirror.y:
            p_xf = f'scale(-1 -1)'
        elif p_mirror.x:
            p_xf = f'scale(1 1)'
        else:
            p_xf = f'scale(1 -1)'
        p_xf += f'rotate({p_rotation})'
        xform = {'transform': f'{p_xf} translate({self.at.x:.3f} {self.at.y:.3f}) rotate({self.at.rotation})'}
        style = {'stroke_width': 0.254, 'stroke': colorscheme.lines, 'stroke_linecap': 'round'}

        yield Tag('path', **xform, **style, d=f'M 0 0 L {self.length:.3f} 0')

        eps = 1
        for tag in {
                'line': [],
                'inverted': [
                    Tag('circle', **xform, **style, cx=x2-eps/3-0.2, cy=y2, r=eps/3)],
                'clock': [
                    Tag('path', **xform, **style, d=f'M {x2} {y2-eps/2} L {x2+eps/2} {y2} L {x2} {y2+eps/2}')],
                'inverted_clock': [
                    Tag('circle', **xform, **style, cx=x2-eps/3-0.2, cy=y2, r=eps/3),
                    Tag('path', **xform, **style, d=f'M {x2} {y2-eps/2} L {x2+eps/2} {y2} L {x2} {y2+eps/2}')],
                'input_low': [
                    Tag('path', **xform, **style, d=f'M {x2} {y2} L {x2-eps} {y2-eps} L {x2-eps} {y2}')],
                'clock_low': [
                    Tag('path', **xform, **style, d=f'M {x2} {y2} L {x2-eps} {y2-eps} L {x2-eps} {y2}'),
                    Tag('path', **xform, **style, d=f'M {x2} {y2-eps/2} L {x2+eps/2} {y2} L {x2} {y2+eps/2}')],
                'output_low': [
                    Tag('path', **xform, **style, d=f'M {x2} {y2-eps} L {x2-eps} {y2}')],
                'edge_clock_high': [
                    Tag('path', **xform, **style, d=f'M {x2} {y2} L {x2-eps} {y2-eps} L {x2-eps} {y2}'),
                    Tag('path', **xform, **style, d=f'M {x2} {y2-eps/2} L {x2+eps/2} {y2} L {x2} {y2+eps/2}')],
                'non_logic': [
                    Tag('path', **xform, **style, d=f'M {x2-eps/2} {y2-eps/2} L {x2+eps/2} {y2+eps/2}'),
                    Tag('path', **xform, **style, d=f'M {x2-eps/2} {y2+eps/2} L {x2+eps/2} {y2-eps/2}')],
                # FIXME...
        }.get(self.style, []):
            yield tag

        rot = self.at.rotation + p_rotation
        trot = self.at.rotation
        ax, ay = self.length+0.2, 0
        ax, ay = rotate_point(ax, ay, math.radians(-self.at.rotation))

        #lx, ly = self.at.x, -self.at.y
        #lx, ly = rotate_point(lx, ly, math.radians(p_rotation))
        #if p_mirror.y:
        #    lx, ly = -lx, ly
        #elif p_mirror.x:
        #    lx, ly = lx, -ly
        #yield Tag('circle', cx=lx, cy=ly, r='0.5', stroke='blue', stroke_width='0.1', fill='none', z_index='100')

        lx, ly = self.at.x + ax, -self.at.y - ay
        lx, ly = rotate_point(lx, ly, math.radians(p_rotation))
        if p_mirror.y:
            lx, ly = -lx, ly
        elif p_mirror.x:
            lx, ly = lx, -ly
        #yield Tag('circle', cx=lx, cy=ly, r='0.5', stroke='red', stroke_width='0.1', fill='none', z_index='100')

        h_align = 'left'
        if p_mirror.y:
            if trot in (0, 180):
                trot = 180 - trot
        elif p_mirror.x:
            if p_rotation == 0:
                if trot in (90, 270):
                    trot = 360-trot
            else:
                if trot in (0, 180):
                    trot = 180 - trot
        frot = (trot + p_rotation)%360
        sx, sy = 1, 1

        if frot == 180:
            frot = 0
            h_align = 'right'
        elif frot == 270:
            frot = 90
            h_align = 'right'

        font = Newstroke.load()
        if self.name.value != '~' and not self.unit.symbol.pin_names.hide:
            yield font.render_svg(self.name.value,
                                  size=self.name.effects.font.size.y or 1.27,
                                  x0=0,
                                  y0=0,
                                  h_align=h_align,
                                  v_align='middle',
                                  rotation=-frot,
                                  stroke=colorscheme.pin_names,
                                  transform=f'translate({lx:.3f} {ly:.3f})',
                                  scale=(sx, sy),
                                  mirror=(False, False),
                                  )

        if self.number.value != '~' and not self.unit.symbol.pin_numbers.hide:
            yield font.render_svg(self.number.value,
                                  size=self.number.effects.font.size.y or 1.27,
                                  x0=-0.4 if h_align == 'left' else 0.4,
                                  y0=-0.4,
                                  h_align={'left': 'right', 'right': 'left'}[h_align],
                                  v_align='bottom',
                                  rotation=-frot,
                                  stroke=colorscheme.pin_numbers,
                                  scale=(sx, sy),
                                  transform=f'translate({lx:.3f} {ly:.3f})',
                                  mirror=(False, False),
                                  )



@sexp_type('fill')
class Fill:
    type: Named(AtomChoice(Atom.none, Atom.outline, Atom.background)) = Atom.none

    def svg(self, fg, bg):
        if self.type == 'outline':
            return fg
        elif self.type == 'background':
            return bg
        else:
            return 'none'


@sexp_type('circle')
class Circle:
    center: Rename(XYCoord) = field(default_factory=XYCoord)
    radius: Named(float) = 0.0
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    def bounding_box(self, default=None):
        x, y, r = self.center.x, self.center.y, self.radius
        return (x-r, y-r), (x+r, y+r)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield Tag('circle', cx=f'{self.center.x:.3f}', cy=f'{self.center.y:.3f}', r=f'{self.radius:.3f}',
                  fill=self.fill.svg(colorscheme.lines, colorscheme.fill),
                  **self.stroke.svg_attrs(colorscheme.lines))


@sexp_type('arc')
class Arc:
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    mid: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    def bounding_box(self, default=None):
        (cx, cy), r = kicad_mid_to_center_arc(self.mid, self.start, self.end)
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.mid.x-x1, self.mid.y-x2
        x3, y3 = (self.end.x - x1)/2, (self.end.y - y1)/2
        clockwise = math.atan2(x2*y3-x3*y2, x2*x3+y2*y3) > 0
        return arc_bounds(x1, y1, self.end.x, self.end.y, cx, cy, clockwise)


    def to_svg(self, colorscheme=Colorscheme.KiCad):
        (cx, cy), r = kicad_mid_to_center_arc(self.mid, self.start, self.end)

        x1r = self.start.x - cx
        y1r = self.start.y - cy
        x2r = self.end.x - cx
        y2r = self.end.y - cy
        a1 = math.atan2(x1r, y1r)
        a2 = math.atan2(x2r, y2r)
        da = (a2 - a1 + math.pi) % (2*math.pi) - math.pi

        large_arc = int(da > math.pi)
        d = f'M {self.start.x:.3f} {self.start.y:.3f} A {r:.3f} {r:.3f} 0 {large_arc} 0 {self.end.x:.3f} {self.end.y:.3f}'
        yield Tag('path', d=d, fill=self.fill.svg(colorscheme.lines, colorscheme.fill),
                  **self.stroke.svg_attrs(colorscheme.lines))


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
        return len(self.points) > 3 and self.points[0].isclose(self.points[-1])

    def bounding_box(self, default=None):
        if not self.points:
            return default

        return (min(p.x for p in self.points), min(p.y for p in self.points)), \
               (max(p.x for p in self.points), max(p.y for p in self.points))

    def as_rectangle(self):
        (maxx, maxy, minx, miny) = self.bbox()
        return Rectangle(minx, maxy, maxx, miny, self.stroke, self.fill)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        p0, *rest = self.points
        if not rest:
            return

        d = ' '.join([f'M {p0.x:.3f} {p0.y:.3f}', *(f'L {pn.x:.3f} {pn.y:.3f}' for pn in rest)])
        yield Tag('path', d=d, fill=self.fill.svg(colorscheme.lines, colorscheme.fill), **self.stroke.svg_attrs(colorscheme.lines))

    def is_rectangle(self):
        # A rectangle has 5 points and is closed
        if len(self.points) != 5 or not self.is_closed():
            return False
            
        # Check that we have all four corners present
        (x1, y1), (x2, y2) = self.bbox()
        if not all(any(cand.isclose(pt) for cand in self.points[:-1]) for pt in
                   [(x1, y1), (x1, y2), (x2, y2), (x2, y1)]):
            return False

        # Check that we only have horizontal or vertical lines
        if any(x2-x1 and y2-y1 for (x1, y1), (x2,  y2) in zip(self.points[:-1], self.points[1:])):
            return False

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
class Text(TextMixin):
    text: str = None
    at: TextPos = field(default_factory=TextPos)
    rotation: float = None
    effects: TextEffect = field(default_factory=TextEffect)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield from TextMixin.to_svg(self, colorscheme.text)


@sexp_type('rectangle')
class Rectangle:
    # Some v6 symbols use rectangles, newer ones encode them as polylines.
    # At some point in time we can most likely remove this class since its not used anymore

    start: Rename(XYCoord) = None
    end: Rename(XYCoord) = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    def to_polyline(self):
        x1, y1 = self.start.x, self.start.y
        x2, y2 = self.end.x, self.end.y
        return Polyline(PointList([XYCoord(x1, y1), XYCoord(x2, y1), XYCoord(x2, y2), XYCoord(x1, y2), XYCoord(x1, y1)]),
                        self.stroke, self.fill)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        return self.to_polyline().to_svg(colorscheme)


@sexp_type('property')
class Property(TextMixin):
    name: str = None
    value: str = None
    id: Named(int) = None
    at: AtPos = field(default_factory=AtPos)
    effects: TextEffect = field(default_factory=TextEffect)

    # Alias value for text mixin
    @property
    def text(self):
        return self.value

    @text.setter
    def text(self, value):
        self.value = value

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield from TextMixin.to_svg(self, colorscheme.text)


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
        if sym_name != self.symbol.raw_name.rpartition(':')[2]:
            raise FormatError(f'Unit name "{self.name}" does not match symbol name "{self.symbol.name}"')
        self.demorgan_style = int(demorgan_style)
        self.unit_index = int(unit_index)
        self.style_global = self.demorgan_style == 0
        self.unit_global = self.unit_index == 0

    @property
    def graphical_elements(self):
        yield from self.rectangles
        yield from self.polylines
        yield from self.circles
        yield from self.arcs
        yield from self.texts

    def __before_sexp__(self):
        self.name = f'{self.symbol.name}_{self.unit_index}_{self.demorgan_style}'

    def pin_stacks(self):
        stacks = defaultdict(lambda: set())
        for pin in self.all_pins():
            stacks[(pin.at.x, pin.at.y)].add(pin)
        return stacks


@sexp_type('symbol')
class Symbol:
    raw_name: str = None
    extends: Named(str) = None
    power: Wrap(Flag()) = False
    pin_numbers: OmitDefault(PinNumberSpec) = field(default_factory=PinNumberSpec)
    pin_names: OmitDefault(PinNameSpec) = field(default_factory=PinNameSpec)
    exclude_from_sim: OmitDefault(Named(YesNoAtom())) = False
    exclude_from_sim: Named(YesNoAtom()) = False
    in_bom: Named(YesNoAtom()) = True
    on_board: Named(YesNoAtom()) = True
    properties: List(Property) = field(default_factory=list)
    units: List(Unit) = field(default_factory=list)
    _ : SEXP_END = None
    library = None
    name: str = None
    library_name: str = None

    def __after_parse__(self, parent):
        self.library = parent

        self.library_name, _, self.name = self.raw_name.rpartition(':')

        if self.extends:
            self.in_bom = None
            self.on_board = None

        self.properties = {prop.name: prop for prop in self.properties}
        if (prop := self.properties.get('ki_fp_filters')):
            prop.value = prop.value.split() if prop.value else []

    def __before_sexp__(self):
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

    def resolve(self):
        if self.extends:
            return self.library[self.extends]
        else:
            return self

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
    generator: Named(str) = Atom.gerbonara
    generator_version: Named(str) = __version__
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
