#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Sebastian Götte <gerbonara@jaseg.de>

from dataclasses import dataclass, field, replace
import operator
import re
import ast
import copy
import warnings
import math

from . import primitive as ap
from .expression import *
from ..utils import MM

# we make our own here instead of using math.degrees to make sure this works with expressions, too.
def rad_to_deg(x):
    return (x / math.pi) * 180

def _map_expression(node, variables={}, parameters=set()):
    if isinstance(node, ast.Constant):
        return ConstantExpression(node.value)

    elif isinstance(node, ast.BinOp):
        op_map = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
        return OperatorExpression(op_map[type(node.op)],
                                  _map_expression(node.left, variables, parameters),
                                  _map_expression(node.right, variables, parameters))

    elif isinstance(node, ast.UnaryOp):
        if type(node.op) == ast.UAdd:
            return _map_expression(node.operand, variables, parameters)
        else:
            return NegatedExpression(_map_expression(node.operand, variables, parameters))

    elif isinstance(node, ast.Name):
        num = int(node.id[3:]) # node.id has format var[0-9]+
        if num in variables:
            return VariableExpression(variables[num])
        else:
            parameters.add(num)
            return ParameterExpression(num)

    else:
        raise SyntaxError('Invalid aperture macro expression')

def _parse_expression(expr, variables, parameters):
    expr = expr.lower().replace('x', '*')
    expr = re.sub(r'\$([0-9]+)', r'var\1', expr)
    try:
        parsed = ast.parse(expr, mode='eval').body
    except SyntaxError as e:
        raise SyntaxError('Invalid aperture macro expression') from e
    return _map_expression(parsed, variables, parameters)

@dataclass(frozen=True, slots=True)
class ApertureMacro:
    name: str = field(default=None, hash=False, compare=False)
    num_parameters: int = 0
    primitives: tuple = ()
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
        parameters = set()
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
                try:
                    name, _, expr = block.partition('=')
                    number = int(name[1:])
                    if number in variables:
                        warnings.warn(f'Re-definition of aperture macro variable ${number} inside aperture macro "{macro_name}". Previous definition of ${number} was ${variables[number]}.')
                    variables[number] = _parse_expression(expr, variables, parameters)
                except Exception as e:
                    raise SyntaxError(f'Error parsing variable definition {block!r}') from e

            else: # primitive
                primitive, *args = block.split(',')
                args = [ _parse_expression(arg, variables, parameters) for arg in args ]
                try:
                    primitives.append(ap.PRIMITIVE_CLASSES[int(primitive)].from_arglist(unit, args))
                except KeyError as e:
                    raise SyntaxError(f'Unknown aperture macro primitive code {int(primitive)}')

        return kls(macro_name, max(parameters, default=0), tuple(primitives), tuple(comments))

    def __str__(self):
        return f'<Aperture macro {self.name}, primitives {self.primitives}>'

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

    def substitute_params(self, params, unit=None, macro_name=None):
        params = dict(enumerate(params, start=1))
        return replace(self,
                       num_parameters=0,
                       name=macro_name,
                       primitives=tuple(p.substitute_params(params, unit) for p in self.primitives),
                       comments=(f'Fully substituted instance of {self.name} macro',
                                 f'Original parameters: {"X".join(map(str, params.values())) if params else "none"}'))

    def to_gerber(self, settings):
        """ Serialize this macro's content (without the name) into Gerber using the given file unit """
        comments = [ f'0 {c.replace("*", "_").replace("%", "_")}' for c in self.comments ]

        subexpression_variables = {}
        def register_variable(expr):
            expr_str = expr.to_gerber(register_variable, settings.unit)
            if expr_str not in subexpression_variables:
                subexpression_variables[expr_str] = self.num_parameters + 1 + len(subexpression_variables)
            return subexpression_variables[expr_str]

        primitive_defs = [prim.to_gerber(register_variable, settings) for prim in self.primitives]
        variable_defs = [f'${num}={expr_str}' for expr_str, num in subexpression_variables.items()]
        return '*\n'.join(comments + variable_defs + primitive_defs)

    def to_graphic_primitives(self, offset, rotation, parameters : [float], unit=None, polarity_dark=True):
        parameters = dict(enumerate(parameters, start=1))
        for primitive in self.primitives:
            yield from primitive.to_graphic_primitives(offset, rotation, parameters, unit, polarity_dark)

    def rotated(self, angle):
        # aperture macro primitives use degree counter-clockwise, our API uses radians clockwise
        return replace(self, primitives=tuple(
            replace(primitive, rotation=primitive.rotation - rad_to_deg(angle)) for primitive in self.primitives))

    def scaled(self, scale):
        return replace(self, primitives=tuple(
            primitive.scaled(scale) for primitive in self.primitives))


