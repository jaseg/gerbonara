"""
Library for handling KiCad's schematic files (`*.kicad_sch`).
"""

import math
import string
from pathlib import Path
from dataclasses import field, replace, KW_ONLY
from itertools import chain
import re
import fnmatch
import os.path
import warnings

from .sexp import *
from .base_types import *
from .primitives import *
from .symbols import Symbol
from . import symbols
from . import graphical_primitives as gr

from .. import primitives as cad_pr
from ... import __version__

from ... import graphic_primitives as gp
from ... import graphic_objects as go
from ... import apertures as ap
from ...layers import LayerStack
from ...newstroke import Newstroke
from ...utils import MM, Inch, rotate_point, Tag, setup_svg, arc_bounds, sum_bounds
from .schematic_colors import *


@sexp_type('path')
class SheetPath:
    path: str = '/'
    page: Named(str) = '1'


@sexp_type('junction')
class Junction:
    at: Rename(XYCoord) = field(default_factory=XYCoord)
    diameter: Named(float) = 0
    color: Color = field(default_factory=lambda: Color(0, 0, 0, 0))
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        r = (self.diameter/2 or 0.5)
        return (self.at.x - r, self.at.y - r), (self.at.x + r, self.at.y + r)
    
    def to_svg(self, colorscheme=Colorscheme.KiCad):
        # KiCad's default diameter is six times its default wire width, and it draws junctions at least 1.7 times as
        # wide as the wire. A diameter of one of KiCad's schematic units, 100 nm, means that junctions are not drawn.
        if round(self.diameter * 1e4) == 1:
            return
        d = self.diameter or 6*KICAD_SCH_LINE_WIDTH
        r = max(d, 1.7*KICAD_SCH_LINE_WIDTH) / 2
        yield Tag('circle', cx=f'{self.at.x:.3f}', cy=f'{self.at.y:.3f}', r=f'{r:.3f}',
                   fill=self.color.svg(colorscheme.wire) if item_colors(colorscheme) else colorscheme.wire)


@sexp_type('no_connect')
class NoConnect:
    at: Rename(XYCoord) = field(default_factory=XYCoord)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        r = 0.635
        return (self.at.x - r, self.at.y - r), (self.at.x + r, self.at.y + r)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        r = MM(0.024, Inch) # half of KiCad's default size
        x, y = self.at.x, self.at.y
        yield Tag('path', d=f'M {x-r:.3f} {y-r:.3f} L {x+r:.3f} {y+r:.3f} M {x-r:.3f} {y+r:.3f} L {x+r:.3f} {y-r:.3f}',
                   fill='none', stroke_width=KICAD_SCH_LINE_WIDTH, stroke=colorscheme.no_connect, stroke_linecap='round')


@sexp_type('bus_alias')
class BusAlias:
    name: str = ''
    members: Named(Array(str)) = field(default_factory=list)


@sexp_type('bus_entry')
class BusEntry:
    at: AtPos = field(default_factory=AtPos)
    size: Rename(XYCoord) = field(default_factory=lambda: XYCoord(2.54, 2.54))
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        x1, y1 = self.at.x, self.at.y
        x2, y2 = x1 + self.size.x, y1 + self.size.y
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        r = (self.stroke.width or 0.254) / 2
        return (x1-r, y1-r), (x2+r, y2+r)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        width = self.stroke.width if (self.stroke.width or 0) > 0 else KICAD_SCH_LINE_WIDTH
        yield Tag('path', d=f'M {self.at.x:.3f} {self.at.y:.3f} l {self.size.x:.3f} {self.size.y:.3f}', fill='none',
                  **replace(self.stroke, width=width).svg_attrs(colorscheme.wire, own_color=item_colors(colorscheme)))


def _polyline_svg(self, colorscheme, default_color, default_width=KICAD_SCH_LINE_WIDTH):
    if len(self.points) < 2:
        warnings.warn(f'Schematic {type(self)} with less than two points')
        return Tag('path', d='')

    # KiCad draws lines whose width is not positive with the default width
    width = self.stroke.width if (self.stroke.width or 0) > 0 else default_width
    d = 'M ' + ' L '.join(f'{pt.x:.3f} {pt.y:.3f}' for pt in self.points)
    return Tag('path', d=d, fill='none',
               **replace(self.stroke, width=width).svg_attrs(default_color, own_color=item_colors(colorscheme)))


def _fill_svg(fill, colorscheme, stroked=True, stroke=None):
    if fill is None or fill.type == Atom.none:
        return 'none'
    elif fill.type == Atom.outline:
        # KiCad fills shapes of schematics with an outline fill with the color of their stroke (fixupSchFillMode())
        color = stroke.color if stroke is not None else None
    elif fill.type == Atom.color:
        color = fill.color
    else:
        return colorscheme.fill
    if not item_colors(colorscheme):
        return black_and_white_fill(color, stroked, colorscheme)
    # Without a color of its own, KiCad fills the shape with the line color
    return color.svg(colorscheme.lines) if color else colorscheme.lines


def _shape_svg(self, colorscheme, name='path', **attrs):
    stroked = self.stroke.width is None or self.stroke.width >= 0
    return Tag(name, **attrs, fill=_fill_svg(self.fill, colorscheme, stroked, self.stroke),
               **self.stroke.svg_attrs(colorscheme.lines, KICAD_SCH_LINE_WIDTH, item_colors(colorscheme)))


def _polyline_bounds(self):
    x1 = min(pt.x for pt in self.points)
    y1 = min(pt.y for pt in self.points)
    x2 = max(pt.x for pt in self.points)
    y2 = max(pt.y for pt in self.points)

    r = (self.stroke.width or 0.254) / 2
    return (x1-r, y1-r), (x2+r, y2+r)


def _shape_bounds(shape, points):
    # The box of points on a shape's outline, grown by half its stroke
    r = max(shape.stroke.width, 0)/2 if shape.stroke.width else KICAD_SCH_LINE_WIDTH/2
    return ((min(x for x, y in points) - r, min(y for x, y in points) - r),
            (max(x for x, y in points) + r, max(y for x, y in points) + r))


