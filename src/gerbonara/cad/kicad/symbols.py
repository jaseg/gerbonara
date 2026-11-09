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
from .primitives import kicad_mid_to_center_arc, kicad_arc_svg_flags, Margins


PIN_ETYPE = AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive, Atom.free,
                       Atom.unspecified, Atom.power_in, Atom.power_out, Atom.open_collector, Atom.open_emitter,
                       Atom.no_connect, Atom.unconnected)


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
    hide: OmitDefault(Named(LegacyCompatibleFlag())) = False
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
        (_x1, _y1), (w, _y2) = font.bounding_box(self.name.value or '', size=2.54)
        h = 2.54
        l = self.length + 0.2 + w

        x1, y1 = x2, y2 = self.at.x, self.at.y
        if self.at.rotation == 0:
            x2 += l
            y1 -= h/2
            y2 += h/2
        elif self.at.rotation == 90:
            y2 += l
            x1 -= h/2
            x2 += h/2
        elif self.at.rotation == 180:
            x1 -= l
            y1 -= h/2
            y2 += h/2
        elif self.at.rotation == 270:
            y1 -= l
            x1 -= h/2
            x2 += h/2
        else:
            raise ValueError(f'Invalid pin rotation {self.at.rotation}')

        return (x1, y1), (x2, y2)

    def to_svg(self, colorscheme, p_mirror, p_rotation, alternate=None):
        if self.hide:
            return

        # Like KiCad's SCH_PIN::PlotPinType(), in the frame of the placed symbol, without its translation: from the
        # root of the pin at the body to its connection point, with decorations sized by KiCad's default pin symbol
        # size, and always above or left of the pin on the sheet where they are one-sided.
        sheet = lambda x, y: sheet_vector(x, y, p_rotation, p_mirror)
        a = math.radians(self.at.rotation or 0)
        px, py = sheet(self.at.x, self.at.y)
        x1, y1 = sheet(self.at.x + self.length*math.cos(a), self.at.y + self.length*math.sin(a))
        # From the root to the connection point, also for pins of length 0
        ux, uy = sheet(math.cos(a), math.sin(a))
        sign = lambda v: (v > 1e-6) - (v < -1e-6)
        mx, my = sign(-ux), sign(-uy)
        d = KICAD_PIN_SYMBOL_SIZE
        # An alternate function selected on the placed symbol replaces the pin's shape and type
        style, etype = (alternate.shape, alternate.etype) if alternate is not None else (self.style, self.etype)

        lines = []
        if style in ('inverted', 'inverted_clock'):
            yield Tag('circle', cx=f'{x1 + mx*d:.3f}', cy=f'{y1 + my*d:.3f}', r=f'{d:.3f}', fill='none',
                      stroke=colorscheme.lines, stroke_width=KICAD_SCH_LINE_WIDTH)
            lines.append([(x1 + mx*2*d, y1 + my*2*d), (px, py)])
        elif style == 'edge_clock_high':
            if my == 0:
                lines.append([(x1, y1 + d), (x1 + mx*2*d, y1), (x1, y1 - d)])
            else:
                lines.append([(x1 + d, y1), (x1, y1 + my*2*d), (x1 - d, y1)])
            lines.append([(x1 + mx*2*d, y1 + my*2*d), (px, py)])
        else:
            lines.append([(x1, y1), (px, py)])

        if style in ('clock', 'inverted_clock', 'clock_low'):
            if my == 0:
                lines.append([(x1, y1 + d), (x1 - mx*2*d, y1), (x1, y1 - d)])
            else:
                lines.append([(x1 + d, y1), (x1, y1 - my*2*d), (x1 - d, y1)])

        if style in ('input_low', 'clock_low'):
            if my == 0:
                lines.append([(x1 + mx*2*d, y1), (x1 + mx*2*d, y1 - 2*d), (x1, y1)])
            else:
                lines.append([(x1, y1 + my*2*d), (x1 - 2*d, y1 + my*2*d), (x1, y1)])

        if style == 'output_low':
            if my == 0:
                lines.append([(x1, y1 - 2*d), (x1 + mx*2*d, y1)])
            else:
                lines.append([(x1 - 2*d, y1), (x1, y1 + my*2*d)])
        elif style == 'non_logic':
            lines.append([(x1 - (mx + my)*d, y1 - (my - mx)*d), (x1 + (mx + my)*d, y1 + (my - mx)*d)])
            lines.append([(x1 - (mx - my)*d, y1 - (my + mx)*d), (x1 + (mx - my)*d, y1 + (my + mx)*d)])

        if etype in ('no_connect', 'unconnected'):
            r = KICAD_TARGET_PIN_RADIUS
            lines.append([(px - r, py - r), (px + r, py + r)])
            lines.append([(px + r, py - r), (px - r, py + r)])

        path_d = ' '.join('M ' + ' L '.join(f'{x:.3f} {y:.3f}' for x, y in line) for line in lines)
        yield Tag('path', d=path_d, fill='none', stroke=colorscheme.lines, stroke_width=KICAD_SCH_LINE_WIDTH,
                  stroke_linecap='round', stroke_linejoin='round')

        rot = self.at.rotation + p_rotation
        trot = self.at.rotation
        # With a positive pin name offset, names go inside the body, that far beyond the pin's inner end. With an
        # offset of 0, names go above the middle of the pin and numbers below it.
        spec = self.unit.symbol.pin_names if self.unit is not None and self.unit.symbol is not None else None
        offset = spec.offset if spec is not None and spec.offset is not None else 0.508
        names_inside = offset > 0
        ax, ay = (self.length + offset if names_inside else self.length/2), 0
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
                                  y0=0 if names_inside else -0.4,
                                  h_align=h_align if names_inside else 'center',
                                  v_align='middle' if names_inside else 'bottom',
                                  rotation=-frot,
                                  stroke=colorscheme.pin_names,
                                  transform=f'translate({lx:.3f} {ly:.3f})',
                                  scale=(sx, sy),
                                  mirror=(False, False),
                                  )

        if self.number.value != '~' and not self.unit.symbol.pin_numbers.hide:
            yield font.render_svg(self.number.value,
                                  size=self.number.effects.font.size.y or 1.27,
                                  x0=(-0.4 if h_align == 'left' else 0.4) if names_inside else 0,
                                  y0=-0.4 if names_inside else 0.4,
                                  h_align={'left': 'right', 'right': 'left'}[h_align] if names_inside else 'center',
                                  v_align='bottom' if names_inside else 'top',
                                  rotation=-frot,
                                  stroke=colorscheme.pin_numbers,
                                  scale=(sx, sy),
                                  transform=f'translate({lx:.3f} {ly:.3f})',
                                  mirror=(False, False),
                                  )



