#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Sebastian Götte <gerbonara@jaseg.de>

from dataclasses import dataclass, field, replace
import operator
import re
import ast
import copy
import math

from . import primitive as ap
from .expression import *
from ..utils import MM

# we make our own here instead of using math.degrees to make sure this works with expressions, too.
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

@dataclass(frozen=True, slots=True)
class ApertureMacro:
    name: str = field(default=None, hash=False, compare=False)
    primitives: tuple = ()
    variables: tuple = ()
    comments: tuple = field(default=(), hash=False, compare=False)

    def __post_init__(self):
        if self.name is None or re.match(r'GNX[0-9A-F]{16}', self.name):
            # We can't use field(default_factory=...) here because that factory doesn't get a reference to the instance.
            self._reset_name()

    def _reset_name(self):
        object.__setattr__(self, 'name', f'GNX{hash(self)&0xffffffffffffffff:016X}')

    @classmethod
    def parse_macro(kls, macro_name, body, unit):
        comments = []
        variables = {}
        primitives = []

        blocks = body.split('*')
        for block in blocks:
            if not (block := block.strip()): # empty block
                continue

            if block.startswith('0 '): # comment
                comments.append(block[2:])
                continue
            
            block = re.sub(r'\s', '', block)

            if block[0] == '$': # variable definition
                name, expr = block.partition('=')
                number = int(name[1:])
                if number in variables:
                    raise SyntaxError(f'Re-definition of aperture macro variable {number} inside macro')
                variables[number] = _parse_expression(expr)

            else: # primitive
                primitive, *args = block.split(',')
                args = [ _parse_expression(arg) for arg in args ]
                primitives.append(ap.PRIMITIVE_CLASSES[int(primitive)].from_arglist(unit, args))

        variables = [variables.get(i+1) for i in range(max(variables.keys(), default=0))]
        return kls(macro_name, tuple(primitives), tuple(variables), tuple(comments))

    def __str__(self):
        return f'<Aperture macro {self.name}, variables {str(self.variables)}, primitives {self.primitives}>'

    def __repr__(self):
        return str(self)

    def dilated(self, offset, unit=MM):
        new_primitives = []
        for primitive in self.primitives:
            try:
                if primitive.exposure.calculate():
                    new_primitives += primitive.dilated(offset, unit)
            except IndexError:
                warnings.warn('Cannot dilate aperture macro primitive with exposure value computed from macro variable.')
                pass
        return replace(self, primitives=tuple(new_primitives))

    def to_gerber(self, unit=None):
        """ Serialize this macro's content (without the name) into Gerber using the given file unit """
        comments = [ f'0 {c.replace("*", "_").replace("%", "_")}' for c in self.comments ]
        variable_defs = [ f'${var}={str(expr)[1:-1]}' for var, expr in enumerate(self.variables, start=1) if expr is not None ]
        primitive_defs = [ prim.to_gerber(unit) for prim in self.primitives ]
        return '*\n'.join(comments + variable_defs + primitive_defs)

    def to_graphic_primitives(self, offset, rotation, parameters : [float], unit=None, polarity_dark=True):
        variables = {i: v for i, v in enumerate(self.variables, start=1) if v is not None}
        for number, value in enumerate(parameters, start=1):
            if number in variables:
                raise SyntaxError(f'Re-definition of aperture macro variable {number} through parameter {value}')
            variables[number] = value

        for primitive in self.primitives:
            yield from primitive.to_graphic_primitives(offset, rotation, variables, unit, polarity_dark)

    def rotated(self, angle):
        # aperture macro primitives use degree counter-clockwise, our API uses radians clockwise
        return replace(self, primitives=tuple(
            replace(primitive, rotation=primitive.rotation - rad_to_deg(angle)) for primitive in self.primitives))

    def scaled(self, scale):
        return replace(self, primitives=tuple(
            primitive.scaled(scale) for primitive in self.primitives))


var = VariableExpression
deg_per_rad = 180 / math.pi

