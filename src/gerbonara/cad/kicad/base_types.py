import re
import string
import time
from dataclasses import field, replace
import math
import uuid
from contextlib import contextmanager
from itertools import cycle

from .sexp import *
from .sexp_mapper import *
from ...newstroke import Newstroke
from ...utils import rotate_point, sum_bounds, Tag, MM, Inch
from ...layers import LayerStack
from ... import apertures as ap
from ... import graphic_objects as go


LAYER_MAP_K2G = {
        'F.Cu': ('top', 'copper'),
        'B.Cu': ('bottom', 'copper'),
        'F.SilkS': ('top', 'silk'),
        'B.SilkS': ('bottom', 'silk'),
        'F.Paste': ('top', 'paste'),
        'B.Paste': ('bottom', 'paste'),
        'F.Mask': ('top', 'mask'),
        'B.Mask': ('bottom', 'mask'),
        'B.CrtYd': ('bottom', 'courtyard'),
        'F.CrtYd': ('top', 'courtyard'),
        'B.Fab': ('bottom', 'fabrication'),
        'F.Fab': ('top', 'fabrication'),
        'B.Adhes': ('bottom', 'adhesive'),
        'F.Adhes': ('top', 'adhesive'),
        'Dwgs.User': ('mechanical', 'drawings'),
        'Cmts.User': ('mechanical', 'comments'),
        'Edge.Cuts': ('mechanical', 'outline'),
        }

LAYER_MAP_G2K = {v: k for k, v in LAYER_MAP_K2G.items()}

# KiCad's paper sizes in landscape orientation, in mm
KICAD_PAPER_SIZES = {
    'A5': (210, 148),
    'A4': (297, 210),
    'A3': (420, 297),
    'A2': (594, 420),
    'A1': (841, 594),
    'A0': (1189, 841),
    'A': (MM(11, Inch), MM(8.5, Inch)),
    'B': (MM(17, Inch), MM(11, Inch)),
    'C': (MM(22, Inch), MM(17, Inch)),
    'D': (MM(34, Inch), MM(22, Inch)),
    'E': (MM(44, Inch), MM(34, Inch)),
    'USLetter': (MM(11, Inch), MM(8.5, Inch)),
    'USLegal': (MM(14, Inch), MM(8.5, Inch)),
    'USLedger': (MM(17, Inch), MM(11, Inch)),
    }


class BBoxMixin:
    def bounding_box(self, unit=MM):
        if not hasattr(self, '_bounding_box'):
            (min_x, min_y), (max_x, max_y) = sum_bounds(fe.bounding_box(unit) for fe in self.render())
            # Convert back from gerbonara's coordinates to kicad coordinates.
            self._bounding_box = (min_x, -max_y), (max_x, -min_y)

        return self._bounding_box


@sexp_type('uuid')
class UUID:
    value: str = field(default_factory=uuid.uuid4)

    def __deepcopy__(self, memo):
        return UUID()

    def __after_parse__(self, parent):
        self.value = str(self.value)

    def before_sexp(self):
        self.value = str(self.value)

    def bump(self):
        self.value = uuid.uuid4()


@sexp_type('group')
class Group:
    locked: Flag() = False
    name: str = ""
    id: Named(str) = None
    uuid: UUID = field(default_factory=UUID)
    members: Named(Array(str)) = field(default_factory=list)


@sexp_type('color')
class Color:
    r: int = None
    g: int = None
    b: int = None
    a: float = None
    
    def __bool__(self):
        return bool(self.r or self.b or self.g or not math.isclose(self.a or 0, 0, abs_tol=1e-3))

    def svg(self, default=None):
        if default and not self:
            return default

        return f'rgba({self.r} {self.g} {self.b} {self.a})'


_KICAD_ESCAPES = {'dblquote': '"', 'quote': "'", 'lt': '<', 'gt': '>', 'backslash': '\\', 'slash': '/', 'bar': '|',
                  'comma': ',', 'colon': ':', 'space': ' ', 'dollar': '$', 'tab': '\t', 'return': '\n', 'brace': '{'}


_KICAD_ESCAPE_RE = re.compile(r'(?<![$~^_])\{(' + '|'.join(_KICAD_ESCAPES) + r')\}')


