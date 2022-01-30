
import math
from dataclasses import dataclass, replace, field, fields, InitVar, KW_ONLY

from .aperture_macros.parse import GenericMacros
from .utils import MM, Inch

from . import graphic_primitives as gp


def _flash_hole(self, x, y, unit=None, polarity_dark=True):
    if getattr(self, 'hole_rect_h', None) is not None:
        return [*self.primitives(x, y, unit, polarity_dark),
                gp.Rectangle((x, y),
                    (self.unit.convert_to(unit, self.hole_dia), self.unit.convert_to(unit, self.hole_rect_h)),
                    rotation=self.rotation, polarity_dark=(not polarity_dark))]
    elif self.hole_dia is not None:
        return [*self.primitives(x, y, unit, polarity_dark),
                gp.Circle(x, y, self.unit.convert_to(unit, self.hole_dia/2), polarity_dark=(not polarity_dark))]
    else:
        return self.primitives(x, y, unit, polarity_dark)

def strip_right(*args):
    args = list(args)
    while args and args[-1] is None:
        args.pop()
    return args

def none_close(a, b):
    if a is None and b is None:
        return True
    elif a is not None and b is not None:
        return math.isclose(a, b)
    else:
        return False

class Length:
    def __init__(self, obj_type):
        self.type = obj_type

@dataclass
class Aperture:
    _ : KW_ONLY
    unit : str = None
    attrs : dict = field(default_factory=dict)
    original_number : str = None

    @property
    def hole_shape(self):
        if hasattr(self, 'hole_rect_h') and self.hole_rect_h is not None:
            return 'rect'
        else:
            return 'circle'

    def params(self, unit=None):
        out = []
        for f in fields(self):
            if f.kw_only:
                continue

            val = getattr(self, f.name)
            if isinstance(f.type, Length):
                val = self.unit.convert_to(unit, val)
            out.append(val)

        return out

    def flash(self, x, y, unit=None, polarity_dark=True):
        return self.primitives(x, y, unit, polarity_dark)

    def equivalent_width(self, unit=None):
        raise ValueError('Non-circular aperture used in interpolation statement, line width is not properly defined.')

    def to_gerber(self, settings=None):
        # Hack: The standard aperture shapes C, R, O do not have a rotation parameter. To make this API easier to use,
        # we emulate this parameter. Our circle, rectangle and oblong classes below have a rotation parameter. Only at
        # export time during to_gerber, this parameter is evaluated. 
        unit = settings.unit if settings else None
        actual_inst = self._rotated()
        params = 'X'.join(f'{float(par):.4}' for par in actual_inst.params(unit) if par is not None)
        if params:
            return f'{actual_inst.gerber_shape_code},{params}'
        else:
            return actual_inst.gerber_shape_code

    def __eq__(self, other):
        # We need to choose some unit here.
        return hasattr(other, 'to_gerber') and self.to_gerber(MM) == other.to_gerber(MM)

    def _rotate_hole_90(self):
        if self.hole_rect_h is None:
            return {'hole_dia': self.hole_dia, 'hole_rect_h': None}
        else:
            return {'hole_dia': self.hole_rect_h, 'hole_rect_h': self.hole_dia}

@dataclass(unsafe_hash=True)
class ExcellonTool(Aperture):
    human_readable_shape = 'drill'
    diameter : Length(float)
    plated : bool = None
    depth_offset : Length(float) = 0
    
    def primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Circle(x, y, self.unit.convert_to(unit, self.diameter/2), polarity_dark=polarity_dark) ]

    def to_xnc(self, settings):
        z_off = 'Z' + settings.write_excellon_value(self.depth_offset, self.unit) if self.depth_offset is not None else ''
        return 'C' + settings.write_excellon_value(self.diameter, self.unit) + z_off

    def __eq__(self, other):
        if not isinstance(other, ExcellonTool):
            return False

        if not self.plated == other.plated:
            return False

        if not none_close(self.depth_offset, self.unit(other.depth_offset, other.unit)):
            return False

        return none_close(self.diameter, self.unit(other.diameter, other.unit))

    def __str__(self):
        plated = '' if self.plated is None else (' plated' if self.plated else ' non-plated')
        z_off = '' if self.depth_offset is None else f' z_offset={self.depth_offset}'
        return f'<Excellon Tool d={self.diameter:.3f}{plated}{z_off} [{self.unit}]>'

    def equivalent_width(self, unit=MM):
        return unit(self.diameter, self.unit)

    def dilated(self, offset, unit=MM):
        offset = unit(offset, self.unit)
        return replace(self, diameter=self.diameter+2*offset)

    def _rotated(self):
        return self

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.circle, self.params(unit=MM))

    def params(self, unit=None):
        return [self.unit.convert_to(unit, self.diameter)]


