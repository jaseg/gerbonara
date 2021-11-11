#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

from dataclasses import dataclass, fields
from expression import Expression, UnitExpression, ConstantExpression

class Primitive:
    def __init__(self, unit, args, is_abstract):
        self.unit = unit
        self.is_abstract = is_abstract

        if len(args) > len(type(self).__annotations__):
            raise ValueError(f'Too many arguments ({len(args)}) for aperture macro primitive {self.code} ({type(self)})')

        for arg, (name, fieldtype) in zip(args, type(self).__annotations__.items()):
            if is_abstract:
                if fieldtype == UnitExpression:
                    setattr(self, name, UnitExpression(arg, unit))
                else:
                    setattr(self, name, arg)
            else:
                setattr(self, name, arg)

        for name in type(self).__annotations__:
            if not hasattr(self, name):
                raise ValueError(f'Too few arguments ({len(args)}) for aperture macro primitive {self.code} ({type(self)})')

    def to_gerber(self, unit=None):
        if not self.is_abstract:
            raise TypeError(f"Something went wrong, tried to gerber'ize bound aperture macro primitive {self}")
        return self.code + ',' + ','.join(
                getattr(self, name).to_gerber(unit) for name in type(self).__annotations__) + '*'

    def __str__(self):
        attrs = ','.join(str(getattr(self, name)).strip('<>') for name in type(self).__annotations__)
        return f'<{type(self).__name__} {attrs}>'

    def bind(self, variable_binding={}):
        if not self.is_abstract:
            raise TypeError('{type(self).__name__} object is already instantiated, cannot bind again.')
        # Return instance of the same class, but replace all attributes by their actual numeric values
        return type(self)(unit=self.unit, is_abstract=False, args=[
            getattr(self, name).calculate(variable_binding) for name in type(self).__annotations__
        ])

class CommentPrimitive(Primitive):
    code = 0
    comment : str

class CirclePrimitive(Primitive):
    code = 1
    exposure : Expression
    diameter : UnitExpression
    center_x : UnitExpression
    center_y : UnitExpression
    rotation : Expression = ConstantExpression(0.0)

class VectorLinePrimitive(Primitive):
    code = 20
    exposure : Expression
    width : UnitExpression
    start_x : UnitExpression
    start_y : UnitExpression
    end_x : UnitExpression
    end_y : UnitExpression
    rotation : Expression

class CenterLinePrimitive(Primitive):
    code = 21
    exposure : Expression
    width : UnitExpression
    height : UnitExpression
    x : UnitExpression
    y : UnitExpression
    rotation : Expression


class PolygonPrimitive(Primitive):
    code = 5
    exposure : Expression
    n_vertices : Expression
    center_x : UnitExpression
    center_y : UnitExpression
    diameter : UnitExpression
    rotation : Expression


class ThermalPrimitive(Primitive):
    code = 7
    center_x : UnitExpression
    center_y : UnitExpression
    d_outer : UnitExpression
    d_inner : UnitExpression
    gap_w : UnitExpression
    rotation : Expression


class OutlinePrimitive(Primitive):
    code = 4

    def __init__(self, unit, args, is_abstract):
        if len(args) < 11:
            raise ValueError(f'Invalid aperture macro outline primitive, not enough parameters ({len(args)}).')
        if len(args) > 5004:
            raise ValueError(f'Invalid aperture macro outline primitive, too many points ({len(args)//2-2}).')

        self.exposure = args[0]

        if is_abstract:
            # length arg must not contain variabels (that would not make sense)
            length_arg = args[1].calculate()

            if length_arg != len(args)//2 - 2:
                raise ValueError(f'Invalid aperture macro outline primitive, given size does not match length of coordinate list({len(args)}).')

            if len(args) % 1 != 1:
                self.rotation = args.pop()
            else:
                self.rotation = ConstantExpression(0.0)

            if args[2] != args[-2] or args[3] != args[-1]:
                raise ValueError(f'Invalid aperture macro outline primitive, polygon is not closed {args[2:4], args[-3:-1]}')

            self.coords = [UnitExpression(arg, unit) for arg in args[1:]]

        else:
            if len(args) % 1 != 1:
                self.rotation = args.pop()
            else:
                self.rotation = 0

            self.coords = args[1:]
    
    def to_gerber(self, unit=None):
        if not self.is_abstract:
            raise TypeError(f"Something went wrong, tried to gerber'ize bound aperture macro primitive {self}")
        coords = ','.join(coord.to_gerber(unit) for coord in self.coords)
        return f'{self.code},{self.exposure.to_gerber()},{len(self.coords)//2-1},{coords},{self.rotation.to_gerber()}'

    def bind(self, variable_binding={}):
        if not self.is_abstract:
            raise TypeError('{type(self).__name__} object is already instantiated, cannot bind again.')

        return OutlinePrimitive(self.unit, is_abstract=False, args=[None, *self.coords, self.rotation])

class Comment:
    def __init__(self, comment):
        self.comment = comment

    def to_gerber(self, unit=None):
        return f'0 {self.comment}'

PRIMITIVE_CLASSES = {
    **{cls.code: cls for cls in [
        CommentPrimitive,
        CirclePrimitive,
        VectorLinePrimitive,
        CenterLinePrimitive,
        OutlinePrimitive,
        PolygonPrimitive,
        ThermalPrimitive,
    ]},
    # alternative codes
    2: VectorLinePrimitive,
}