def kicad_unescape(text):
    """ Undo KiCad's escaping of special characters like KiCad's UnescapeString() does. """
    return _KICAD_ESCAPE_RE.sub(lambda m: _KICAD_ESCAPES[m[1]], text) if text else text


# KiCad's default widths of lines and wires, and of buses, in schematics and symbols
KICAD_SCH_LINE_WIDTH = MM(0.006, Inch)
KICAD_SCH_BUS_WIDTH = MM(0.012, Inch)
# KiCad's default size of pin decorations, and the size of the cross on no connect pins
KICAD_PIN_SYMBOL_SIZE = MM(0.025, Inch)
KICAD_TARGET_PIN_RADIUS = MM(0.015, Inch)


@sexp_type('stroke')
class Stroke:
    width: Named(float) = 0.254
    type: Named(AtomChoice(Atom.dash, Atom.dot, Atom.dash_dot_dot, Atom.dash_dot, Atom.default, Atom.solid)) = Atom.default
    color: Color = None

    def svg_color(self, default=None):
        if self.color:
            return self.color.svg(default)
        else:
            return default
    
    def svg_attrs(self, default_color=None, default_width=0.254):
        # KiCad does not stroke shapes with a negative width
        if self.width is not None and self.width < 0:
            return {'stroke': 'none'}
        w = self.width or default_width
        if not (color := self.svg_color(default_color)):
            return {}

        attrs = {'stroke': color,
                'stroke_linecap': 'round',
                'stroke_linejoin': 'round',
                'stroke_width': w}

        if self.type not in (Atom.default, Atom.solid):
            attrs['stroke_dasharray'] = {
                    Atom.dash: f'{w*5:.3f},{w*5:.3f}',
                    Atom.dot: f'{w*2:.3f},{w*2:.3f}',
                    Atom.dash_dot: f'{w*5:.3f},{w*3:.3f},{w:.3f},{w*3:.3f}',
                    Atom.dash_dot_dot: f'{w*5:.3f},{w*3:.3f},{w:.3f},{w*3:.3f},{w:.3f},{w*3:.3f}',
                    }[self.type]

        return attrs


@sexp_type('fill')
class Fill:
    type: Named(AtomChoice(Atom.none, Atom.outline, Atom.background, Atom.color)) = Atom.none
    color: Color = None


class WidthMixin:
    def __post_init__(self):
        if self.width is not None:
            self.stroke = Stroke(self.width)


class Dasher:
    def __init__(self, obj, default_width=0.254):
        if obj.stroke:
            w = obj.stroke.width if obj.stroke.width and obj.stroke.width > 0 else default_width
            t = obj.stroke.type
        else:
            w = obj.width or 0
            t = Atom.solid
            
        self.width = w
        gap = 4*w
        dot = 0
        dash = 11*w
        self.pattern = {
                Atom.dash: [dash, gap],
                Atom.dot: [dot, gap],
                Atom.dash_dot_dot: [dash, gap, dot, gap, dot, gap],
                Atom.dash_dot: [dash, gap, dot, gap],
                Atom.default: [1e99],
                Atom.solid: [1e99]}[t]
        self.solid = t in (Atom.default, Atom.solid)
        self.start_x, self.start_y = None, None
        self.cur_x, self.cur_y = None, None
        self.segments = []

    def move(self, x, y):
        if self.cur_x is None:
            self.start_x, self.start_y = x, y
        self.cur_x, self.cur_y = x, y

    def line(self, x, y):
        if x is None or y is None:
            raise ValueError('line() called before move()')
        self.segments.append((self.cur_x, self.cur_y, x, y))
        self.cur_x, self.cur_y = x, y

    def close(self):
        self.segments.append((self.cur_x, self.cur_y, self.start_x, self.start_y))
        self.cur_x, self.cur_y = None, None

    @staticmethod
    def _interpolate(x1, y1, x2, y2, length):
        dx, dy = x2-x1, y2-y1
        total = math.hypot(dx, dy)
        if total == 0:
            return x2, y2
        frac = length / total
        return x1 + dx*frac, y1 + dy*frac

    def __iter__(self):
        it = iter(self.segments)
        segment_remaining, segment_pos = 0, 0

        if self.width is None or self.width < 1e-3:
            return

        for length, stroked in cycle(zip(self.pattern, cycle([True, False]))):
            length = max(1e-12, length)
            while length > 0:
                if segment_remaining == 0:
                    try:
                        x1, y1, x2, y2 = next(it)
                    except StopIteration:
                        return
                    dx, dy = x2-x1, y2-y1
                    lx, ly = x1, y1
                    segment_remaining = math.hypot(dx, dy)
                    segment_pos = 0

                if segment_remaining > length:
                    segment_pos += length
                    ix, iy = self._interpolate(x1, y1, x2, y2, segment_pos)
                    segment_remaining -= length
                    if stroked:
                        yield lx, ly, ix, iy
                    lx, ly = ix, iy
                    break

                else:
                    length -= segment_remaining
                    segment_remaining = 0
                    if stroked:
                        yield lx, ly, x2, y2

    def svg(self, **kwargs):
        if 'fill' not in kwargs:
            kwargs['fill'] = 'none'
        if 'stroke' not in kwargs:
            kwargs['stroke'] = 'black'
        if 'stroke_width' not in kwargs:
            kwargs['stroke_width'] = self.width
        if 'stroke_linecap' not in kwargs:
            kwargs['stroke_linecap'] = 'round'

        d = ' '.join(f'M {x1:.3f} {y1:.3f} L {x2:.3f} {y2:.3f}' for x1, y1, x2, y2 in self)
        return Tag('path', d=d, **kwargs)