@dataclass
class CircleAperture(Aperture):
    gerber_shape_code = 'C'
    human_readable_shape = 'circle'
    diameter : Length(float)
    hole_dia : Length(float) = None
    hole_rect_h : Length(float) = None
    rotation : float = 0 # radians; for rectangular hole; see hack in Aperture.to_gerber

    def primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Circle(x, y, self.unit.convert_to(unit, self.diameter/2), polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<circle aperture d={self.diameter:.3} [{self.unit}]>'

    flash = _flash_hole

    def equivalent_width(self, unit=None):
        return self.unit.convert_to(unit, self.diameter)

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        return replace(self, diameter=self.diameter+2*offset, hole_dia=None, hole_rect_h=None)

    def _rotated(self):
        if math.isclose(self.rotation % (2*math.pi), 0) or self.hole_rect_h is None:
            return self
        else:
            return self.to_macro(self.rotation)

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.circle, self.params(unit=MM))

    def params(self, unit=None):
        return strip_right(
                self.unit.convert_to(unit, self.diameter),
                self.unit.convert_to(unit, self.hole_dia),
                self.unit.convert_to(unit, self.hole_rect_h))


@dataclass
class RectangleAperture(Aperture):
    gerber_shape_code = 'R'
    human_readable_shape = 'rect'
    w : Length(float)
    h : Length(float)
    hole_dia : Length(float) = None
    hole_rect_h : Length(float) = None
    rotation : float = 0 # radians

    def primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Rectangle(x, y, self.unit.convert_to(unit, self.w), self.unit.convert_to(unit, self.h),
            rotation=self.rotation, polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<rect aperture {self.w:.3}x{self.h:.3} [{self.unit}]>'

    flash = _flash_hole

    def equivalent_width(self, unit=None):
        return self.unit.convert_to(unit, math.sqrt(self.w**2 + self.h**2))

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
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
                [MM(self.w, self.unit),
                    MM(self.h, self.unit),
                    MM(self.hole_dia, self.unit) or 0,
                    MM(self.hole_rect_h, self.unit) or 0,
                    self.rotation])

    def params(self, unit=None):
        return strip_right(
                self.unit.convert_to(unit, self.w),
                self.unit.convert_to(unit, self.h),
                self.unit.convert_to(unit, self.hole_dia),
                self.unit.convert_to(unit, self.hole_rect_h))


@dataclass
class ObroundAperture(Aperture):
    gerber_shape_code = 'O'
    human_readable_shape = 'obround'
    w : Length(float)
    h : Length(float)
    hole_dia : Length(float) = None
    hole_rect_h : Length(float) = None
    rotation : float = 0

    def primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Obround(x, y, self.unit.convert_to(unit, self.w), self.unit.convert_to(unit, self.h),
            rotation=self.rotation, polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<obround aperture {self.w:.3}x{self.h:.3} [{self.unit}]>'

    flash = _flash_hole

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
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
                [MM(inst.w, self.unit),
                 MM(ints.h, self.unit),
                 MM(inst.hole_dia, self.unit),
                 MM(inst.hole_rect_h, self.unit),
                 inst.rotation])

    def params(self, unit=None):
        return strip_right(
                self.unit.convert_to(unit, self.w),
                self.unit.convert_to(unit, self.h),
                self.unit.convert_to(unit, self.hole_dia),
                self.unit.convert_to(unit, self.hole_rect_h))


@dataclass
class PolygonAperture(Aperture):
    gerber_shape_code = 'P'
    diameter : Length(float)
    n_vertices : int
    rotation : float = 0
    hole_dia : Length(float) = None

    def __post_init__(self):
        self.n_vertices = int(self.n_vertices)

    def primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.RegularPolygon(x, y, self.unit.convert_to(unit, self.diameter)/2, self.n_vertices,
            rotation=self.rotation, polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<{self.n_vertices}-gon aperture d={self.diameter:.3} [{self.unit}]>'

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        return replace(self, diameter=self.diameter+2*offset, hole_dia=None)

    flash = _flash_hole

    def _rotated(self):
        return self

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.polygon, self.params(MM))

    def params(self, unit=None):
        rotation = self.rotation % (2*math.pi / self.n_vertices) if self.rotation is not None else None
        if self.hole_dia is not None:
            return self.unit.convert_to(unit, self.diameter), self.n_vertices, rotation, self.unit.convert_to(unit, self.hole_dia)
        elif rotation is not None and not math.isclose(rotation, 0):
            return self.unit.convert_to(unit, self.diameter), self.n_vertices, rotation
        else:
            return self.unit.convert_to(unit, self.diameter), self.n_vertices

@dataclass
class ApertureMacroInstance(Aperture):
    macro : object
    parameters : [float]
    rotation : float = 0

    @property
    def gerber_shape_code(self):
        return self.macro.name

    def primitives(self, x, y, unit=None, polarity_dark=True):
        out = list(self.macro.to_graphic_primitives(
                offset=(x, y), rotation=self.rotation,
                parameters=self.parameters, unit=unit, polarity_dark=polarity_dark))
        return out

    def dilated(self, offset, unit=MM):
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


