#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Sebastian Götte <gerbonara@jaseg.de>

import operator
import re
import ast
import copy
import math

from . import primitive as ap
from .expression import *
from ..utils import MM

def rad_to_deg(x):
    return (x / math.pi) * 180

def _map_expression(node):
    if isinstance(node, ast.Num):
        return ConstantExpression(node.n)

    elif isinstance(node, ast.BinOp):
        op_map = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
        return OperatorExpression(op_map[type(node.op)], _map_expression(node.left), _map_expression(node.right))

    elif isinstance(node, ast.UnaryOp):
        if type(node.op) == ast.UAdd:
            return _map_expression(node.operand)
        else:
            return OperatorExpression(operator.sub, ConstantExpression(0), _map_expression(node.operand))

    elif isinstance(node, ast.Name):
        return VariableExpression(int(node.id[3:])) # node.id has format var[0-9]+

    else:
        raise SyntaxError('Invalid aperture macro expression')

def _parse_expression(expr):
    expr = expr.lower().replace('x', '*')
    expr = re.sub(r'\$([0-9]+)', r'var\1', expr)
    try:
        parsed = ast.parse(expr, mode='eval').body
    except SyntaxError as e:
        raise SyntaxError('Invalid aperture macro expression') from e
    return _map_expression(parsed)

class ApertureMacro:
    def __init__(self, name=None, primitives=None, variables=None):
        self._name = name
        self.comments = []
        self.variables = variables or {}
        self.primitives = primitives or []

    @classmethod
    def parse_macro(cls, name, body, unit):
        macro = cls(name)

        blocks = body.split('*')
        for block in blocks:
            if not (block := block.strip()): # empty block
                continue

            if block.startswith('0 '): # comment
                macro.comments.append(block[2:])
                continue
            
            block = re.sub(r'\s', '', block)

            if block[0] == '$': # variable definition
                name, expr = block.partition('=')
                number = int(name[1:])
                if number in macro.variables:
                    raise SyntaxError(f'Re-definition of aperture macro variable {number} inside macro')
                macro.variables[number] = _parse_expression(expr)

            else: # primitive
                primitive, *args = block.split(',')
                args = [ _parse_expression(arg) for arg in args ]
                primitive = ap.PRIMITIVE_CLASSES[int(primitive)](unit=unit, args=args)
                macro.primitives.append(primitive)

        return macro

    @property
    def name(self):
        if self._name is not None:
            return self._name
        else:
            return f'gn_{hash(self)}'

    @name.setter
    def name(self, name):
        self._name = name

    def __str__(self):
        return f'<Aperture macro {self.name}, variables {str(self.variables)}, primitives {self.primitives}>'

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        return hasattr(other, 'to_gerber') and self.to_gerber() == other.to_gerber()

    def __hash__(self):
        return hash(self.to_gerber())

    def dilated(self, offset, unit=MM):
        dup = copy.deepcopy(self)
        new_primitives = []
        for primitive in dup.primitives:
            try:
                if primitive.exposure.calculate():
                    primitive.dilate(offset, unit)
                    new_primitives.append(primitive)
            except IndexError:
                warnings.warn('Cannot dilate aperture macro primitive with exposure value computed from macro variable.')
                pass
        dup.primitives = new_primitives
        return dup

    def to_gerber(self, unit=None):
        comments = [ c.to_gerber() for c in self.comments ]
        variable_defs = [ f'${var.to_gerber(unit)}={expr}' for var, expr in self.variables.items() ]
        primitive_defs = [ prim.to_gerber(unit) for prim in self.primitives ]
        return '*\n'.join(comments + variable_defs + primitive_defs)

    def to_graphic_primitives(self, offset, rotation, parameters : [float], unit=None, polarity_dark=True):
        variables = dict(self.variables)
        for number, value in enumerate(parameters, start=1):
            if number in variables:
                raise SyntaxError(f'Re-definition of aperture macro variable {i} through parameter {value}')
            variables[number] = value

        for primitive in self.primitives:
            yield from primitive.to_graphic_primitives(offset, rotation, variables, unit, polarity_dark)

    def rotated(self, angle):
        dup = copy.deepcopy(self)
        for primitive in dup.primitives:
            # aperture macro primitives use degree counter-clockwise, our API uses radians clockwise
            primitive.rotation -= rad_to_deg(angle)
        return dup

    def scaled(self, scale):
        dup = copy.deepcopy(self)
        for primitive in dup.primitives:
            primitive.scale(scale)
        return dup


var = VariableExpression
deg_per_rad = 180 / math.pi

class GenericMacros:

    _generic_hole = lambda n: [
            ap.Circle('mm', [0, var(n), 0, 0]),
            ap.CenterLine('mm', [0, var(n), var(n+1), 0, 0, var(n+2) * -deg_per_rad])]

    # NOTE: All generic macros have rotation values specified in **clockwise radians** like the rest of the user-facing
    # API.
    circle = ApertureMacro('GNC', [
        ap.Circle('mm', [1, var(1), 0, 0, var(4) * -deg_per_rad]),
        *_generic_hole(2)])

    rect = ApertureMacro('GNR', [
        ap.CenterLine('mm', [1, var(1), var(2), 0, 0, var(5) * -deg_per_rad]),
        *_generic_hole(3)])

    # params: width, height, corner radius, *hole, rotation
    rounded_rect = ApertureMacro('GRR', [
        ap.CenterLine('mm', [1, var(1)-2*var(3), var(2), 0, 0, var(6) * -deg_per_rad]),
        ap.CenterLine('mm', [1, var(1), var(2)-2*var(3), 0, 0, var(6) * -deg_per_rad]),
        ap.Circle('mm', [1, var(3)*2, +(var(1)/2-var(3)), +(var(2)/2-var(3)), 0]),
        ap.Circle('mm', [1, var(3)*2, +(var(1)/2-var(3)), -(var(2)/2-var(3)), 0]),
        ap.Circle('mm', [1, var(3)*2, -(var(1)/2-var(3)), +(var(2)/2-var(3)), 0]),
        ap.Circle('mm', [1, var(3)*2, -(var(1)/2-var(3)), -(var(2)/2-var(3)), 0]),
        *_generic_hole(4)])

    # w must be larger than h
    obround = ApertureMacro('GNO', [
        ap.CenterLine('mm', [1, var(1), var(2), 0, 0, var(5) * -deg_per_rad]),
        ap.Circle('mm', [1, var(2), +var(1)/2, 0, var(5) * -deg_per_rad]),
        ap.Circle('mm', [1, var(2), -var(1)/2, 0, var(5) * -deg_per_rad]),
        *_generic_hole(3) ])

    polygon = ApertureMacro('GNP', [
        ap.Polygon('mm', [1, var(2), 0, 0, var(1), var(3) * -deg_per_rad]),
        ap.Circle('mm', [0, var(4), 0, 0])])


if __name__ == '__main__':
    import sys
    #for line in sys.stdin:
        #expr = _parse_expression(line.strip())
        #print(expr, '->', expr.optimized())

    for primitive in parse_macro(sys.stdin.read(), 'mm'):
        print(primitive)