var = ParameterExpression
deg_per_rad = 180 / math.pi

class GenericMacros:

    _generic_hole = lambda n: (ap.Circle('mm', 0, var(n), 0, 0),)

    # NOTE: All generic macros have rotation values specified in **clockwise radians** like the rest of the user-facing
    # API.
    circle = ApertureMacro('GNC', 4, (
        ap.Circle('mm', 1, var(1), 0, 0, var(4) * -deg_per_rad),
        *_generic_hole(2)))

    rect = ApertureMacro('GNR', 5, (
        ap.CenterLine('mm', 1, var(1), var(2), 0, 0, var(5) * -deg_per_rad),
        *_generic_hole(3)))

    # params: width, height, corner radius, *hole, rotation
    rounded_rect = ApertureMacro('GRR', 6, (
        ap.CenterLine('mm', 1, var(1)-2*var(3), var(2), 0, 0, var(6) * -deg_per_rad),
        ap.CenterLine('mm', 1, var(1), var(2)-2*var(3), 0, 0, var(6) * -deg_per_rad),
        ap.Circle('mm', 1, var(3)*2, +(var(1)/2-var(3)), +(var(2)/2-var(3)), var(6) * -deg_per_rad),
        ap.Circle('mm', 1, var(3)*2, +(var(1)/2-var(3)), -(var(2)/2-var(3)), var(6) * -deg_per_rad),
        ap.Circle('mm', 1, var(3)*2, -(var(1)/2-var(3)), +(var(2)/2-var(3)), var(6) * -deg_per_rad),
        ap.Circle('mm', 1, var(3)*2, -(var(1)/2-var(3)), -(var(2)/2-var(3)), var(6) * -deg_per_rad),
        *_generic_hole(4)))

    # params: width, height, length difference between narrow side (top) and wide side (bottom), *hole, rotation
    isosceles_trapezoid = ApertureMacro('GTR', 6, (
        ap.Outline('mm', 1, 4,
                          (var(1)/-2,            var(2)/-2,
                          var(1)/-2+var(3)/2,   var(2)/2,
                          var(1)/2-var(3)/2,    var(2)/2,
                          var(1)/2,             var(2)/-2,
                          var(1)/-2,            var(2)/-2,),
                          var(6) * -deg_per_rad),
        *_generic_hole(4)))

    # params: width, height, length difference between narrow side (top) and wide side (bottom), margin, *hole, rotation
    rounded_isosceles_trapezoid = ApertureMacro('GRTR', 7, (
        ap.Outline('mm', 1, 4,
                          (var(1)/-2,            var(2)/-2,
                          var(1)/-2+var(3)/2,   var(2)/2,
                          var(1)/2-var(3)/2,    var(2)/2,
                          var(1)/2,             var(2)/-2,
                          var(1)/-2,            var(2)/-2,),
                          var(7) * -deg_per_rad),
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
    obround = ApertureMacro('GNO', 5, (
        ap.CenterLine('mm', 1, var(1)-var(2), var(2), 0, 0, var(5) * -deg_per_rad),
        ap.Circle('mm', 1, var(2), +(var(1)-var(2))/2, 0, var(5) * -deg_per_rad),
        ap.Circle('mm', 1, var(2), -(var(1)-var(2))/2, 0, var(5) * -deg_per_rad),
        *_generic_hole(3) ))

    polygon = ApertureMacro('GNP', 4, (
        ap.Polygon('mm', 1, var(2), 0, 0, var(1), var(3) * -deg_per_rad),
        ap.Circle('mm', 0, var(4), 0, 0)))


if __name__ == '__main__':
    import sys
    #for line in sys.stdin:
        #expr = _parse_expression(line.strip())
        #print(expr, '->', expr.optimized())

    for primitive in parse_macro(sys.stdin.read(), 'mm'):
        print(primitive)