@sexp_type('wire')
class Wire:
    points: PointList = field(default_factory=list)
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        return _polyline_bounds(self)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield _polyline_svg(self, colorscheme, colorscheme.wire)


@sexp_type('bus')
class Bus:
    points: PointList = field(default_factory=list)
    stroke: Stroke = field(default_factory=Stroke)
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        return _polyline_bounds(self)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield _polyline_svg(self, colorscheme, colorscheme.bus, KICAD_SCH_BUS_WIDTH)


@sexp_type('polyline')
class Polyline:
    points: PointList = field(default_factory=list)
    stroke: Stroke = field(default_factory=Stroke)
    fill: OmitDefault(Fill) = None
    uuid: UUID = field(default_factory=UUID)

    # KiCad 6 drew graphic lines dashed by default, see Schematic.__after_parse__()
    legacy_dashed = False

    def bounding_box(self, default=None):
        return _polyline_bounds(self)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        if self.legacy_dashed and self.stroke.type == Atom.default:
            self = replace(self, stroke=replace(self.stroke, type=Atom.dash))
        # KiCad reads polylines of more than two points as shapes, which can be filled, and which it does not stroke
        # with a negative width. Lines of two points it draws with its default width then.
        if len(self.points) > 2:
            # Closed if the last point is the first, like KiCad's SVG plotter does it
            d = 'M ' + ' L '.join(f'{pt.x:.3f} {pt.y:.3f}' for pt in self.points[:-1])
            last = self.points[-1]
            d += ' Z' if (last.x, last.y) == (self.points[0].x, self.points[0].y) else f' L {last.x:.3f} {last.y:.3f}'
            yield _shape_svg(self, colorscheme, d=d, fill_rule='evenodd')
        else:
            yield _polyline_svg(self, colorscheme, colorscheme.lines)


@sexp_type('circle')
class Circle:
    center: Rename(XYCoord) = field(default_factory=XYCoord)
    radius: Named(float) = 0.0
    stroke: Stroke = field(default_factory=Stroke)
    fill: OmitDefault(Fill) = None
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        c, r = self.center, self.radius
        return _shape_bounds(self, [(c.x - r, c.y - r), (c.x + r, c.y + r)])

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield _shape_svg(self, colorscheme, 'circle', cx=f'{self.center.x:.3f}', cy=f'{self.center.y:.3f}',
                         r=f'{self.radius:.3f}')


@sexp_type('rectangle')
class Rectangle:
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    stroke: Stroke = field(default_factory=Stroke)
    fill: OmitDefault(Fill) = None
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        return _shape_bounds(self, [(self.start.x, self.start.y), (self.end.x, self.end.y)])

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        # From the top left corner clockwise, like the SVG rect that KiCad draws, or as a line from the top left if it is
        # flat, so that dashes start at the same place
        x1, x2 = sorted((self.start.x, self.end.x))
        y1, y2 = sorted((self.start.y, self.end.y))
        if x1 == x2 or y1 == y2:
            yield _shape_svg(self, colorscheme, d=f'M {x1:.3f} {y1:.3f} L {x2:.3f} {y2:.3f}')
        else:
            yield _shape_svg(self, colorscheme, d=f'M {x1:.3f} {y1:.3f} H {x2:.3f} V {y2:.3f} H {x1:.3f} Z')


@sexp_type('arc')
class Arc:
    start: Rename(XYCoord) = field(default_factory=XYCoord)
    mid: Rename(XYCoord) = field(default_factory=XYCoord)
    end: Rename(XYCoord) = field(default_factory=XYCoord)
    stroke: Stroke = field(default_factory=Stroke)
    fill: OmitDefault(Fill) = None
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        start, end = self.start, self.end
        try:
            (cx, cy), _r, sweep, _large = kicad_arc_svg_flags(start, self.mid, end)
        except ValueError: # start, mid and end on one line
            return _shape_bounds(self, [(start.x, start.y), (end.x, end.y)])
        points = arc_bounds(start.x, start.y, end.x, end.y, cx, cy, not sweep)
        # KiCad fills arcs as pie wedges
        if self.fill is not None and self.fill.type != Atom.none:
            points += ((cx, cy),)
        return _shape_bounds(self, points)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        start, end = self.start, self.end
        try:
            (cx, cy), r, sweep, large = kicad_arc_svg_flags(start, self.mid, end)
        except ValueError: # start, mid and end on one line
            yield _shape_svg(self, colorscheme, d=f'M {start.x:.3f} {start.y:.3f} L {end.x:.3f} {end.y:.3f}')
            return
        # Counter-clockwise, like KiCad's SVG plotter draws arcs, so that dashes start at the same end
        if sweep:
            start, end = end, start
        arc = f'M {start.x:.3f} {start.y:.3f} A {r:.4f} {r:.4f} 0 {int(large)} 0 {end.x:.3f} {end.y:.3f}'
        # KiCad fills arcs as pie wedges
        shape = _shape_svg(self, colorscheme, d=arc)
        if shape.attrs.get('fill', 'none') != 'none':
            yield Tag('path', d=f'{arc} L {cx:.3f} {cy:.3f} Z', fill=shape.attrs['fill'], stroke='none')
            shape.attrs['fill'] = 'none'
        yield shape


@sexp_type('bezier')
class Bezier:
    points: PointList = field(default_factory=list)
    stroke: Stroke = field(default_factory=Stroke)
    fill: OmitDefault(Fill) = None
    uuid: UUID = field(default_factory=UUID)

    def bounding_box(self, default=None):
        # The control polygon contains the curve.
        if not self.points:
            return default
        return _shape_bounds(self, [(pt.x, pt.y) for pt in self.points])

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        if len(self.points) != 4:
            return
        p0, *rest = self.points
        yield _shape_svg(self, colorscheme, d=f'M {p0.x:.3f} {p0.y:.3f} C ' + ' '.join(f'{p.x:.3f} {p.y:.3f}' for p in rest))


