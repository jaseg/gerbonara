#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>
# Copyright 2022 Jan Sebastian Götte <gerbonara@jaseg.de>

import warnings
import contextlib
import math
from dataclasses import dataclass, fields, replace

from .expression import Expression, UnitExpression, ConstantExpression, expr

from .. import graphic_primitives as gp
from .. import graphic_objects as go
from ..utils import rotate_point, LengthUnit, MM


def point_distance(a, b):
    x1, y1 = a
    x2, y2 = b
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)


# we make our own here instead of using math.degrees to make sure this works with expressions, too.
def deg_to_rad(a):
    return a * (math.pi / 180)


def rad_to_deg(a):
    return a * (180 / math.pi)


@dataclass(frozen=True, slots=True)
class Primitive:
    unit: LengthUnit

    def __post_init__(self):
        for field in fields(self):
            if field.type == UnitExpression:
                value = getattr(self, field.name)
                if not isinstance(value, UnitExpression):
                    value = UnitExpression(expr(value), self.unit)
                object.__setattr__(self, field.name, value)
            elif field.type == Expression:
                object.__setattr__(self, field.name, expr(getattr(self, field.name)))

    def to_gerber(self, register_variable=None, settings=None):
        return f'{self.code},' + ','.join(
                getattr(self, field.name).optimized().to_gerber(register_variable, settings.unit)
                for field in fields(self) if issubclass(field.type, Expression))
    
    def substitute_params(self, binding, unit):
        out = replace(self, unit=unit, **{
                       field.name: getattr(self, field.name).calculate(binding, unit)
                       for field in fields(self) if issubclass(field.type, Expression)})
        return out

    def __str__(self):
        attrs = ','.join(str(getattr(self, name)).strip('<>') for name in type(self).__annotations__)
        return f'<{type(self).__name__} {attrs}>'

    def __repr__(self):
        return str(self)

    @classmethod
    def from_arglist(kls, unit, arglist):
        return kls(unit, *arglist)

    def parameters(self):
        for field in fields(self):
            if issubclass(field.type, Expression):
                yield from getattr(self, field.name).parameters()

    class Calculator:
        def __init__(self, instance, variable_binding={}, unit=None):
            self.instance = instance
            self.variable_binding = variable_binding
            self.unit = unit

        def __enter__(self):
            return self

        def __exit__(self, _type, _value, _traceback):
            pass

        def __getattr__(self, name):
            return getattr(self.instance, name).calculate(self.variable_binding, self.unit)

        def __call__(self, expr):
            return expr.calculate(self.variable_binding, self.unit)


@dataclass(frozen=True, slots=True)
class Circle(Primitive):
    code = 1
    exposure : Expression
    diameter : UnitExpression
    # center x/y
    x : UnitExpression = 0
    y : UnitExpression = 0
    rotation : Expression = 0

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            x, y = rotate_point(calc.x, calc.y, -(deg_to_rad(calc.rotation) + rotation), 0, 0)
            x, y = x+offset[0], y+offset[1]
            return [ gp.Circle(x, y, calc.diameter/2, polarity_dark=(bool(calc.exposure) == polarity_dark)) ]

    def substitute_params(self, binding, unit):
        with self.Calculator(self, binding, unit) as calc:
            x, y = rotate_point(calc.x, calc.y, -deg_to_rad(calc.rotation), 0, 0)
            new =  Circle(unit, self.exposure, calc.diameter, x, y)
            return new

    def dilated(self, offset, unit):
        return replace(self, diameter=self.diameter + UnitExpression(offset, unit))

    def scaled(self, scale):
        return replace(self, x=self.x * UnitExpression(scale), y=self.y * UnitExpression(scale),
                       diameter=self.diameter * UnitExpression(scale))


@dataclass(frozen=True, slots=True)
class VectorLine(Primitive):
    code = 20
    exposure : Expression
    width : UnitExpression
    start_x : UnitExpression
    start_y : UnitExpression
    end_x : UnitExpression
    end_y : UnitExpression
    rotation : Expression = 0

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            center_x = (calc.end_x + calc.start_x) / 2
            center_y = (calc.end_y + calc.start_y) / 2
            delta_x = calc.end_x - calc.start_x
            delta_y = calc.end_y - calc.start_y
            length = point_distance((calc.start_x, calc.start_y), (calc.end_x, calc.end_y))

            center_x, center_y = rotate_point(center_x, center_y, -(deg_to_rad(calc.rotation) + rotation), 0, 0)
            center_x, center_y = center_x+offset[0], center_y+offset[1]
            rotation += deg_to_rad(calc.rotation) + math.atan2(delta_y, delta_x)

            return [ gp.Rectangle(center_x, center_y, length, calc.width, rotation=rotation,
                        polarity_dark=(bool(calc.exposure) == polarity_dark)) ]

    def substitute_params(self, binding, unit):
        with self.Calculator(self, binding, unit) as calc:
            x1, y1 = rotate_point(calc.start_x, calc.start_y, -deg_to_rad(calc.rotation), 0, 0)
            x2, y2 = rotate_point(calc.end_x, calc.end_y, -deg_to_rad(calc.rotation), 0, 0)
            return VectorLine(unit, calc.exposure, calc.width, x1, y1, x2, y2)

    def dilated(self, offset, unit):
        return replace(self, width=self.width + UnitExpression(2*offset, unit))

    def scaled(self, scale):
        return replace(self, 
                       start_x=self.start_x * UnitExpression(scale),
                       start_y=self.start_y * UnitExpression(scale),
                       end_x=self.end_x * UnitExpression(scale),
                       end_y=self.end_y * UnitExpression(scale))