@sexp_type('xy')
class XYCoord:
    x: float = 0
    y: float = 0

    def __init__(self, x=None, y=None):
        if x is None:
            self.x, self.y = None, None
        elif isinstance(x, XYCoord):
            self.x, self.y = x.x, x.y
        elif isinstance(x, (tuple, list)):
            self.x, self.y = x
        elif hasattr(x, 'abs_pos'):
            self.x, self.y, _1, _2 = x.abs_pos
        elif hasattr(x, 'at'):
            self.x, self.y = x.at.x, x.at.y
        else:
            self.x, self.y = x, y

    def __iter__(self):
        return iter((self.x, self.y))

    def __getitem__(self, index):
        return (self.x, self.y)[index]

    def __setitem__(self, index, value):
        if index == 0:
            self.x = value
        elif index == 1:
            self.y = value
        else:
            raise IndexError(f'Invalid 2D point coordinate index {index}')

    def within_distance(self, x, y, dist):
        return math.dist((x, y), (self.x, self.y)) < dist

    def isclose(self, other, tol=1e-3):
        return math.isclose(self.x, other.x, tol) and math.isclose(self.y, other.y, tol)

    def with_offset(self, x=0, y=0):
        return replace(self, x=self.x+x, y=self.y+y)

    def with_rotation(self, angle, cx=0, cy=0):
        x, y = rotate_point(self.x, self.y, angle, cx, cy)
        return replace(self, x=x, y=y)


@sexp_type('pts')
class PointList:
    @classmethod
    def __map__(kls, obj, parent=None, path=''):
        _tag, *values = obj
        return [map_sexp(XYCoord, elem, parent=parent, path=path) for elem in values]

    @classmethod
    def __sexp__(kls, value):
        yield [kls.name_atom, *(e for elem in value for e in elem.__sexp__(elem))]


@sexp_type('arc')
class Arc:
    start: Rename(XYCoord) = None
    mid: Rename(XYCoord) = None
    end: Rename(XYCoord) = None


@sexp_type('pts')
class ArcPointList:
    @classmethod
    def __map__(kls, obj, parent=None, path=''):
        _tag, *values = obj
        return [map_sexp((XYCoord if elem[0] == 'xy' else Arc), elem, parent=parent, path=path) for elem in values]

    @classmethod
    def __sexp__(kls, value):
        yield [kls.name_atom, *(e for elem in value for e in elem.__sexp__(elem))]


@sexp_type('net')
class Net:
    index: int = 0
    name: str = ''