def label_shape_path_d(shape, w, h):
    """ Outline of a global or hierarchical label, from the connection point towards +x """
    left, right = {
        Atom.input: '<]',
        Atom.output: '[>',
        Atom.bidirectional: '<>',
        Atom.tri_state: '<>',
        Atom.passive: '[]'}.get(shape, '<]')
    r = h/2

    if left == '[':
        d = f'M {r:.3f} {r:.3f} L 0 {r:.3f} L 0 {-r:.3f} L {r:.3f} {-r:.3f}'
    else:
        d = f'M {r:.3f} {r:.3f} L 0 0 L {r:.3f} {-r:.3f}'

    e = w+r
    d += f' L {e:.3f} {-r:.3f}'

    if right == ']':
        return d + f' L {e+r:.3f} {-r:.3f} L {e+r:.3f} {r:.3f} L {e:.3f} {r:.3f} Z'
    else:
        return d + f' L {e+r:.3f} {0:.3f} L {e:.3f} {r:.3f} Z'


@sexp_type('property')
class DrawnProperty(TextMixin):
    private: Flag() = False
    key: str = None
    value: str = None
    id: Named(int) = None
    at: AtPos = field(default_factory=AtPos)
    show_name: Named(LegacyCompatibleFlag()) = None
    do_not_autoplace: Named(LegacyCompatibleFlag()) = None
    hide: OmitDefault(Named(LegacyCompatibleFlag())) = False
    effects: TextEffect = field(default_factory=TextEffect)
    _: SEXP_END = None
    parent: object = None

    def __after_parse__(self, parent=None):
        self.parent = parent

    # Alias value for text mixin
    @property
    def text(self):
        unit = getattr(self.parent, 'unit', 0)
        if self.key == 'Reference' and unit > 0 and getattr(self.parent, 'unit_count', 1) > 1:
            return f'{self.value}{string.ascii_uppercase[unit-1]}'
        else:
            return self.value

    @text.setter
    def text(self, value):
        self.value = value

    @property
    def default_v_align(self):
        return 'middle'

    @property
    def h_align(self):
        align = self.effects.justify.h_str
        if self.rotation in (90, 270):
            align = {'left': 'right', 'right': 'left'}.get(align, align)
        return align

    @property
    def rotation(self):
        rot = self.at.rotation
        rot += getattr(self.parent.at, 'rotation', 0)
        return rot%360

    @property
    def mirrored(self):
        if hasattr(self.parent, 'mirror'):
            return self.parent.mirror.x, self.parent.mirror.y
        return False, False

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        if not self.hide:
            yield from TextMixin.to_svg(self, colorscheme.values)


@dataclass
class TextLabel(TextMixin):
    text: str = ''
    shape: Named(AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive, Atom.dot, Atom.round, Atom.diamond, Atom.rectangle)) = Atom.passive
    exclude_from_sim: Named(YesNoAtom()) = False
    at: AtPos = field(default_factory=AtPos)
    fields_autoplaced: Named(YesNoAtom()) = False
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)
    properties: List(DrawnProperty) = field(default_factory=list)

    def _svg_rotation(self):
        # KiCad keeps text upright: at 180 or 270 degrees, it is drawn at 0 or 90 degrees with the justification its
        # file stores.
        return (270 if (self.at.rotation or 0) % 180 == 90 else 0), self.h_align


@sexp_type('text')
class Text(TextLabel):
    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield from TextMixin.to_svg(self, colorscheme.text)


@sexp_type('label')
class LocalLabel(TextLabel):
    @property
    def _text_offset(self):
        return (0, -2*self.line_width)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield from TextMixin.to_svg(self, colorscheme.labels)


def _label_pen_widths(label):
    # KiCad's pen width for the outline of a label, and the one it lays out the outline of global labels with
    f = label.effects.font
    size = f.size.y or 1.27
    if f.thickness:
        pens = f.thickness, f.thickness
    elif f.bold:
        pens = size/5, size/5
    else:
        pens = KICAD_SCH_LINE_WIDTH, size/8
    return [min(pen, size/4) for pen in pens]


def _markup_runs(text, size, base_size=None):
    # (text, size) of the runs of text with KiCad's overbar (~{...}), subscript (_{...}) and superscript (^{...})
    # markup, which can be nested. KiCad does not draw the markup characters, and draws sub- and superscripts, also
    # nested ones, at 0.8 times the text's size.
    base_size = base_size or size
    runs, plain, i = [], '', 0
    while i < len(text):
        if text[i] in '~_^' and text[i+1:i+2] == '{':
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {'{': 1, '}': -1}.get(text[j], 0)
                j += 1
            if depth == 0:
                runs.append((plain, size))
                runs += _markup_runs(text[i+2:j-1], size if text[i] == '~' else 0.8*base_size, base_size)
                plain, i = '', j
                continue
        plain += text[i]
        i += 1
    return [run for run in runs + [(plain, size)] if run[0]]


def _markup_glyph_width(text, size):
    # Width of the box of the glyphs of text with KiCad's markup, which is a fifth of the size of the last run narrower
    # than the advance width
    font = Newstroke.load()
    x = end = 0
    for run, run_size in _markup_runs(text, size):
        w = font.bounding_box(kicad_unescape(run), size=run_size, space_width=16/21)[1][0]
        end = max(end, x + w - 0.2*run_size)
        x += w
    return end


def _label_text(label, text_offset):
    # Where the text of a global or hierarchical label goes, and how it is rendered
    x, y, rot = label.at.x, label.at.y, round(label.at.rotation or 0) % 360
    dx, dy = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}.get(rot, (1, 0))
    return (x + dx*text_offset, y + dy*text_offset), dict(size=label.size,
                                                         h_align='left' if rot in (0, 90) else 'right',
                                                         v_align='middle',
                                                         rotation=-90 if rot in (90, 270) else 0,
                                                         scale=(1, 1))


def _label_svg(label, colorscheme, text_offset, frame_d):
    x, y, rot = label.at.x, label.at.y, round(label.at.rotation or 0) % 360
    (tx, ty), text_args = _label_text(label, text_offset)
    text = Newstroke.load().render_svg(label.text, **text_args, stroke=colorscheme.labels,
                                       transform=f'translate({tx:.3f} {ty:.3f})')
    frame = Tag('path', fill='none', stroke_width=_label_pen_widths(label)[0], stroke=colorscheme.lines, d=frame_d,
                stroke_linejoin='round',
                transform=f'translate({x:.3f} {y:.3f}) rotate({-rot})')
    return Tag('g', children=[frame, text])


