#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

from dataclasses import dataclass, fields

from .utils import *
from .am_statements import *
from .am_expression import *
from .am_opcode import OpCode

class Primitive:
    def __init__(self, unit, args):
        self.unit = unit

        if len(args) > len(type(self).__annotations__):
            raise ValueError(f'Too many arguments ({len(args)}) for aperture macro primitive {self.code} ({type(self)})')

        for arg, (name, fieldtype) in zip(args, type(self).__annotations__.items()):
            if fieldtype == UnitExpression:
                setattr(self, name, UnitExpression(arg, unit))
            else:
                setattr(self, name, arg)

        for name, _type in type(self).__annotations__.items():
            if not hasattr(self, name):
                raise ValueError(f'Too few arguments ({len(args)}) for aperture macro primitive {self.code} ({type(self)})')

    def to_gerber(self, unit=None):
        return self.code + ',' + ','.join(
                getattr(self, name).to_gerber(unit) for name, _type in type(self).__annotations__.items()) + '*'

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

    def __init__(self, code, unit, args):
        if len(args) < 11:
            raise ValueError(f'Invalid aperture macro outline primitive, not enough parameters ({len(args)}).')
        if len(args) > 5004:
            raise ValueError(f'Invalid aperture macro outline primitive, too many points ({len(args)//2-2}).')

        self.exposure = args[0]

        if args[1] != len(args)//2 - 2:
            raise ValueError(f'Invalid aperture macro outline primitive, given size does not match length of coordinate list({len(args)}).')

        if len(args) % 1 != 1:
            self.rotation = args.pop()
        else:
            self.rotation = ConstantExpression(0.0)

        if args[2] != args[-2] or args[3] != args[-1]:
            raise ValueError(f'Invalid aperture macro outline primitive, polygon is not closed {args[2:4], args[-3:-1]}')

        self.coords = [UnitExpression(arg, unit) for arg in args[1:]]
    
    def to_gerber(self, unit=None):
        coords = ','.join(coord.to_gerber(unit) for coord in self.coords)
        return f'{self.code},{self.exposure.to_gerber()},{len(self.coords)//2-1},{coords},{self.rotation.to_gerber()}'


class VariableDef(object):
    def __init__(self, number, value):
        self.number = number
        self.value = value

    def to_gerber(self, _unit=None):
        return '$%d=%s*' % (self.number, self.value.to_gerber(settings))

PRIMITIVE_CLASSES = {
    **{cls.code: cls for cls in [
        CommentPrimitive,
        CirclePrimitive,
        VectorLinePrimitive,
        CenterLinePrimitive,
        OutlinePrimitive,
        PolygonPrimitive,
        ThermalPrimitive,
    ],
    # alternative codes
    2: VectorLinePrimitive,
}

def eval_macro(instructions, unit):
    stack = []
    for opcode, argument in instructions:
        if opcode == OpCode.PUSH:
            stack.append(ConstantExpression(argument))

        elif opcode == OpCode.LOAD:
            stack.append(VariableExpression(argument))

        elif opcode == OpCode.STORE:
            yield VariableDef(code, stack.pop())

        elif opcode == OpCode.ADD:
            op1 = stack.pop()
            op2 = stack.pop()
            stack.append(OperatorExpression(OperatorExpression.ADD, op2, op1))

        elif opcode == OpCode.SUB:
            op1 = stack.pop()
            op2 = stack.pop()
            stack.append(OperatorExpression(OperatorExpression.SUB, op2, op1))

        elif opcode == OpCode.MUL:
            op1 = stack.pop()
            op2 = stack.pop()
            stack.append(OperatorExpression(OperatorExpression.MUL, op2, op1))

        elif opcode == OpCode.DIV:
            op1 = stack.pop()
            op2 = stack.pop()
            stack.append(OperatorExpression(OperatorExpression.DIV, op2, op1))

        elif opcode == OpCode.PRIM:
            yield PRIMITIVE_CLASSES[argument](unit=unit, args=stack)
            stack = []

