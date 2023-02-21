#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>
# Copyright 2022 Jan Sebastian Götte <gerbonara@jaseg.de>

import warnings
import contextlib
import math

from .expression import Expression, UnitExpression, ConstantExpression, expr

from .. import graphic_primitives as gp


def point_distance(a, b):
    x1, y1 = a
    x2, y2 = b
    return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

def deg_to_rad(a):
    return (a / 180) * math.pi

class Primitive:
    def __init__(self, unit, args):
        self.unit = unit

        if len(args) > len(type(self).__annotations__):
            raise ValueError(f'Too many arguments ({len(args)}) for aperture macro primitive {self.code} ({type(self)})')

        for arg, (name, fieldtype) in zip(args, type(self).__annotations__.items()):
            arg = expr(arg) # convert int/float to Expression object

            if fieldtype == UnitExpression:
                setattr(self, name, UnitExpression(arg, unit))
            else:
                setattr(self, name, arg)

        for name in type(self).__annotations__:
            if not hasattr(self, name):
                raise ValueError(f'Too few arguments ({len(args)}) for aperture macro primitive {self.code} ({type(self)})')

    def to_gerber(self, unit=None):
        return f'{self.code},' + ','.join(
                getattr(self, name).to_gerber(unit) for name in type(self).__annotations__)

    def __str__(self):
        attrs = ','.join(str(getattr(self, name)).strip('<>') for name in type(self).__annotations__)
        return f'<{type(self).__name__} {attrs}>'

    def __repr__(self):
        return str(self)

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


class Circle(Primitive):
    code = 1
    exposure : Expression
    diameter : UnitExpression
    # center x/y
    x : UnitExpression
    y : UnitExpression
    rotation : Expression = None

    def __init__(self, unit, args):
        super().__init__(unit, args)
        if self.rotation is None:
            self.rotation = ConstantExpression(0)

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            x, y = gp.rotate_point(calc.x, calc.y, deg_to_rad(calc.rotation) + rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]
            return [ gp.Circle(x, y, calc.diameter/2, polarity_dark=(bool(calc.exposure) == polarity_dark)) ]

    def dilate(self, offset, unit):
        self.diameter += UnitExpression(offset, unit)

    def scale(self, scale):
        self.x *= UnitExpression(scale)
        self.y *= UnitExpression(scale)
        self.diameter *= UnitExpression(scale)


class VectorLine(Primitive):
    code = 20
    exposure : Expression
    width : UnitExpression
    start_x : UnitExpression
    start_y : UnitExpression
    end_x : UnitExpression
    end_y : UnitExpression
    rotation : Expression

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            center_x = (calc.end_x + calc.start_x) / 2
            center_y = (calc.end_y + calc.start_y) / 2
            delta_x = calc.end_x - calc.start_x
            delta_y = calc.end_y - calc.start_y
            length = point_distance((calc.start_x, calc.start_y), (calc.end_x, calc.end_y))

            center_x, center_y = center_x+offset[0], center_y+offset[1]
            rotation += deg_to_rad(calc.rotation) + math.atan2(delta_y, delta_x)

            return [ gp.Rectangle(center_x, center_y, length, calc.width, rotation=rotation,
                        polarity_dark=(bool(calc.exposure) == polarity_dark)) ]

    def dilate(self, offset, unit):
        self.width += UnitExpression(2*offset, unit)

    def scale(self, scale):
        self.start_x *= UnitExpression(scale)
        self.start_y *= UnitExpression(scale)
        self.end_x *= UnitExpression(scale)
        self.end_y *= UnitExpression(scale)


class CenterLine(Primitive):
    code = 21
    exposure : Expression
    width : UnitExpression
    height : UnitExpression
    # center x/y
    x : UnitExpression
    y : UnitExpression
    rotation : Expression

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = gp.rotate_point(calc.x, calc.y, rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]
            w, h = calc.width, calc.height

            return [ gp.Rectangle(x, y, w, h, rotation, polarity_dark=(bool(calc.exposure) == polarity_dark)) ]

    def dilate(self, offset, unit):
        self.width += UnitExpression(2*offset, unit)

    def scale(self, scale):
        self.width *= UnitExpression(scale)
        self.height *= UnitExpression(scale)
        self.x *= UnitExpression(scale)
        self.y *= UnitExpression(scale)
            