def _label_bounds(label, text_offset, frame_d):
    # The box of what _label_svg() draws
    x, y, rot = label.at.x, label.at.y, round(label.at.rotation or 0) % 360
    c, s = round(math.cos(math.radians(rot))), round(math.sin(math.radians(rot)))
    coords = [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', frame_d)]
    frame = [(x + c*px + s*py, y - s*px + c*py) for px, py in zip(coords[0::2], coords[1::2])]
    (tx, ty), text_args = _label_text(label, text_offset)
    text = [(tx + px, ty + py) for stroke in Newstroke.load().render(label.text, **text_args) for px, py in stroke]
    boxes = []
    for points, r in ((frame, _label_pen_widths(label)[0]/2), (text, 0.1*label.size)):
        if points:
            boxes.append(((min(px for px, py in points) - r, min(py for px, py in points) - r),
                          (max(px for px, py in points) + r, max(py for px, py in points) + r)))
    return sum_bounds(boxes)


@sexp_type('global_label')
class GlobalLabel(TextLabel):
    def bounding_box(self, default=None):
        return _label_bounds(self, self.size*0.6, self._shape_d())

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield _label_svg(self, colorscheme, self.size*0.6, self._shape_d())

    def _shape_d(self):
        # Like KiCad's SCH_GLOBALLABEL::CreateGraphicShape(): drawn towards -x, then turned towards +x
        margin = 0.375*self.size
        half = self.size/2 + margin
        pen = _label_pen_widths(self)[1]
        # KiCad's text box is the box of the glyphs, grown by one and a half pen widths on each side
        x, y = _markup_glyph_width(self.text, self.size) + 3*pen + 2*margin + pen, half + pen
        points = [[0, 0], [0, -y], [-x, -y], [-x, 0], [-x, y], [0, y]]
        x_offset = 0
        if self.shape in (Atom.input, Atom.bidirectional, Atom.tri_state):
            x_offset = -half
            points[0][0] += half
        if self.shape in (Atom.output, Atom.bidirectional, Atom.tri_state):
            points[3][0] -= half
        return 'M ' + ' L '.join(f'{-(px + x_offset):.3f} {-py:.3f}' for px, py in points) + ' Z'


@sexp_type('hierarchical_label')
class HierarchicalLabel(TextLabel):
    def bounding_box(self, default=None):
        return _label_bounds(self, self.size*1.2, label_shape_path_d(self.shape, 0, self.size))

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        yield _label_svg(self, colorscheme, self.size*1.2, label_shape_path_d(self.shape, 0, self.size))


@sexp_type('netclass_flag')
class NetclassFlag(TextLabel):
    length: Named(float) = 2.54

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        # FIXME
        yield from TextMixin.to_svg(self, colorscheme.text)


@sexp_type('pin')
class Pin:
    name: str = '1'
    uuid: UUID = field(default_factory=UUID)
    alternate: Named(str) = None


@sexp_type('field')
class VariantField:
    name: Named(str) = ''
    value: Named(str) = ''


# Attributes that are None are inherited from the symbol or sheet.
@sexp_type('variant')
class Variant:
    name: Named(str) = ''
    dnp: Named(YesNoAtom()) = None
    exclude_from_sim: Named(YesNoAtom()) = None
    in_bom: Named(YesNoAtom()) = None
    on_board: Named(YesNoAtom()) = None
    in_pos_files: Named(YesNoAtom()) = None
    fields: List(VariantField) = field(default_factory=list)


# Suddenly, we're doing syntax like this is yaml or something.
@sexp_type('path')
class SymbolCrosslinkSheet:
    path: str = ''
    reference: Named(str) = ''
    unit: Named(int) = 1
    value: OmitDefault(Named(str)) = None
    footprint: OmitDefault(Named(str)) = None
    variants: List(Variant) = field(default_factory=list)


@sexp_type('project')
class SymbolCrosslinkProject:
    project_name: str = ''
    instances: List(SymbolCrosslinkSheet) = field(default_factory=list)


@sexp_type('mirror')
class MirrorFlags:
    x: Flag() = False
    y: Flag() = False


@sexp_type('default_instance')
class DefaultSymbolInstance:
    reference: Named(str) = ''
    unit: Named(int) = 1
    value: Named(str) = ''
    footprint: Named(str) = ''


@sexp_type('symbol')
class SymbolInstance:
    name: str = None
    lib_name: Named(str) = ''
    lib_id: Named(str) = ''
    at: AtPos = field(default_factory=AtPos)
    mirror: OmitDefault(MirrorFlags) = field(default_factory=MirrorFlags)
    unit: Named(int) = 1
    # De Morgan body style. KiCad 9 renamed (convert ...) to (body_style ...).
    convert: Named(int) = None
    body_style: Named(int) = None
    exclude_from_sim: Named(YesNoAtom()) = False
    in_bom: Named(YesNoAtom()) = True
    on_board: Named(YesNoAtom()) = True
    in_pos_files: Named(YesNoAtom()) = None
    dnp: Named(YesNoAtom()) = False
    fields_autoplaced: Named(YesNoAtom()) = True
    uuid: UUID = field(default_factory=UUID)
    default_instance: DefaultSymbolInstance = None
    properties: List(DrawnProperty) = field(default_factory=list)
    # AFAICT this property is completely redundant.
    pins: List(Pin) = field(default_factory=list)
    # AFAICT this property, too,  is completely redundant. It ultimately just lists paths and references of at most
    # three other uses of the same symbol in this schematic.
    instances: Named(Array(SymbolCrosslinkProject)) = field(default_factory=list)
    _ : SEXP_END = None
    schematic: object = field(repr=False, default=None)

    def __after_parse__(self, parent):
        self.schematic = parent

    @property
    def reference(self):
        return self['Reference'].value

    @reference.setter
    def reference(self, value):
        self['Reference'].value = value

    @property
    def value(self):
        return self['Value'].value

    @value.setter
    def value(self, value):
        self['Value'].value = value

    @property
    def footprint(self):
        return self['Footprint'].value

    @footprint.setter
    def footprint(self, value):
        self['Footprint'].value = value

    def __getitem__(self, key):
        for prop in self.properties:
            if prop.key == key:
                return prop

    @property
    def rotation(self):
        return self.at.rotation

    @property
    def unit_count(self):
        try:
            sym = self.schematic.lookup_symbol(self.lib_name, self.lib_id).resolve()
        except (AttributeError, KeyError):
            return 1
        return len({unit.unit_index for unit in sym.units} - {0}) or 1

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        children = []
        rot = self.at.rotation

        units = self._units()

        at_xform = xform = f'translate({self.at.x:.3f} {self.at.y:.3f})'
        if self.mirror.y:
            xform += f'scale(-1 -1)'
        elif self.mirror.x:
            xform += f'scale(1 1)'
        else:
            xform += f'scale(1 -1)'
        if rot:
            xform += f'rotate({rot})'

        # Where the dashes of circles, arcs and rectangles start depends on how the symbol is turned and mirrored
        oriented = (symbols.Circle, symbols.Arc, symbols.Rectangle)
        children = [foo for unit in units for elem in unit.graphical_elements
                    for foo in (elem.to_svg(colorscheme, orientation=(rot, self.mirror)) if isinstance(elem, oriented)
                                else elem.to_svg(colorscheme))]
        yield Tag('g', children=children, transform=xform, fill=colorscheme.fill, stroke=colorscheme.lines)

        selected = {pin.name: pin.alternate for pin in self.pins if pin.alternate}
        alternate = lambda pin: next((alt for alt in pin.alternates if alt.name == selected.get(pin.number.value)), None)
        children = [foo for unit in units for pin in unit.pins
                    for foo in pin.to_svg(colorscheme, self.mirror, rot, alternate(pin))]
        yield Tag('g', children=children, transform=at_xform, fill=colorscheme.fill, stroke=colorscheme.lines)

        for prop in self.properties:
            yield from prop.to_svg(colorscheme)

        if self.dnp:
            yield from self._dnp_svg(units, colorscheme)

    def _units(self):
        sym = self.schematic.lookup_symbol(self.lib_name, self.lib_id)
        style = self.body_style or self.convert or 1
        return [unit for unit in sym.units if (unit.unit_global or unit.unit_index == self.unit)
                and (unit.style_global or unit.demorgan_style == style)]

    def _dnp_svg(self, units, colorscheme):
        # Like KiCad's SCH_SYMBOL::PlotDNP(): a cross over the box of the symbol's body, that is its graphics and the
        # roots of its pins, grown by part of how far its pins reach beyond it
        body, pins = [], []
        for unit in units:
            for elem in unit.graphical_elements:
                if isinstance(elem, symbols.Rectangle):
                    elem = elem.to_polyline()
                if isinstance(elem, symbols.Bezier) and len(elem.points) == 4:
                    # KiCad measures Bézier curves by points on the curve, not by their control points
                    (ax, ay), (bx, by), (cx, cy), (dx, dy) = [(pt.x, pt.y) for pt in elem.points]
                    curve = lambda t, a, b, c, d: (1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t**2*c + t**3*d
                    points = [(curve(t/64, ax, bx, cx, dx), curve(t/64, ay, by, cy, dy)) for t in range(65)]
                    box = (min(x for x, y in points), min(y for x, y in points)), \
                          (max(x for x, y in points), max(y for x, y in points))
                elif isinstance(elem, (symbols.Polyline, symbols.Circle, symbols.Arc)):
                    box = elem.bounding_box()
                else:
                    continue
                (x1, y1), (x2, y2) = box
                w = max(0, elem.stroke.width or 0) / 2
                body += [(x1 - w, y1 - w), (x2 + w, y2 + w)]
                # The boxes of filled arcs include their center
                if isinstance(elem, symbols.Arc) and elem.fill is not None and elem.fill.type != 'none':
                    try:
                        body.append(elem._arc()[0])
                    except ValueError:
                        pass
            for pin in unit.pins:
                if not pin.hide:
                    a = math.radians(pin.at.rotation or 0)
                    root = (pin.at.x + pin.length*math.cos(a), pin.at.y + pin.length*math.sin(a))
                    body.append(root)
                    pins += [(pin.at.x, pin.at.y), root]
                    # KiCad's exports count pins with the circle that KiCad marks unconnected pins with, except no
                    # connect pins
                    if pin.etype not in ('no_connect', 'unconnected'):
                        r = KICAD_TARGET_PIN_RADIUS
                        pins += [(pin.at.x - r, pin.at.y - r), (pin.at.x + r, pin.at.y + r)]
        if not body:
            return

        def box(points):
            points = [symbols.sheet_vector(x, y, self.at.rotation, self.mirror) for x, y in points]
            xs, ys = [x for x, y in points], [y for x, y in points]
            return min(xs), min(ys), max(xs), max(ys)
        bx1, by1, bx2, by2 = box(body)
        px1, py1, px2, py2 = box(body + pins)
        mx, my = max(bx1 - px1, px2 - bx2), max(by1 - py1, py2 - by2)
        mx = max(mx*0.6, my*0.3)
        my = max(my*0.6, mx*0.3)
        x1, y1, x2, y2 = self.at.x + bx1 - mx, self.at.y + by1 - my, self.at.x + bx2 + mx, self.at.y + by2 + my
        yield Tag('path', d=f'M {x1:.3f} {y1:.3f} L {x2:.3f} {y2:.3f} M {x2:.3f} {y1:.3f} L {x1:.3f} {y2:.3f}',
                  fill='none', stroke=colorscheme.lines, stroke_width=f'{3*KICAD_SCH_LINE_WIDTH:.4f}',
                  stroke_linecap='round')


@sexp_type('path')
class SubsheetCrosslinkSheet:
    path: str = ''
    page: Named(str) = ''
    variants: List(Variant) = field(default_factory=list)


@sexp_type('project')
class SubsheetCrosslinkProject:
    project_name: str = ''
    instances: List(SubsheetCrosslinkSheet) = field(default_factory=list)


@sexp_type('pin')
class SubsheetPin:
    name: str = '1'
    shape: AtomChoice(Atom.input, Atom.output, Atom.bidirectional, Atom.tri_state, Atom.passive) = Atom.input
    at: AtPos = field(default_factory=AtPos)
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)
    _ : SEXP_END = None
    subsheet: object = None

    def __after_parse__(self, parent):
        self.subsheet = parent

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        size = self.effects.font.size.y or 1.27
        # KiCad draws input sheet pins with the shape of output hierarchical labels, and the other way around
        shape = {Atom.input: Atom.output, Atom.output: Atom.input}.get(self.shape, self.shape)
        yield Tag('path', fill='none', d=label_shape_path_d(shape, 0, size), stroke=colorscheme.lines,
                  stroke_width=_label_pen_widths(self)[0], stroke_linejoin='round',
                  transform=f'translate({self.at.x:.3f} {self.at.y:.3f}) rotate({180-self.at.rotation})')

        lx, ly = self.at.x, self.at.y
        dx, dy = rotate_point(-(size+1), 0, math.radians(self.at.rotation))
        lx += dx
        ly += dy
        frot = self.at.rotation
        h_align = 'right'
        if frot == 180:
            frot = 0
            h_align = 'left'

        font = Newstroke.load()
        yield font.render_svg(self.name,
                              size=size,
                              x0=0,
                              y0=0,
                              h_align=h_align,
                              v_align='middle',
                              rotation=-frot,
                              transform=f'translate({lx:.3f} {ly:.3f})',
                              scale=(1, 1),
                              mirror=(False, False),
                              stroke=colorscheme.labels,
                              )

@sexp_type('fill')
class SubsheetFill:
    color: Color = field(default_factory=lambda: Color(0, 0, 0, 0))


@sexp_type('sheet')
class Subsheet:
    at: Rename(XYCoord) = field(default_factory=XYCoord)
    size: Rename(XYCoord) = field(default_factory=lambda: XYCoord(2.54, 2.54))
    exclude_from_sim: Named(YesNoAtom()) = False
    in_bom: Named(YesNoAtom()) = False
    on_board: Named(YesNoAtom()) = False
    dnp: Named(YesNoAtom()) = False
    fields_autoplaced: Named(YesNoAtom()) = True
    stroke: Stroke = field(default_factory=Stroke)
    fill: SubsheetFill = field(default_factory=SubsheetFill)
    uuid: UUID = field(default_factory=UUID)
    _properties: List(DrawnProperty) = field(default_factory=list)
    pins: List(SubsheetPin) = field(default_factory=list)
    # AFAICT this is completely redundant, just like the one in SymbolInstance
    instances: Named(Array(SubsheetCrosslinkProject)) = field(default_factory=list)
    _ : SEXP_END = None
    sheet_name: object = field(default_factory=lambda: DrawnProperty(key='Sheetname', value=''))
    file_name: object = field(default_factory=lambda: DrawnProperty(key='Sheetfile', value=''))
    extra_properties: list = field(default_factory=list)
    schematic: object = field(repr=False, default=None)

    def __after_parse__(self, parent):
        self.sheet_name, self.file_name, *self.extra_properties = self._properties
        self.schematic = parent

    def __before_sexp__(self):
        self._properties = [self.sheet_name, self.file_name, *self.extra_properties]

    @property
    def rotation(self):
        return 0

    def open(self, search_dir=None, safe=True):
        if search_dir is None:
            if not self.schematic.original_filename:
                raise FileNotFoundError('No search path given and path of parent schematic unknown')
            else:
                search_dir = Path(self.schematic.original_filename).parent
        else:
            search_dir = Path(search_dir)

        resolved = search_dir / self.file_name.value
        if safe and os.path.commonprefix((search_dir.parts, resolved.parts)) != search_dir.parts:
                raise ValueError('Subsheet path traversal to parent directory attempted in Subsheet.open(..., safe=True)')

        return Schematic.open(resolved)

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        children = []

        for prop in self._properties:
            yield from prop.to_svg(colorscheme)

        # KiCad draws the borders of sheets solid, and with its default width if theirs is not positive
        width = self.stroke.width if (self.stroke.width or 0) > 0 else KICAD_SCH_LINE_WIDTH
        stroke = replace(self.stroke, width=width, type=Atom.solid)
        yield Tag('rect', x=f'{self.at.x:.3f}', y=f'{self.at.y:.3f}',
                  width=f'{self.size.x:.3f}', height=f'{self.size.y:.3f}',
                  **stroke.svg_attrs(colorscheme.lines, KICAD_SCH_LINE_WIDTH, item_colors(colorscheme)),
                  fill=self.fill.color.svg(colorscheme.fill) if item_colors(colorscheme) else colorscheme.fill)

        children = []
        for pin in self.pins:
            children += pin.to_svg(colorscheme)

        #xform = f'translate({self.at.x:.3f} {self.at.y:.3f})'
        yield Tag('g', children=children, #transform=xform,
                  fill=self.fill.color.svg(colorscheme.fill) if item_colors(colorscheme) else colorscheme.fill,
                  **stroke.svg_attrs(colorscheme.lines, KICAD_SCH_LINE_WIDTH, item_colors(colorscheme)))


@sexp_type('rule_area')
class RuleArea:
    # KiCad 10 lets rule areas set these attributes of the symbols inside them.
    exclude_from_sim: Named(YesNoAtom()) = None
    in_bom: Named(YesNoAtom()) = None
    on_board: Named(YesNoAtom()) = None
    dnp: Named(YesNoAtom()) = None
    polyline: Polyline = None

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        if self.polyline is None or len(self.polyline.points) < 3:
            return
        p0, *rest = self.polyline.points
        d = f'M {p0.x:.3f} {p0.y:.3f} ' + ' '.join(f'L {p.x:.3f} {p.y:.3f}' for p in rest) + ' Z'
        yield _shape_svg(self.polyline, colorscheme, d=d, fill_rule='evenodd')


@sexp_type('text_box')
class TextBox(TextMixin):
    text: str = None
    exclude_from_sim: Named(YesNoAtom()) = False
    at: AtPos = field(default_factory=AtPos)
    size: Rename(XYCoord) = None
    margins: Rename(gr.Margins) = None
    effects: TextEffect = field(default_factory=TextEffect)
    stroke: Stroke = field(default_factory=Stroke)
    fill: OmitDefault(Fill) = None
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)

    def render(self, variables={}, cache=None):
        yield from gr.TextBox.render(self, variables=variables)


