#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>
# Copyright 2022 Jan Götte <gerbonara@jaseg.de>

import contextlib
import math

from expression import Expression, UnitExpression, ConstantExpression, expr

from .. import graphic_primitivese as gp


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
        return self.code + ',' + ','.join(
                getattr(self, name).to_gerber(unit) for name in type(self).__annotations__) + '*'

    def __str__(self):
        attrs = ','.join(str(getattr(self, name)).strip('<>') for name in type(self).__annotations__)
        return f'<{type(self).__name__} {attrs}>'

    @contextlib.contextmanager
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
    rotation : Expression = ConstantExpression(0.0)

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None):
        with self.Calculator(variable_binding, unit) as calc:
            x, y = gp.rotate_point(calc.x, calc.y, deg_to_rad(calc.rotation) + rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]
            return [ gp.Circle(x, y, calc.r, polarity_dark=bool(calc.exposure)) ]

class VectorLine(Primitive):
    code = 20
    exposure : Expression
    width : UnitExpression
    start_x : UnitExpression
    start_y : UnitExpression
    end_x : UnitExpression
    end_y : UnitExpression
    rotation : Expression

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None):
        with self.Calculator(variable_binding, unit) as calc:
            center_x = (calc.end_x + calc.start_x) / 2
            center_y = (calc.end_y + calc.start_y) / 2
            delta_x = calc.end_x - calc.start_x
            delta_y = calc.end_y - calc.start_y
            length = point_distance((calc.start_x, calc.start_y), (calc.end_x, calc.end_y))

            center_x, center_y = center_x+offset[0], center_y+offset[1]
            rotation += deg_to_rad(calc.rotation) + math.atan2(delta_y, delta_x)

            return [ gp.Rectangle(center_x, center_y, length, calc.width, rotation=rotation,
                        polarity_dark=bool(calc.exposure)) ]


class CenterLine(Primitive):
    code = 21
    exposure : Expression
    width : UnitExpression
    height : UnitExpression
    # center x/y
    x : UnitExpression
    y : UnitExpression
    rotation : Expression

    def to_graphic_primitives(self, variable_binding={}, unit=None):
        with self.Calculator(variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = gp.rotate_point(calc.x, calc.y, rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]
            w, h = calc.width, calc.height

            return [ gp.Rectangle(x, y, w, h, rotation, polarity_dark=bool(calc.exposure)) ]
            

class Polygon(Primitive):
    code = 5
    exposure : Expression
    n_vertices : Expression
    # center x/y
    x : UnitExpression
    y : UnitExpression
    diameter : UnitExpression
    rotation : Expression

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None):
        with self.Calculator(variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = gp.rotate_point(calc.x, calc.y, rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]
            return [ gp.RegularPolygon(calc.x, calc.y, calc.diameter/2, calc.n_vertices, rotation,
                        polarity_dark=bool(calc.exposure)) ]


class Thermal(Primitive):
    code = 7
    # center x/y
    x : UnitExpression
    y : UnitExpression
    d_outer : UnitExpression
    d_inner : UnitExpression
    gap_w : UnitExpression
    rotation : Expression

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None):
        with self.Calculator(variable_binding, unit) as calc:
            rotation += deg_to_rad(calc.rotation)
            x, y = gp.rotate_point(calc.x, calc.y, rotation, 0, 0)
            x, y = x+offset[0], y+offset[1]

            dark = bool(calc.exposure)

            return [
                    gp.Circle(x, y, calc.d_outer/2, polarity_dark=dark),
                    gp.Circle(x, y, calc.d_inner/2, polarity_dark=not dark),
                    gp.Rectangle(x, y, d_outer, gap_w, rotation=rotation, polarity_dark=not dark),
                    gp.Rectangle(x, y, gap_w, d_outer, rotation=rotation, polarity_dark=not dark),
                    ]


class Outline(Primitive):
    code = 4

    def __init__(self, unit, args):
        if len(args) < 11:
            raise ValueError(f'Invalid aperture macro outline primitive, not enough parameters ({len(args)}).')
        if len(args) > 5004:
            raise ValueError(f'Invalid aperture macro outline primitive, too many points ({len(args)//2-2}).')

        self.exposure = args[0]

        # length arg must not contain variables (that would not make sense)
        length_arg = args[1].calculate()

        if length_arg != len(args)//2 - 2:
            raise ValueError(f'Invalid aperture macro outline primitive, given size does not match length of coordinate list({len(args)}).')

        if len(args) % 1 != 1:
            self.rotation = args.pop()
        else:
            self.rotation = ConstantExpression(0.0)

        if args[2] != args[-2] or args[3] != args[-1]:
            raise ValueError(f'Invalid aperture macro outline primitive, polygon is not closed {args[2:4], args[-3:-1]}')

        self.coords = [(UnitExpression(x, unit), UnitExpression(y, unit)) for x, y in zip(args[1::2], args[2::2])]

    def to_gerber(self, unit=None):
        coords = ','.join(coord.to_gerber(unit) for coord in self.coords)
        return f'{self.code},{self.exposure.to_gerber()},{len(self.coords)//2-1},{coords},{self.rotation.to_gerber()}'

    def to_graphic_primitives(self, offset, rotation, variable_binding={}, unit=None):
        with self.Calculator(variable_binding, unit) as calc:
            bound_coords = [ (calc(x)+offset[0], calc(y)+offset[1]) for x, y in self.coords ]
            bound_radii = [None] * len(bound_coords)

            rotation += deg_to_rad(calc.rotation)
            bound_coords = [ rotate_point(*p, rotation, 0, 0) for p in bound_coords ]

            return gp.ArcPoly(bound_coords, bound_radii, polarity_dark=calc.exposure)


class Comment:
    def __init__(self, comment):
        self.comment = comment

    def to_gerber(self, unit=None):
        return f'0 {self.comment}'

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
    2: VectorLinePrimitive,
}