class Polygon(Primitive):
    code = 5
    exposure : Expression
    n_vertices : Expression
    # center x/y
    x : UnitExpression
    y : UnitExpression
    diameter : UnitExpression
    rotation : Expression

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = gp.rotate_point(calc.x, calc.y, rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]
            return [ gp.ArcPoly.from_regular_polygon(calc.x, calc.y, calc.diameter/2, calc.n_vertices, rotation,
                        polarity_dark=(bool(calc.exposure) == polarity_dark)) ]

    def dilate(self, offset, unit):
        self.diameter += UnitExpression(2*offset, unit)

    def scale(self, scale):
        self.diameter *= UnitExpression(scale)
        self.x *= UnitExpression(scale)
        self.y *= UnitExpression(scale)
            

class Thermal(Primitive):
    code = 7
    exposure : Expression
    # center x/y
    x : UnitExpression
    y : UnitExpression
    d_outer : UnitExpression
    d_inner : UnitExpression
    gap_w : UnitExpression
    rotation : Expression

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = gp.rotate_point(calc.x, calc.y, rotation, 0, 0)
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
        self.d_outer *= UnitExpression(scale)
        self.d_inner *= UnitExpression(scale)
        self.gap_w *= UnitExpression(scale)
        self.x *= UnitExpression(scale)
        self.y *= UnitExpression(scale)


class Outline(Primitive):
    code = 4

    def __init__(self, unit, args):
        if len(args) < 11:
            raise ValueError(f'Invalid aperture macro outline primitive, not enough parameters ({len(args)}).')
        if len(args) > 5004:
            raise ValueError(f'Invalid aperture macro outline primitive, too many points ({len(args)//2-2}).')

        self.exposure = args.pop(0)

        # length arg must not contain variables (that would not make sense)
        length_arg = args.pop(0).calculate()

        if length_arg != len(args)//2-1:
            raise ValueError(f'Invalid aperture macro outline primitive, given size {length_arg} does not match length of coordinate list({len(args)//2-1}).')

        if len(args) % 2 == 1:
            self.rotation = args.pop()
        else:
            self.rotation = ConstantExpression(0.0)

        if args[0] != args[-2] or args[1] != args[-1]:
            raise ValueError(f'Invalid aperture macro outline primitive, polygon is not closed {args[2:4], args[-3:-1]}')

        self.coords = [(UnitExpression(x, unit), UnitExpression(y, unit)) for x, y in zip(args[0::2], args[1::2])]

    def __str__(self):
        return f'<Outline {len(self.coords)} points>'

    def to_gerber(self, unit=None):
        coords = ','.join(coord.to_gerber(unit) for xy in self.coords for coord in xy)
        return f'{self.code},{self.exposure.to_gerber()},{len(self.coords)-1},{coords},{self.rotation.to_gerber()}'

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None, polarity_dark=True):
        with self.Calculator(self, variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            bound_coords = [ gp.rotate_point(calc(x), calc(y), rotation, 0, 0) for x, y in self.coords ]
            bound_coords = [ (x+offset[0], y+offset[1]) for x, y in bound_coords ]
            bound_radii = [None] * len(bound_coords)
            return [gp.ArcPoly(bound_coords, bound_radii, polarity_dark=(bool(calc.exposure) == polarity_dark))]

    def dilate(self, offset, unit):
        # we would need a whole polygon offset/clipping library here
        warnings.warn('Attempted dilation of macro aperture outline primitive. This is not supported.')

    def scale(self, scale):
        self.coords = [(x*UnitExpression(scale), y*UnitExpression(scale)) for x, y in self.coords]


class Comment:
    code = 0

    def __init__(self, comment):
        self.comment = comment

    def to_gerber(self, unit=None):
        return f'0 {self.comment}'

    def scale(self, scale):
        pass

PRIMITIVE_CLASSES = {
    **{cls.code: cls for cls in [
        Comment,
        Circle,
        VectorLine,
        CenterLine,
        Outline,
        Polygon,
        Thermal,
    ]},
    # alternative codes
    2: VectorLine,
}