@sexp_type('border')
class TableBorder:
    external: Named(YesNoAtom()) = True
    header: Named(YesNoAtom()) = True
    stroke: Stroke = field(default_factory=Stroke)


@sexp_type('separators')
class TableSeparators:
    rows: Named(YesNoAtom()) = True
    cols: Named(YesNoAtom()) = True
    stroke: Stroke = field(default_factory=Stroke)


@sexp_type('span')
class TableCellSpan:
    columns: int = 1
    rows: int = 1


@sexp_type('table_cell')
class TableCell:
    text: str = ''
    exclude_from_sim: Named(YesNoAtom()) = False
    at: AtPos = field(default_factory=AtPos)
    size: Rename(XYCoord) = field(default_factory=XYCoord)
    margins: Margins = None
    span: TableCellSpan = field(default_factory=TableCellSpan)
    fill: OmitDefault(Fill) = None
    effects: TextEffect = field(default_factory=TextEffect)
    uuid: UUID = field(default_factory=UUID)


# Cells are listed row by row, including the ones covered by another cell's span.
@sexp_type('table')
class Table:
    column_count: Named(int) = 1
    border: TableBorder = field(default_factory=TableBorder)
    separators: TableSeparators = field(default_factory=TableSeparators)
    column_widths: Named(Array(float)) = field(default_factory=list)
    row_heights: Named(Array(float)) = field(default_factory=list)
    cells: Named(Array(TableCell)) = field(default_factory=list)
    uuid: UUID = None


