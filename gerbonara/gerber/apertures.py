
import math
from dataclasses import dataclass, replace, fields, InitVar, KW_ONLY

from .aperture_macros.parse import GenericMacros

from . import graphic_primitives as gp


def _flash_hole(self, x, y, unit=None):
    if self.hole_rect_h is not None:
        return [*self.primitives(x, y, unit),
                Rectangle((x, y),
                    (self.convert(self.hole_dia, unit), self.convert(self.hole_rect_h, unit)),
                    rotation=self.rotation, polarity_dark=False)]
    else:
        return self.primitives(x, y), Circle((x, y), self.hole_dia, polarity_dark=False)

def strip_right(*args):
    args = list(args)
    while args and args[-1] is None:
        args.pop()
    return args


class Length:
    def __init__(self, obj_type):
        self.type = obj_type

CONVERSION_FACTOR = {None: 1, 'mm': 25.4, 'inch': 1/25.4}

@dataclass
class Aperture:
    _ : KW_ONLY
    unit : str = None

    @property
    def hole_shape(self):
        if self.hole_rect_h is not None:
            return 'rect'
        else:
            return 'circle'

    @property
    def hole_size(self):
        return (self.hole_dia, self.hole_rect_h)

    def convert(self, value, unit):
        if self.unit == unit or self.unit is None or unit is None or value is None:
            return value
        elif unit == 'mm':
            return value * 25.4
        else:
            return value / 25.4

    def convert_from(self, value, unit):
        if self.unit == unit or self.unit is None or unit is None or value is None:
            return value
        elif unit == 'mm':
            return value / 25.4
        else:
            return value * 25.4

    def params(self, unit=None):
        out = []
        for f in fields(self):
            if f.kw_only:
                continue

            val = getattr(self, f.name)
            if isinstance(f.type, Length):
                val = self.convert(val, unit)
            out.append(val)

        return out

    def flash(self, x, y, unit=None):
        return self.primitives(x, y, unit)

    def equivalent_width(self, unit=None):
        raise ValueError('Non-circular aperture used in interpolation statement, line width is not properly defined.')

    def to_gerber(self, settings=None):
        # Hack: The standard aperture shapes C, R, O do not have a rotation parameter. To make this API easier to use,
        # we emulate this parameter. Our circle, rectangle and oblong classes below have a rotation parameter. Only at
        # export time during to_gerber, this parameter is evaluated. 
        unit = settings.unit if settings else None
        #print(f'aperture to gerber {self.unit=} {settings=} {unit=}')
        actual_inst = self._rotated()
        params = 'X'.join(f'{float(par):.4}' for par in actual_inst.params(unit) if par is not None)
        return f'{actual_inst.gerber_shape_code},{params}'

    def __eq__(self, other):
        # We need to choose some unit here.
        return hasattr(other, to_gerber) and self.to_gerber('mm') == other.to_gerber('mm')

    def _rotate_hole_90(self):
        if self.hole_rect_h is None:
            return {'hole_dia': self.hole_dia, 'hole_rect_h': None}
        else:
            return {'hole_dia': self.hole_rect_h, 'hole_rect_h': self.hole_dia}


@dataclass
class CircleAperture(Aperture):
    gerber_shape_code = 'C'
    human_readable_shape = 'circle'
    diameter : Length(float)
    hole_dia : Length(float) = None
    hole_rect_h : Length(float) = None
    rotation : float = 0 # radians; for rectangular hole; see hack in Aperture.to_gerber

    def primitives(self, x, y, unit=None):
        return [ gp.Circle(x, y, self.convert(self.diameter/2, unit)) ]

    def __str__(self):
        return f'<circle aperture d={self.diameter:.3}>'

    flash = _flash_hole

    def equivalent_width(self, unit=None):
        return self.convert(self.diameter, unit)

    def dilated(self, offset, unit='mm'):
        offset = self.convert_from(offset, unit)
        return replace(self, diameter=self.diameter+2*offset, hole_dia=None, hole_rect_h=None)

    def _rotated(self):
        if math.isclose(self.rotation % (2*math.pi), 0) or self.hole_rect_h is None:
            return self
        else:
            return self.to_macro(self.rotation)

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.circle, self.params(unit='mm'))

    def params(self, unit=None):
        return strip_right(
                self.convert(self.diameter, unit),
                self.convert(self.hole_dia, unit),
                self.convert(self.hole_rect_h, unit))