class NetMixin:
    def reset_net(self):
        self.net = Net()

    @property
    def net_index(self):
        if self.net is None:
            return 0
        return self.net.index

    @property
    def net_name(self):
        if self.net is None:
            return ''
        return self.net.name


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
    unlocked: Flag() = True

    def __before_sexp__(self):
        self.rotation = int(round(self.rotation % 360))

    @property
    def rotation_rad(self):
        return math.radians(self.rotation)

    @rotation_rad.setter
    def rotation_rad(self, value):
        self.rotation = math.degrees(value)

    def with_rotation(self, angle, cx=0, cy=0):
        obj = super().with_rotation(angle, cx, cy)
        return replace(obj, rotation=self.rotation + angle)


@sexp_type('font')
class FontSpec:
    face: Named(str) = None
    size: Rename(XYCoord) = field(default_factory=lambda: XYCoord(1.27, 1.27))
    thickness: Named(float) = None
    bold: OmitDefault(Named(LegacyCompatibleFlag())) = False
    italic: OmitDefault(Named(LegacyCompatibleFlag())) = False
    # Schematic text only
    color: Color = None
    line_spacing: Named(float) = None


@sexp_type('justify')
class Justify:
    h: AtomChoice(Atom.left, Atom.right) = None
    v: AtomChoice(Atom.top, Atom.bottom) = None
    mirror: Flag() = False

    @property
    def h_str(self):
        if self.h is None:
            return 'center'
        else:
            return str(self.h)

    @property
    def v_str(self):
        if self.v is None:
            return 'middle'
        else:
            return str(self.v)


@sexp_type('effects')
class TextEffect:
    font: FontSpec = field(default_factory=FontSpec)
    justify: OmitDefault(Justify) = field(default_factory=Justify)
    hide: OmitDefault(Named(LegacyCompatibleFlag())) = False
    # Hyperlink of schematic text
    href: Named(str) = None


class TextMixin:
    @property
    def size(self):
        return self.effects.font.size.y or 1.27

    @size.setter
    def size(self, value):
        self.effects.font.size.x = self.effects.font.size.y = value

    @property
    def line_width(self):
        return self.effects.font.thickness or 0.254

    @line_width.setter
    def line_width(self, value):
        self.effects.font.thickness = value

    def bounding_box(self, default=None):
        if not self.text or not self.text.strip():
            return default

        lines = list(self.render())
        x1 = min(min(l.x1, l.x2) for l in lines)
        y1 = min(min(l.y1, l.y2) for l in lines)
        x2 = max(max(l.x1, l.x2) for l in lines)
        y2 = max(max(l.y1, l.y2) for l in lines)
        r = self.effects.font.thickness/2
        return (x1-r, -(y1-r)), (x2+r, -(y2+r))
    
    def svg_path_data(self):
        for line in self.render():
            yield f'M {line.x1:.3f} {line.y1:.3f} L {line.x2:.3f} {line.y2:.3f}'

    @property
    def default_v_align(self):
        return 'bottom'

    @property
    def h_align(self):
        return self.effects.justify.h_str

    @property
    def mirrored(self):
        return False, False

    def _svg_rotation(self):
        rot = self.rotation
        h_align = self.h_align
        mx, my = self.mirrored
        if rot in (90, 270):
            h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)
            rot = (rot+180)%360
        elif rot == 180:
            rot = 0
            h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)

        if my and rot in (0, 180):
            h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)
            rot = (rot+180)%360
        if mx and rot in (90, 270):
            h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)
            rot = (rot+180)%360
        if rot == 180:
            rot = 0
            h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)
        if rot == 90:
            rot = 270
            h_align = {'left': 'right', 'right': 'left'}.get(h_align, h_align)
        return rot, h_align

    def to_svg(self, color='black', variables={}):
        if not self.effects or self.effects.hide or not self.effects.font:
            return

        font = Newstroke.load()
        text = string.Template(self.text).safe_substitute(variables)
        aperture = ap.CircleAperture(self.line_width or 0.2, unit=MM)
        rot, h_align = self._svg_rotation()

        yield font.render_svg(text,
                              size=self.size or 1.27,
                              h_align=h_align,
                              v_align=self.effects.justify.v or self.default_v_align,
                              stroke=color,
                              stroke_width=f'{self.line_width:.3f}',
                              scale=(1,1),
                              rotation=0,
                              transform=f'translate({self.at.x:.3f} {self.at.y:.3f}) rotate({rot})',
                              )

    @property
    def _text_offset(self):
        return (0, 0)

    @property
    def rotation(self):
        return self.at.rotation

    def render(self, variables={}):
        if not self.effects or self.effects.hide or not self.effects.font:
            return

        font = Newstroke.load()
        text = string.Template(self.text).safe_substitute(variables)
        aperture = ap.CircleAperture(self.line_width or 0.2, unit=MM)
        for stroke in font.render(text, 
                                  x0=self.at.x, y=self.at.y,
                                  size=self.size or 1.27,
                                  h_align=self.effects.justify.h_str,
                                  v_align=self.effects.justify.v_str,
                                  rotation=self.at.rotation,
                                  ):

            points = []
            for x, y in stroke:
                x, y = x+offx, y+offy
                x, y = rotate_point(x, y, math.radians(-rot or 0))
                x, y = x+self.at.x, y+self.at.y
                points.append((x, -y))

            for p1, p2 in zip(points[:-1], points[1:]):
                yield go.Line(*p1, *p2, aperture=aperture, unit=MM)