@sexp_type('lib_symbols')
class LocalLibrary:
    symbols: List(Symbol) = field(default_factory=list)


SUPPORTED_FILE_FORMAT_VERSIONS = [20230620]
@sexp_type('kicad_sch')
class Schematic:
    _version: Named(int, name='version') = 20230620
    generator: Named(str) = 'gerbonara'
    generator_version: Named(str) = __version__
    legacy_generator: Named(Array(str), name='host') = None
    uuid: UUID = field(default_factory=UUID)
    page_settings: PageSettings = field(default_factory=PageSettings)
    legacy_page: Named(Array(int), name='page') = None
    title_block: TitleBlock = None
    # The doc says this is expected, but eeschema barfs when it's there.
    # path: SheetPath = field(default_factory=SheetPath)
    lib_symbols: LocalLibrary = field(default_factory=LocalLibrary)
    junctions: List(Junction) = field(default_factory=list)
    no_connects: List(NoConnect) = field(default_factory=list)
    rule_areas: List(RuleArea) = field(default_factory=list)
    netclass_flags: List(NetclassFlag) = field(default_factory=list)
    bus_aliases: List(BusAlias) = field(default_factory=list)
    bus_entries: List(BusEntry) = field(default_factory=list)
    wires: List(Wire) = field(default_factory=list)
    buses: List(Bus) = field(default_factory=list)
    images: List(gr.Image) = field(default_factory=list)
    polylines: List(Polyline) = field(default_factory=list)
    circles: List(Circle) = field(default_factory=list)
    rectangles: List(Rectangle) = field(default_factory=list)
    arcs: List(Arc) = field(default_factory=list)
    beziers: List(Bezier) = field(default_factory=list)
    texts: List(Text) = field(default_factory=list)
    text_boxes: List(TextBox) = field(default_factory=list)
    tables: List(Table) = field(default_factory=list)
    local_labels: List(LocalLabel) = field(default_factory=list)
    global_labels: List(GlobalLabel) = field(default_factory=list)
    hierarchical_labels: List(HierarchicalLabel) = field(default_factory=list)
    symbols: List(SymbolInstance) = field(default_factory=list)
    subsheets: List(Subsheet) = field(default_factory=list)
    groups: List(Group) = field(default_factory=list)
    sheet_instances: Named(Array(SubsheetCrosslinkSheet)) = field(default_factory=list)
    symbol_instances: Named(Array(SymbolCrosslinkSheet)) = field(default_factory=list)
    embedded_fonts: Named(YesNoAtom()) = False
    _ : SEXP_END = None
    original_filename: str = None

    def __after_parse__(self, parent=None):
        # KiCad reads graphic lines of the default style in files of KiCad 6 and older as dashed
        for line in self.polylines:
            line.legacy_dashed = self._version <= 20211123

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        if value not in SUPPORTED_FILE_FORMAT_VERSIONS:
            raise FormatError(f'File format version {value} is not supported. Supported versions are {", ".join(map(str, SUPPORTED_FILE_FORMAT_VERSIONS))}.')


    def lookup_symbol(self, lib_name, lib_id):
        key = lib_name or lib_id
        for sym in self.lib_symbols.symbols:
            if sym.name == key or sym.raw_name == key:
                return sym
        raise KeyError(f'Symbol with {lib_name=} {lib_id=} not found')

    def write(self, filename=None):
        with open(filename or self.original_filename, 'w') as f:
            f.write(self.serialize())

    def serialize(self):
        return build_sexp(sexp(type(self), self)[0])

    @classmethod
    def open(kls, pcb_file, *args, **kwargs):
        return kls.load(Path(pcb_file).read_text(), *args, **kwargs, original_filename=pcb_file)

    @classmethod
    def load(kls, data, *args, **kwargs):
        return kls.parse(data, *args, **kwargs)

    @property
    def elements(self):
        yield from self.subsheets
        yield from self.images
        yield from self.rule_areas
        yield from self.polylines
        yield from self.rectangles
        yield from self.circles
        yield from self.arcs
        yield from self.beziers
        yield from self.symbols
        yield from self.junctions
        yield from self.no_connects
        yield from self.bus_entries
        yield from self.wires
        yield from self.buses
        yield from self.texts
        yield from self.local_labels
        yield from self.global_labels
        yield from self.hierarchical_labels

    def to_svg(self, colorscheme=Colorscheme.KiCad):
        children = []
        for elem in self.elements:
            children += elem.to_svg(colorscheme)
        w, h = self.page_settings.size
        return setup_svg(children, ((0, 0), (w, h)), pagecolor=colorscheme.background)


    