class GenericMacros:

    _generic_hole = lambda n: (ap.Circle('mm', 0, var(n), 0, 0),)

    # NOTE: All generic macros have rotation values specified in **clockwise radians** like the rest of the user-facing
    # API.
    circle = ApertureMacro('GNC', (
        ap.Circle('mm', 1, var(1), 0, 0, var(4) * -deg_per_rad),
        *_generic_hole(2)))

    rect = ApertureMacro('GNR', (
        ap.CenterLine('mm', 1, var(1), var(2), 0, 0, var(5) * -deg_per_rad),
        *_generic_hole(3)))

    # params: width, height, corner radius, *hole, rotation
    rounded_rect = ApertureMacro('GRR', (
        ap.CenterLine('mm', 1, var(1)-2*var(3), var(2), 0, 0, var(6) * -deg_per_rad),
        ap.CenterLine('mm', 1, var(1), var(2)-2*var(3), 0, 0, var(6) * -deg_per_rad),
        ap.Circle('mm', 1, var(3)*2, +(var(1)/2-var(3)), +(var(2)/2-var(3)), var(6) * -deg_per_rad),
        ap.Circle('mm', 1, var(3)*2, +(var(1)/2-var(3)), -(var(2)/2-var(3)), var(6) * -deg_per_rad),
        ap.Circle('mm', 1, var(3)*2, -(var(1)/2-var(3)), +(var(2)/2-var(3)), var(6) * -deg_per_rad),
        ap.Circle('mm', 1, var(3)*2, -(var(1)/2-var(3)), -(var(2)/2-var(3)), var(6) * -deg_per_rad),
        *_generic_hole(4)))

    # params: width, height, length difference between narrow side (top) and wide side (bottom), *hole, rotation
    isosceles_trapezoid = ApertureMacro('GTR', (
        ap.Outline('mm', 1, 4,
                          (var(1)/-2,            var(2)/-2,
                          var(1)/-2+var(3)/2,   var(2)/2,
                          var(1)/2-var(3)/2,    var(2)/2,
                          var(1)/2,             var(2)/-2,
                          var(1)/-2,            var(2)/-2,),
                          var(6) * -deg_per_rad),
        *_generic_hole(4)))

    # params: width, height, length difference between narrow side (top) and wide side (bottom), margin, *hole, rotation
    rounded_isosceles_trapezoid = ApertureMacro('GRTR', (
        ap.Outline('mm', 1, 4,
                          (var(1)/-2,            var(2)/-2,
                          var(1)/-2+var(3)/2,   var(2)/2,
                          var(1)/2-var(3)/2,    var(2)/2,
                          var(1)/2,             var(2)/-2,
                          var(1)/-2,            var(2)/-2,),
                          var(6) * -deg_per_rad),
        ap.VectorLine('mm', 1, var(4)*2, 
                          var(1)/-2,            var(2)/-2,
                          var(1)/-2+var(3)/2,   var(2)/2,),
        ap.VectorLine('mm', 1, var(4)*2, 
                          var(1)/-2+var(3)/2,   var(2)/2,
                          var(1)/2-var(3)/2,    var(2)/2,),
        ap.VectorLine('mm', 1, var(4)*2, 
                          var(1)/2-var(3)/2,    var(2)/2,
                          var(1)/2,             var(2)/-2,),
        ap.VectorLine('mm', 1, var(4)*2, 
                          var(1)/2,             var(2)/-2,
                          var(1)/-2,            var(2)/-2,),
        ap.Circle('mm', 1, var(4)*2, 
                          var(1)/-2,            var(2)/-2,),
        ap.Circle('mm', 1, var(4)*2, 
                          var(1)/-2+var(3)/2,   var(2)/2,),
        ap.Circle('mm', 1, var(4)*2, 
                          var(1)/2-var(3)/2,    var(2)/2,),
        ap.Circle('mm', 1, var(4)*2, 
                          var(1)/2,             var(2)/-2,),
        *_generic_hole(5)))

    # w must be larger than h
    # params: width, height, *hole, rotation
    obround = ApertureMacro('GNO', (
        ap.CenterLine('mm', 1, var(1)-var(2), var(2), 0, 0, var(5) * -deg_per_rad),
        ap.Circle('mm', 1, var(2), +(var(1)-var(2))/2, 0, var(5) * -deg_per_rad),
        ap.Circle('mm', 1, var(2), -(var(1)-var(2))/2, 0, var(5) * -deg_per_rad),
        *_generic_hole(3) ))

    polygon = ApertureMacro('GNP', (
        ap.Polygon('mm', 1, var(2), 0, 0, var(1), var(3) * -deg_per_rad),
        ap.Circle('mm', 0, var(4), 0, 0)))


if __name__ == '__main__':
    import sys
    #for line in sys.stdin:
        #expr = _parse_expression(line.strip())
        #print(expr, '->', expr.optimized())

    for primitive in parse_macro(sys.stdin.read(), 'mm'):
        print(primitive)