@dataclass(frozen=True, slots=True)
class CenterLine(Primitive):
    code = 21
    exposure : Expression
    width : UnitExpression
    height : UnitExpression
    # center x/y
    x : UnitExpression = 0
    y : UnitExpression = 0
    rotation : Expression = 0

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = gp.rotate_point(calc.x, calc.y, -rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]
            w, h = calc.width, calc.height

            return [ gp.Rectangle(x, y, w, h, rotation, polarity_dark=(bool(calc.exposure) == polarity_dark)) ]

    def substitute_params(self, binding, unit):
        with self.Calculator(self, binding, unit) as calc:
            x1, y1 = rotate_point(calc.x, calc.y-calc.height/2, -deg_to_rad(calc.rotation), 0, 0)
            x2, y2 = rotate_point(calc.x, calc.y+calc.height/2, -deg_to_rad(calc.rotation), 0, 0)
            return VectorLine(unit, calc.exposure, calc.width, x1, y1, x2, y2)

    def dilated(self, offset, unit):
        return replace(self, width=self.width + UnitExpression(2*offset, unit))

    def scaled(self, scale):
        return replace(self, 
                       width=self.width * UnitExpression(scale),
                       height=self.height * UnitExpression(scale),
                       x=self.x * UnitExpression(scale),
                       y=self.y * UnitExpression(scale))
            

@dataclass(frozen=True, slots=True)
class Polygon(Primitive):
    code = 5
    exposure : Expression
    n_vertices : Expression
    # center x/y
    x : UnitExpression
    y : UnitExpression
    diameter : UnitExpression
    rotation : Expression = 0

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = rotate_point(calc.x, calc.y, -rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]
            return [ gp.ArcPoly.from_regular_polygon(calc.x, calc.y, calc.diameter/2, calc.n_vertices, rotation,
                        polarity_dark=(bool(calc.exposure) == polarity_dark)) ]

    def dilated(self, offset, unit):
        return replace(self, diameter=self.diameter + UnitExpression(2*offset, unit))

    def scale(self, scale):
        return replace(self,
                       diameter=self.diameter * UnitExpression(scale),
                       x=self.x * UnitExpression(scale),
                       y=self.y * UnitExpression(scale))
            

@dataclass(frozen=True, slots=True)
class Moire(Primitive):
    """ Deprecated, but still found in some really old gerber files. """
    code = 6
    # center x/y
    x : UnitExpression
    y : UnitExpression
    d_outer : UnitExpression
    line_thickness : UnitExpression
    gap_w : UnitExpression
    num_circles : Expression
    crosshair_thickness : UnitExpression = 0
    crosshair_length : UnitExpression =0
    rotation : Expression = 0

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = rotate_point(calc.x, calc.y, -rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]

            pitch = calc.line_thickness + calc.gap_w
            for i in range(int(round(calc.num_circles))):
                yield gp.Circle(x, y, calc.d_outer/2 - i*pitch, polarity_dark=True)
                yield gp.Circle(x, y, calc.d_inner/2 - i*pitch - calc.line_thickness, polarity_dark=False)

            if math.isclose(calc.crosshair_thickness, 0, abs_tol=1e-6) or\
                    math.isclose(calc.crosshair_length, 0, abs_tol=1e-6):
                return

            yield gp.Rectangle(x, y, crosshair_length, crosshair_thickness, rotation=rotation, polarity_dark=True)
            yield gp.Rectangle(x, y, crosshair_thickness, crosshair_length, rotation=rotation, polarity_dark=True)

    def dilate(self, offset, unit):
        # I'd rather print a warning and produce graphically slightly incorrect output in these few cases here than
        # producing macros that may evaluate to primitives with negative values.
        warnings.warn('Attempted dilation of macro aperture thermal primitive. This is not supported.')

    def scale(self, scale):
        return replace(self, 
                       d_outer=self.d_outer * UnitExpression(scale),
                       d_inner=self.d_inner * UnitExpression(scale),
                       gap_w=self.gap_w * UnitExpression(scale),
                       x=self.x * UnitExpression(scale),
                       y=self.y * UnitExpression(scale))