# From: https://jakevdp.github.io/blog/2012/10/07/xkcd-style-plots-in-matplotlib/
#def xkcd_line(x, y, xlim=None, ylim=None, mag=1.0, f1=30, f2=0.05, f3=15):
def xkcd_line(x, y, xlim=None, ylim=None, mag=1.0, f1=10, f2=0.05, f3=5):
    """
    Mimic a hand-drawn line from (x, y) data

    Parameters
    ----------
    x, y : array_like
        arrays to be modified
    xlim, ylim : data range
        the assumed plot range for the modification.  If not specified,
        they will be guessed from the  data
    mag : float
        magnitude of distortions
    f1, f2, f3 : int, float, int
        filtering parameters.  f1 gives the size of the window, f2 gives
        the high-frequency cutoff, f3 gives the size of the filter
    
    Returns
    -------
    x, y : ndarrays
        The modified lines
    """
    import numpy as np
    from scipy import interpolate, signal

    x = np.asarray(x)
    y = np.asarray(y)
    
    # get limits for rescaling
    if xlim is None:
        xlim = (x.min(), x.max())
    if ylim is None:
        ylim = (y.min(), y.max())

    if xlim[1] == xlim[0]:
        xlim = ylim
        
    if ylim[1] == ylim[0]:
        ylim = xlim

    # scale the data
    x_scaled = (x - xlim[0]) * 1. / (xlim[1] - xlim[0])
    y_scaled = (y - ylim[0]) * 1. / (ylim[1] - ylim[0])

    # compute the total distance along the path
    dx = x_scaled[1:] - x_scaled[:-1]
    dy = y_scaled[1:] - y_scaled[:-1]
    dist_tot = np.sum(np.sqrt(dx * dx + dy * dy))

    # number of interpolated points is proportional to the distance
    Nu = int(50 * dist_tot)
    u = np.arange(-1, Nu + 1) * 1. / (Nu - 1)

    # interpolate curve at sampled points
    k = min(3, len(x) - 1)
    res = interpolate.splprep([x_scaled, y_scaled], s=0, k=k)
    x_int, y_int = interpolate.splev(u, res[0]) 

    # we'll perturb perpendicular to the drawn line
    dx = x_int[2:] - x_int[:-2]
    dy = y_int[2:] - y_int[:-2]
    dist = np.sqrt(dx * dx + dy * dy)

    # create a filtered perturbation
    coeffs = mag * np.random.normal(0, 0.01, len(x_int) - 2)
    b = signal.firwin(f1, f2 * dist_tot, window=('kaiser', f3))
    response = signal.lfilter(b, 1, coeffs)

    x_int[1:-1] += response * dy / dist
    y_int[1:-1] += response * dx / dist

    # un-scale data
    x_int = x_int[1:-1] * (xlim[1] - xlim[0]) + xlim[0]
    y_int = y_int[1:-1] * (ylim[1] - ylim[0]) + ylim[0]
    
    return x_int, y_int