@sexp_type('fill')
class Fill:
    type: Named(AtomChoice(Atom.none, Atom.outline, Atom.background, Atom.color)) = Atom.none
    color: Color = None

    def svg(self, fg, bg):
        if self.type == 'outline':
            return fg
        elif self.type == 'background':
            return bg
        elif self.type == 'color' and self.color is not None:
            return self.color.svg(bg)
        else:
            return 'none'


def sheet_vector(x, y, rotation, mirror):
    # Library coordinates turned and mirrored like a placed symbol is, see SymbolInstance.to_svg()
    sx, sy = (-1, -1) if mirror.y else ((1, 1) if mirror.x else (1, -1))
    c, s = math.cos(math.radians(rotation or 0)), math.sin(math.radians(rotation or 0))
    return sx*(c*x - s*y), sy*(s*x + c*y)


def _sheet_sweep(sweep, orientation):
    # The sweep flag of an arc on the sheet, which mirroring the symbol turns around
    rotation, mirror = orientation
    return sweep if bool(mirror.x) != bool(mirror.y) else not sweep


@sexp_type('circle')
class Circle:
    center: Rename(XYCoord) = field(default_factory=XYCoord)
    radius: Named(float) = 0.0
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    def bounding_box(self, default=None):
        x, y, r = self.center.x, self.center.y, self.radius
        return (x-r, y-r), (x+r, y+r)

    def to_svg(self, colorscheme=Colorscheme.KiCad, orientation=None):
        attrs = dict(fill=self.fill.svg(colorscheme.lines, colorscheme.fill),
                     **self.stroke.svg_attrs(colorscheme.lines, KICAD_SCH_LINE_WIDTH))
        if orientation is None or 'stroke_dasharray' not in attrs:
            yield Tag('circle', cx=f'{self.center.x:.3f}', cy=f'{self.center.y:.3f}', r=f'{self.radius:.3f}', **attrs)
            return
        # KiCad draws circles on the sheet, so that their dashes start on the right and run clockwise there
        x, y, r = self.center.x, self.center.y, self.radius
        dx, dy = next((dx, dy) for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r))
                      if all(abs(a - b) < 1e-6 for a, b in zip(sheet_vector(dx, dy, *orientation), (r, 0))))
        sweep = int(not _sheet_sweep(False, orientation))
        yield Tag('path', d=f'M {x+dx:.3f} {y+dy:.3f} A {r:.3f} {r:.3f} 0 1 {sweep} {x-dx:.3f} {y-dy:.3f} '
                            f'A {r:.3f} {r:.3f} 0 1 {sweep} {x+dx:.3f} {y+dy:.3f} Z', **attrs)