@sexp_type('tstamp')
class Timestamp:
    value: str = field(default_factory=uuid.uuid4)

    def __deepcopy__(self, memo):
        return Timestamp()

    def __after_parse__(self, parent):
        self.value = str(self.value)

    def before_sexp(self):
        self.value = Atom(str(self.value))

    def bump(self):
        self.value = uuid.uuid4()


@sexp_type('tedit')
class EditTime:
    value: str = field(default_factory=time.time)

    def __deepcopy__(self, memo):
        return EditTime()

    def __after_parse__(self, parent):
        self.value = int(str(self.value), 16)

    def __before_sexp__(self):
        self.value = Atom(f'{int(self.value):08X}')

    def bump(self):
        self.value = time.time()


@sexp_type('paper')
class PageSettings:
    page_format: str = 'A4'
    width: float = None
    height: float = None
    portrait: Flag() = False

    @property
    def size(self):
        """ (width, height) in mm """
        if self.page_format == 'User' and self.width and self.height:
            w, h = float(self.width), float(self.height)
        else:
            w, h = KICAD_PAPER_SIZES.get(str(self.page_format), KICAD_PAPER_SIZES['A4'])
        # Like KiCad's PAGE_INFO::SetPortrait(), which turns landscape pages upright and leaves portrait pages as they
        # are. KiCad's standard sizes are all landscape. KiCad only writes the flag for them, not for user sizes.
        if self.portrait and w > h:
            w, h = h, w
        return w, h


@sexp_type('property')
class Property:
    key: str = ''
    value: str = ''


@sexp_type('property')
class DrawnProperty(TextMixin):
    key: str = None
    value: str = None
    id: Named(int) = None
    at: AtPos = None
    unlocked: OmitDefault(Named(YesNoAtom())) = True
    layer: Named(str) = None
    hide: OmitDefault(Named(YesNoAtom())) = False
    uuid: UUID = None
    tstamp: Timestamp = None
    effects: OmitDefault(TextEffect) = field(default_factory=TextEffect)
    _ : SEXP_END = None
    parent: object = None

    def __after_parse(self, parent=None):
        self.parent = parent

    # Alias value for text mixin
    @property
    def text(self):
        return self.value

    @text.setter
    def text(self, value):
        self.value = value


@sexp_type('chamfer')
class Chamfer:
    top_left: Flag() = False
    top_right: Flag() = False
    bottom_left: Flag() = False
    bottom_right: Flag() = False


if __name__ == '__main__':
    class Foo:
        pass

    foo = Foo()
    foo.stroke =  troke(0.01, Atom.dash_dot_dot)
    d = Dasher(foo)
    #d = Dasher(Stroke(0.01, Atom.solid))
    d.move(1, 1)
    d.line(1, 2)
    d.line(3, 2)
    d.line(3, 1)
    d.close()

    print('<?xml version="1.0" standalone="no"?>')
    print('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">')
    print('<svg version="1.1" width="4cm" height="3cm" viewBox="0 0 4 3" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">')
    for x1, y1, x2, y2 in d:
        print(f'<path fill="none" stroke="black" stroke-width="0.01" stroke-linecap="round" d="M {x1},{y1} L {x2},{y2}"/>')
    print('</svg>')