@dataclass
class RectangleAperture(Aperture):
    gerber_shape_code = 'R'
    human_readable_shape = 'rect'
    w : Length(float)
    h : Length(float)
    hole_dia : Length(float) = None
    hole_rect_h : Length(float) = None
    rotation : float = 0 # radians

    def primitives(self, x, y, unit=None):
        return [ gp.Rectangle(x, y, self.convert(self.w, unit), self.convert(self.h, unit), rotation=self.rotation) ]

    def __str__(self):
        return f'<rect aperture {self.w:.3}x{self.h:.3}>'

    flash = _flash_hole

    def equivalent_width(self, unit=None):
        return self.convert(math.sqrt(self.w**2 + self.h**2), unit)

    def dilated(self, offset, unit='mm'):
        offset = self.convert_from(offset, unit)
        return replace(self, w=self.w+2*offset, h=self.h+2*offset, hole_dia=None, hole_rect_h=None)

    def _rotated(self):
        if math.isclose(self.rotation % math.pi, 0):
            return self
        elif math.isclose(self.rotation % math.pi, math.pi/2):
            return replace(self, w=self.h, h=self.w, **self._rotate_hole_90(), rotation=0)
        else: # odd angle
            return self.to_macro()

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.rect,
                [self.convert(self.w, 'mm'),
                    self.convert(self.h, 'mm'),
                    self.convert(self.hole_dia, 'mm') or 0,
                    self.convert(self.hole_rect_h, 'mm') or 0,
                    self.rotation])

    def params(self, unit=None):
        return strip_right(
                self.convert(self.w, unit),
                self.convert(self.h, unit),
                self.convert(self.hole_dia, unit),
                self.convert(self.hole_rect_h, unit))


@dataclass
class ObroundAperture(Aperture):
    gerber_shape_code = 'O'
    human_readable_shape = 'obround'
    w : Length(float)
    h : Length(float)
    hole_dia : Length(float) = None
    hole_rect_h : Length(float) = None
    rotation : float = 0

    def primitives(self, x, y, unit=None):
        return [ gp.Obround(x, y, self.convert(self.w, unit), self.convert(self.h, unit), rotation=self.rotation) ]

    def __str__(self):
        return f'<obround aperture {self.w:.3}x{self.h:.3}>'

    flash = _flash_hole

    def dilated(self, offset, unit='mm'):
        offset = self.convert_from(offset, unit)
        return replace(self, w=self.w+2*offset, h=self.h+2*offset, hole_dia=None, hole_rect_h=None)

    def _rotated(self):
        if math.isclose(self.rotation % math.pi, 0):
            return self
        elif math.isclose(self.rotation % math.pi, math.pi/2):
            return replace(self, w=self.h, h=self.w, **self._rotate_hole_90(), rotation=0)
        else:
            return self.to_macro()

    def to_macro(self):
        # generic macro only supports w > h so flip x/y if h > w
        inst = self if self.w > self.h else replace(self, w=self.h, h=self.w, **_rotate_hole_90(self), rotation=self.rotation-90)
        return ApertureMacroInstance(GenericMacros.obround,
                [self.convert(inst.w, 'mm'),
                    self.convert(ints.h, 'mm'),
                    self.convert(inst.hole_dia, 'mm'),
                    self.convert(inst.hole_rect_h, 'mm'),
                    inst.rotation])

    def params(self, unit=None):
        return strip_right(
                self.convert(self.w, unit),
                self.convert(self.h, unit),
                self.convert(self.hole_dia, unit),
                self.convert(self.hole_rect_h, unit))


@dataclass
class PolygonAperture(Aperture):
    gerber_shape_code = 'P'
    diameter : Length(float)
    n_vertices : int
    rotation : float = 0
    hole_dia : Length(float) = None

    def primitives(self, x, y, unit=None):
        return [ gp.RegularPolygon(x, y, self.convert(diameter, unit), n_vertices, rotation=self.rotation) ]

    def __str__(self):
        return f'<{self.n_vertices}-gon aperture d={self.diameter:.3}'

    def dilated(self, offset, unit='mm'):
        offset = self.convert_from(offset, unit)
        return replace(self, diameter=self.diameter+2*offset, hole_dia=None)

    flash = _flash_hole

    def _rotated(self):
        return self

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.polygon, self.params('mm'))

    def params(self, unit=None):
        rotation = self.rotation % (2*math.pi / self.n_vertices) if self.rotation is not None else None
        if self.hole_dia is not None:
            return self.convert(self.diameter, unit), self.n_vertices, rotation, self.convert(self.hole_dia, unit)
        elif rotation is not None and not math.isclose(rotation, 0):
            return self.convert(self.diameter, unit), self.n_vertices, rotation
        else:
            return self.convert(self.diameter, unit), self.n_vertices

@dataclass
class ApertureMacroInstance(Aperture):
    macro : object
    parameters : [float]
    rotation : float = 0

    @property
    def gerber_shape_code(self):
        return self.macro.name

    def primitives(self, x, y, unit=None):
        return [ primitive.with_offset(x, y).rotated(self.rotation, cx=0, cy=0)
                for primitive in self.macro.to_graphic_primitives(self.parameters, unit=unit) ]

    def dilated(self, offset, unit='mm'):
        return replace(self, macro=self.macro.dilated(offset, unit))

    def _rotated(self):
        if math.isclose(self.rotation % (2*math.pi), 0):
            return self
        else:
            return self.to_macro()

    def to_macro(self):
        return replace(self, macro=self.macro.rotated(self.rotation), rotation=0)

    def __eq__(self, other):
        return hasattr(other, 'macro') and self.macro == other.macro and \
                hasattr(other, 'params') and self.params == other.params and \
                hasattr(other, 'rotation') and self.rotation == other.rotation

    def params(self, unit=None):
        # We ignore "unit" here as we convert the actual macro, not this instantiation.
        # We do this because here we do not have information about which parameter has which physical units.
        return tuple(self.parameters)


