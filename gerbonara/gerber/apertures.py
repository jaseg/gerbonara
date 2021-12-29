
import math
from dataclasses import dataclass, replace, astuple

from .aperture_macros.parse import GenericMacros

from . import graphic_primitives as gp


def _flash_hole(self, x, y):
    if self.hole_rect_h is not None:
        return self.primitives(x, y), Rectangle((x, y), (self.hole_dia, self.hole_rect_h), rotation=self.rotation, polarity_dark=False)
    else:
        return self.primitives(x, y), Circle((x, y), self.hole_dia, polarity_dark=False)

def strip_right(*args):
    args = list(args)
    while args and args[-1] is None:
        args.pop()
    return args


class Aperture:
    @property
    def hole_shape(self):
        if self.hole_rect_h is not None:
            return 'rect'
        else:
            return 'circle'

    @property
    def hole_size(self):
        return (self.hole_dia, self.hole_rect_h)

    @property
    def params(self):
        return astuple(self)

    def flash(self, x, y):
        return self.primitives(x, y)

    @property
    def equivalent_width(self):
        raise ValueError('Non-circular aperture used in interpolation statement, line width is not properly defined.')

    def to_gerber(self):
        # Hack: The standard aperture shapes C, R, O do not have a rotation parameter. To make this API easier to use,
        # we emulate this parameter. Our circle, rectangle and oblong classes below have a rotation parameter. Only at
        # export time during to_gerber, this parameter is evaluated. 
        actual_inst = self._rotated()
        params = 'X'.join(f'{float(par):.4}' for par in actual_inst.params if par is not None)
        return f'{actual_inst.gerber_shape_code},{params}'

    def __eq__(self, other):
        return hasattr(other, to_gerber) and self.to_gerber() == other.to_gerber()

    def _rotate_hole_90(self):
        if self.hole_rect_h is None:
            return {'hole_dia': self.hole_dia, 'hole_rect_h': None}
        else:
            return {'hole_dia': self.hole_rect_h, 'hole_rect_h': self.hole_dia}


@dataclass(frozen=True)
class CircleAperture(Aperture):
    gerber_shape_code = 'C'
    human_readable_shape = 'circle'
    diameter : float
    hole_dia : float = None
    hole_rect_h : float = None
    rotation : float = 0 # radians; for rectangular hole; see hack in Aperture.to_gerber

    def primitives(self, x, y, rotation):
        return [ gp.Circle(x, y, self.diameter/2) ]

    def __str__(self):
        return f'<circle aperture d={self.diameter:.3}>'

    flash = _flash_hole

    @property
    def equivalent_width(self):
        return self.diameter

    def _rotated(self):
        if math.isclose(self.rotation % (2*math.pi), 0) or self.hole_rect_h is None:
            return self
        else:
            return self.to_macro(self.rotation)

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.circle, *self.params)

    @property
    def params(self):
        return strip_right(self.diameter, self.hole_dia, self.hole_rect_h)


@dataclass(frozen=True)
class RectangleAperture(Aperture):
    gerber_shape_code = 'R'
    human_readable_shape = 'rect'
    w : float
    h : float
    hole_dia : float = None
    hole_rect_h : float = None
    rotation : float = 0 # radians

    def primitives(self, x, y):
        return [ gp.Rectangle(x, y, self.w, self.h, rotation=self.rotation) ]

    def __str__(self):
        return f'<rect aperture {self.w:.3}x{self.h:.3}>'

    flash = _flash_hole

    @property
    def equivalent_width(self):
        return math.sqrt(self.w**2 + self.h**2)

    def _rotated(self):
        if math.isclose(self.rotation % math.pi, 0):
            return self
        elif math.isclose(self.rotation % math.pi, math.pi/2):
            return replace(self, w=self.h, h=self.w, **self._rotate_hole_90())
        else: # odd angle
            return self.to_macro()

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.rect, *self.params)

    @property
    def params(self):
        return strip_right(self.w, self.h, self.hole_dia, self.hole_rect_h)


@dataclass(frozen=True)
class ObroundAperture(Aperture):
    gerber_shape_code = 'O'
    human_readable_shape = 'obround'
    w : float
    h : float
    hole_dia : float = None
    hole_rect_h : float = None
    rotation : float = 0

    def primitives(self, x, y):
        return [ gp.Obround(x, y, self.w, self.h, rotation=self.rotation) ]

    def __str__(self):
        return f'<obround aperture {self.w:.3}x{self.h:.3}>'

    flash = _flash_hole

    def _rotated(self):
        if math.isclose(self.rotation % math.pi, 0):
            return self
        elif math.isclose(self.rotation % math.pi, math.pi/2):
            return replace(self, w=self.h, h=self.w, **self._rotate_hole_90())
        else:
            return self.to_macro()

    def to_macro(self, rotation:'radians'=0):
        # generic macro only supports w > h so flip x/y if h > w
        inst = self if self.w > self.h else replace(self, w=self.h, h=self.w, **_rotate_hole_90(self))
        return ApertureMacroInstance(GenericMacros.obround, *inst.params)

    @property
    def params(self):
        return strip_right(self.w, self.h, self.hole_dia, self.hole_rect_h)


@dataclass(frozen=True)
class PolygonAperture(Aperture):
    gerber_shape_code = 'P'
    diameter : float
    n_vertices : int
    rotation : float = 0
    hole_dia : float = None

    def primitives(self, x, y):
        return [ gp.RegularPolygon(x, y, diameter, n_vertices, rotation=self.rotation) ]

    def __str__(self):
        return f'<{self.n_vertices}-gon aperture d={self.diameter:.3}'

    flash = _flash_hole

    def _rotated(self):
        self.rotation %= (2*math.pi / self.n_vertices)
        return self

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.polygon, *self.params)

    @property
    def params(self):
        if self.hole_dia is not None:
            return self.diameter, self.n_vertices, self.rotation, self.hole_dia
        elif self.rotation:
            return self.diameter, self.n_vertices, self.rotation
        else:
            return self.diameter, self.n_vertices


class ApertureMacroInstance(Aperture):
    params : [float]
    rotation : float = 0

    def __init__(self, macro, *parameters):
        self.params = parameters
        self._primitives = macro.to_graphic_primitives(parameters)
        self.macro = macro

    @property
    def gerber_shape_code(self):
        return self.macro.name

    def primitives(self, x, y):
        # FIXME return graphical primitives not macro primitives here
        return [ primitive.with_offset(x, y).rotated(self.rotation, cx=0, cy=0) for primitive in self._primitives ]

    def _rotated(self):
        if math.isclose(self.rotation % (2*math.pi), 0):
            return self
        else:
            return self.to_macro()

    def to_macro(self):
        return type(self)(self.macro.rotated(self.rotation), self.params)

    def __eq__(self, other):
        return hasattr(other, 'macro') and self.macro == other.macro and \
                hasattr(other, 'params') and self.params == other.params and \
                hasattr(other, 'rotation') and self.rotation == other.rotation

    @property
    def params(self):
        return astuple(self)[:-1]