@sexp_type('radius')
class ArcRadius:
    at: AtPos = field(default_factory=AtPos)
    length: Named(float) = 0.0
    angles: Rename(XYCoord) = field(default_factory=XYCoord)


@sexp_type('arc')
class Arc:
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    mid: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    radius: ArcRadius = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    @property
    def midpoint(self):
        # KiCad 6 symbols may give arcs as (radius (at center) (length r) (angles a1 a2)), running counter-clockwise
        if self.mid is not None and self.mid.x is not None:
            return self.mid
        if self.radius is None:
            raise ValueError('Arc has neither a midpoint nor a radius')
        a1, a2 = self.radius.angles.x, self.radius.angles.y
        if a2 < a1:
            a2 += 360
        a = math.radians((a1 + a2) / 2)
        return XYCoord(self.radius.at.x + self.radius.length*math.cos(a), self.radius.at.y + self.radius.length*math.sin(a))

    def _arc(self):
        return kicad_arc_svg_flags(self.start, self.midpoint, self.end)

    def bounding_box(self, default=None):
        try:
            (cx, cy), _r, sweep, _large = self._arc()
        except ValueError: # start, mid and end on one line
            return ((min(self.start.x, self.end.x), min(self.start.y, self.end.y)),
                    (max(self.start.x, self.end.x), max(self.start.y, self.end.y)))
        # Symbol coordinates have the y axis pointing up like arc_bounds expects, so increasing angle means counter-
        # clockwise.
        return arc_bounds(self.start.x, self.start.y, self.end.x, self.end.y, cx, cy, not sweep)

    def to_svg(self, colorscheme=Colorscheme.KiCad, orientation=None):
        fill = self.fill.svg(colorscheme.lines, colorscheme.fill)
        stroke = self.stroke.svg_attrs(colorscheme.lines, KICAD_SCH_LINE_WIDTH)
        start, end = self.start, self.end
        try:
            _c, r, sweep, large = self._arc()
        except ValueError: # start, mid and end on one line
            yield Tag('path', d=f'M {start.x:.3f} {start.y:.3f} L {end.x:.3f} {end.y:.3f}', fill='none', **stroke)
            return
        # Counter-clockwise on the sheet, like KiCad's SVG plotter draws arcs, so that dashes start at the same end
        if orientation is not None and _sheet_sweep(sweep, orientation):
            start, end, sweep = end, start, not sweep
        arc = f'M {start.x:.3f} {start.y:.3f} A {r:.3f} {r:.3f} 0 {int(large)} {int(sweep)} {end.x:.3f} {end.y:.3f}'
        yield Tag('path', d=arc, fill=fill, **stroke)


@sexp_type('bezier')
class Bezier:
    points: PointList = field(default_factory=list)
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    def bounding_box(self, default=None):
        # The control polygon contains the curve.
        if not self.points:
            return default
        return (min(p.x for p in self.points), min(p.y for p in self.points)), \
               (max(p.x for p in self.points), max(p.y for p in self.points))

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        if len(self.points) != 4:
            return
        p0, *rest = self.points
        d = f'M {p0.x:.3f} {p0.y:.3f} C ' + ' '.join(f'{p.x:.3f} {p.y:.3f}' for p in rest)
        yield Tag('path', d=d, fill=self.fill.svg(colorscheme.lines, colorscheme.fill),
                  **self.stroke.svg_attrs(colorscheme.lines, KICAD_SCH_LINE_WIDTH))