def wonkify(path):
    out = []
    for segment in path.attrs['d'].split('M')[1:]:
        if 'A' in segment:
            out.append(segment)
            continue

        points = segment.split('L')
        if points[-1].rstrip().endswith('Z'):
            closed = True
            points[-1] = points[-1].rstrip()[:-1].rstrip()
            points.append(points[0])
        else:
            closed = False

        pts = []
        lx, ly = None, None
        for pt in points:
            x, y = pt.strip().split()
            x, y = float(x), float(y)
            if (x, y) == (lx, ly):
                continue

            lx, ly = x, y
            pts.append((x, y))

        if len(pts) == 2:
            segs = [pts]

        else:
            seg = [pts[0]]
            segs = [seg]
            for p0, p1, p2 in zip(pts[0::], pts[1::], pts[2::]):
                dx1, dy1 = p1[0] - p0[0], p1[1] - p0[1]
                dx2, dy2 = p2[0] - p1[0], p2[1] - p1[1]
                l1, l2 = math.hypot(dx1, dy1), math.hypot(dx2, dy2)
                a1, a2 = math.atan2(dy1, dx1), math.atan2(dy2, dx2)
                da = (a2 - a1 + math.pi) % (2*math.pi) - math.pi
                if abs(da) > math.pi/4 and l1+l2 > 3:
                    seg.append(p1)
                    seg = [p1, p2]
                    segs.append(seg)
                seg.append(p1)
            seg.append(p2)

        for seg in segs:
            xs, ys = [x for x, y in seg], [y for x, y in seg]
            xs, ys = xkcd_line(xs, ys)
            d = ' L '.join(f'{x:.3f} {y:.3f}' for x, y in zip(xs, ys))
            if closed:
                d += ' Z'
            out.append(d)

    path.attrs['d'] = ' '.join(f'M {seg}' for seg in out)


def postprocess(tag):
    if tag.name == 'path':
        wonkify(tag)
    else:
        for child in tag.children:
            postprocess(child)
    return tag

if __name__ == '__main__':
    import sys
    from ...layers import LayerStack
    from .tmtheme import *
    sch = Schematic.open(sys.argv[1])
    print('Loaded schematic with', len(sch.wires), 'wires and', len(sch.symbols), 'symbols.')
    for subsh in sch.subsheets:
        subsh = subsh.open()
        print('Loaded sub-sheet with', len(subsh.wires), 'wires and', len(subsh.symbols), 'symbols.')

    sch.write('/tmp/test.kicad_sch')
    for p in Path('/tmp').glob('*.tmTheme'):
        cs = TmThemeSchematic(p.read_text())
        Path(f'/tmp/test-{p.stem}.svg').write_text(str(postprocess(sch.to_svg(cs))))
    for p in Path('/tmp').glob('*.sublime-color-scheme'):
        cs = SublimeSchematic(p.read_text())
        Path(f'/tmp/test-{p.stem}.svg').write_text(str(postprocess(sch.to_svg(cs))))