@dataclass(frozen=True, slots=True)
class Thermal(Primitive):
    code = 7
    exposure : Expression
    # center x/y
    x : UnitExpression
    y : UnitExpression
    d_outer : UnitExpression
    d_inner : UnitExpression
    gap_w : UnitExpression
    rotation : Expression = 0

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = rotate_point(calc.x, calc.y, -rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]

            dark = (bool(calc.exposure) == polarity_dark)

            return [
                    gp.Circle(x, y, calc.d_outer/2, polarity_dark=dark),
                    gp.Circle(x, y, calc.d_inner/2, polarity_dark=not dark),
                    gp.Rectangle(x, y, d_outer, gap_w, rotation=rotation, polarity_dark=not dark),
                    gp.Rectangle(x, y, gap_w, d_outer, rotation=rotation, polarity_dark=not dark),
                    ]

    def dilate(self, offset, unit):
        # I'd rather print a warning and produce graphically slightly incorrect output in these few cases here than
        # producing macros that may evaluate to primitives with negative values.
        warnings.warn('Attempted dilation of macro aperture thermal primitive. This is not supported.')

    def scale(self, scale):
        return replace(self, 
                       d_outer=self.d_outer * UnitExpression(scale),
                       d_inner=self.d_inner * UnitExpression(scale),
                       gap_w=self.gap_w * UnitExpression(scale),
                       x=self.x * UnitExpression(scale),
                       y=self.y * UnitExpression(scale))


@dataclass(frozen=True, slots=True)
class Outline(Primitive):
    code = 4
    exposure : Expression
    length: Expression
    coords: tuple
    rotation: Expression = 0

    def __post_init__(self):
        if self.length is None:
            object.__setattr__(self, 'length', expr(len(self.coords)//2-1))
        else:
            object.__setattr__(self, 'length', expr(self.length))
        object.__setattr__(self, 'rotation', expr(self.rotation))
        object.__setattr__(self, 'exposure', expr(self.exposure))

        if self.length.calculate() != len(self.coords)//2-1:
            raise ValueError('length must exactly equal number of segments, which is the number of points minus one')

        if self.coords[-2:] != self.coords[:2]:
            raise ValueError('Last point must equal first point')

        object.__setattr__(self, 'coords', tuple(
            UnitExpression(coord, self.unit) for coord in self.coords))

    @property
    def points(self):
        for x, y in zip(self.coords[0::2], self.coords[1::2]):
            yield x, y

    @classmethod
    def from_arglist(kls, unit, arglist):
        if len(arglist[2:]) % 2 == 0:
            return kls(unit=unit, exposure=arglist[0], length=arglist[1], coords=arglist[2:], rotation=0)
        else:
            return kls(unit=unit, exposure=arglist[0], length=arglist[1], coords=arglist[2:-1], rotation=arglist[-1])

    def __str__(self):
        return f'<Outline {len(self.coords)} points>'

    def to_gerber(self, register_variable=None, settings=None):
        rotation = self.rotation.optimized()
        coords = ','.join(coord.optimized().to_gerber(register_variable, settings.unit) for coord in self.coords)
        return f'{self.code},{self.exposure.optimized().to_gerber(register_variable)},{len(self.coords)//2-1},{coords},{rotation.to_gerber(register_variable)}'

    def substitute_params(self, binding, unit):
        with self.Calculator(self, binding, unit) as calc:
            rotation = calc.rotation
            coords = [ rotate_point(x.calculate(binding, unit), y.calculate(binding, unit), -deg_to_rad(rotation), 0, 0)
                      for x, y in self.points ]
            coords = [ e for point in coords for e in point ]
            return Outline(unit, calc.exposure, calc.length, coords)

    def parameters(self):
        yield from Primitive.parameters(self)

        for expr in self.coords:
            yield from expr.parameters()

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            bound_coords = [ rotate_point(calc(x), calc(y), -rotation, 0, 0) for x, y in self.points ]
            bound_coords = [ (x+offset[0], y+offset[1]) for x, y in bound_coords ]
            bound_radii = [None] * len(bound_coords)
            return [gp.ArcPoly(bound_coords, bound_radii, polarity_dark=(bool(calc.exposure) == polarity_dark))]

    def dilated(self, offset, unit):
        # we would need a whole polygon offset/clipping library here
        warnings.warn('Attempted dilation of macro aperture outline primitive. This is not supported.')

    def scaled(self, scale):
        return replace(self, coords=tuple(x*scale for x in self.coords))


@dataclass(frozen=True, slots=True)
class Comment:
    code = 0
    comment: str

    def to_gerber(self, register_variable=None, settings=None):
        return f'0 {self.comment}'

    def dilated(self, offset, unit):
        return self

    def scaled(self, scale):
        return self


PRIMITIVE_CLASSES = {
    **{cls.code: cls for cls in [
        Comment,
        Circle,
        VectorLine,
        CenterLine,
        Outline,
        Polygon,
        Moire,
        Thermal,
    ]},
    # alternative codes
    2: VectorLine,
}