@sexp_type('polyline')
class Polyline:
    pts: PointList = field(default_factory=list)
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)

    @property
    def points(self):
        return self.pts

    @points.setter
    def points(self, value):
        self.pts = value

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
        yield Tag('path', d=d, fill=self.fill.svg(colorscheme.lines, colorscheme.fill),
                  **self.stroke.svg_attrs(colorscheme.lines, KICAD_SCH_LINE_WIDTH))

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
        return Polyline([XYCoord(x1, y1), XYCoord(x2, y1), XYCoord(x2, y2), XYCoord(x1, y2), XYCoord(x1, y1)],
                        self.stroke, self.fill)

    def to_svg(self, colorscheme=Colorscheme.KiCad, orientation=None):
        polyline = self.to_polyline()
        if orientation is not None:
            # KiCad draws rectangles on the sheet from their top left corner clockwise, or as a line from the top left
            # if they are flat, so that their dashes start at the same place
            corners = polyline.points[:4]
            sheet = [sheet_vector(pt.x, pt.y, *orientation) for pt in corners]
            key = lambda i: (round(sheet[i][0], 6), round(sheet[i][1], 6))
            first, last = min(range(4), key=key), max(range(4), key=key)
            if self.start.x == self.end.x or self.start.y == self.end.y:
                polyline.points = [corners[first], corners[last]]
            else:
                order = [(first + i) % 4 for i in range(4)]
                if abs(sheet[order[1]][1] - sheet[first][1]) > 1e-6: # the next corner is below, not to the right
                    order = [first] + order[1:][::-1]
                polyline.points = [corners[i] for i in order] + [corners[first]]
        return polyline.to_svg(colorscheme)


@sexp_type('property')
class Property(TextMixin):
    private: Flag() = False
    name: str = None
    value: str = None
    id: Named(int) = None
    at: AtPos = field(default_factory=AtPos)
    # These three are None when absent, so files without them round trip unchanged.
    show_name: Named(LegacyCompatibleFlag()) = None
    do_not_autoplace: Named(LegacyCompatibleFlag()) = None
    hide: Named(LegacyCompatibleFlag()) = None
    effects: TextEffect = field(default_factory=TextEffect)

    # Alias value for text mixin
    @property
    def text(self):
        return self.value

    @text.setter
    def text(self, value):
        self.value = value

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        if not self.hide:
            yield from TextMixin.to_svg(self, colorscheme.text)


@sexp_type('pin_numbers')
class PinNumberSpec:
    hide: Named(LegacyCompatibleFlag()) = False


@sexp_type('pin_names')
class PinNameSpec:
    offset: OmitDefault(Named(float)) = 0.508
    hide: OmitDefault(Named(LegacyCompatibleFlag())) = False

@sexp_type('text_box')
class TextBox:
    text: str = ''
    exclude_from_sim: OmitDefault(Named(YesNoAtom())) = False
    at: AtPos = field(default_factory=AtPos)
    size: Rename(XYCoord) = field(default_factory=XYCoord)
    margins: Margins = None
    stroke: Stroke = field(default_factory=Stroke)
    fill: Fill = field(default_factory=Fill)
    effects: TextEffect = field(default_factory=TextEffect)


@sexp_type('symbol')
class Unit:
    name: str = None
    circles: List(Circle) = field(default_factory=list)
    arcs: List(Arc) = field(default_factory=list)
    polylines: List(Polyline) = field(default_factory=list)
    beziers: List(Bezier) = field(default_factory=list)
    rectangles: List(Rectangle) = field(default_factory=list)
    texts: List(Text) = field(default_factory=list)
    text_boxes: List(TextBox) = field(default_factory=list)
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
        yield from self.beziers
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
    power: Named(AtomChoice(Atom('global'), Atom('local'), value_when_empty=True), omit_empty=False) = None
    body_styles: Named(Array(object)) = None
    pin_numbers: OmitDefault(PinNumberSpec) = field(default_factory=PinNumberSpec)
    pin_names: OmitDefault(PinNameSpec) = field(default_factory=PinNameSpec)
    exclude_from_sim: OmitDefault(Named(YesNoAtom())) = False
    exclude_from_sim: Named(YesNoAtom()) = False
    in_bom: Named(YesNoAtom()) = True
    on_board: Named(YesNoAtom()) = True
    in_pos_files: Named(YesNoAtom()) = None
    duplicate_pin_numbers_are_jumpers: Named(YesNoAtom()) = None
    jumper_pin_groups: Named(Array(Array(str))) = None
    properties: List(Property) = field(default_factory=list)
    units: List(Unit) = field(default_factory=list)
    embedded_fonts: Named(YesNoAtom()) = False
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
