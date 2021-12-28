#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Götte <gerbonara@jaseg.de>

import operator
import re
import ast
import copy
import math

import primitive as ap
from expression import *

from .. import apertures

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
    def parse_macro(cls, name, macro, unit):
        macro = cls(name)

        blocks = re.sub(r'\s', '', macro).split('*')
        for block in blocks:
            if not (block := block.strip()): # empty block
                continue

            if block[0:1] == '0 ': # comment
                macro.comments.append(Comment(block[2:]))
            
            if block[0] == '$': # variable definition
                name, expr = block.partition('=')
                number = int(name[1:])
                if number in macro.variables:
                    raise SyntaxError(f'Re-definition of aperture macro variable {number} inside macro')
                macro.variables[number] = _parse_expression(expr)

            else: # primitive
                primitive, *args = block.split(',')
                args = [_parse_expression(arg) for arg in args]
                primitive =  ap.PRIMITIVE_CLASSES[int(primitive)](unit=unit, args=args
                macro.primitives.append(primitive)

    @property
    def name(self):
        if self.name is not None:
            return self.name
        else:
            return f'gn_{hash(self)}'

    def __str__(self):
        return f'<Aperture macro, variables {str(self.variables)}, primitives {self.primitives}>'

    def __eq__(self, other):
        return hasattr(other, to_gerber) and self.to_gerber() == other.to_gerber()

    def __hash__(self):
        return hash(self.to_gerber())

    def to_gerber(self, unit=None):
        comments = [ c.to_gerber() for c in self.comments ]
        variable_defs = [ f'${var.to_gerber(unit)}={expr}' for var, expr in self.variables.items() ]
        primitive_defs = [ prim.to_gerber(unit) for prim in self.primitives ]
        return '*\n'.join(comments + variable_defs + primitive_defs)

    def to_graphic_primitives(self, offset, rotation:'radians', parameters : [float], unit=None):
        variables = dict(self.variables)
        for number, value in enumerate(parameters):
            if i in variables:
                raise SyntaxError(f'Re-definition of aperture macro variable {i} through parameter {value}')
            variables[i] = value

        return [ primitive.to_graphic_primitives(offset, rotation, variables, unit) for primitive in self.primitives ]

    def rotated(self, angle):
        copy = copy.deepcopy(self)
        for primitive in copy.primitives:
            primitive.rotation += rad_to_deg(angle)
        return copy


class GenericMacros:
    deg_per_rad = 180 / math.pi
    cons, var = VariableExpression
    _generic_hole = lambda n: [
            ap.Circle(exposure=0, diameter=var(n), x=0, y=0),
            ap.Rectangle(exposure=0, w=var(n), h=var(n+1), x=0, y=0, rotation=var(n+2) * deg_per_rad)]

    circle = ApertureMacro([
        ap.Circle(exposure=1, diameter=var(1), x=0, y=0, rotation=var(4) * deg_per_rad),
        *_generic_hole(2)])

    rect = ApertureMacro([
        ap.Rectangle(exposure=1, w=var(1), h=var(2), x=0, y=0, rotation=var(5) * deg_per_rad),
        *_generic_hole(3) ])

    # w must be larger than h
    obround = ApertureMacro([
        ap.Rectangle(exposure=1, w=var(1), h=var(2), x=0, y=0, rotation=var(5) * deg_per_rad),
        ap.Circle(exposure=1, diameter=var(2), x=+var(1)/2, y=0, rotation=var(5) * deg_per_rad),
        ap.Circle(exposure=1, diameter=var(2), x=-var(1)/2, y=0, rotation=var(5) * deg_per_rad),
        *_generic_hole(3) ])

    polygon = ApertureMacro([
        ap.Polygon(exposure=1, n_vertices=var(2), x=0, y=0, diameter=var(1), rotation=var(3) * deg_per_rad),
        pa.Circle(exposure=0, diameter=var(4), x=0, y=0)])


if __name__ == '__main__':
    import sys
    #for line in sys.stdin:
        #expr = _parse_expression(line.strip())
        #print(expr, '->', expr.optimized())

    for primitive in parse_macro(sys.stdin.read(), 'mm'):
        print(primitive)
