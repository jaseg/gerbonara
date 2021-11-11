#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Götte <gerbonara@jaseg.de>

import operator
import re
import ast

class Expression(object):
    @property
    def value(self):
        return self

    def optimized(self, variable_binding={}):
        return self

    def __str__(self):
        return f'<{self.to_gerber()}>'

class UnitExpression(Expression):
    def __init__(self, expr, unit):
        self._expr = expr
        self.unit = unit

    def to_gerber(self, unit=None):
        return self.converted(unit).optimized().to_gerber()

    def __eq__(self, other):
        return type(other) == type(self) and \
            self.unit == other.unit and\
            self._expr == other._expr

    def __str__(self):
        return f'<{self.expr.to_gerber()} {self.unit}>'

    def converted(self, unit):
        if unit is None or self.unit == unit:
            return self._expr

        elif unit == 'mm':
            return OperatorExpression.mul(self._expr, MILLIMETERS_PER_INCH)

        elif unit == 'inch':
            return OperatorExpression.div(self._expr, MILLIMETERS_PER_INCH)

        else:
            raise ValueError('invalid unit, must be "inch" or "mm".')

    def calculate(self, variable_binding={}, unit=None):
        expr = self.converted(unit).optimized(variable_binding)
        if not isinstance(expr, ConstantExpression):
            raise IndexError(f'Cannot fully resolve expression due to unresolved variables: {expr} with variables {variable_binding}')


class ConstantExpression(Expression):
    def __init__(self, value):
        self._value = value

    @property
    def value(self):
        return self._value

    def __float__(self):
        return float(self._value)

    def __eq__(self, other):
        return type(self) == type(other) and self._value == other._value

    def to_gerber(self, _unit=None):
        if isinstance(self._value, str):
            return self._value
        return f'{self.value:.6f}'.rstrip('0').rstrip('.')

    
class VariableExpression(Expression):
    def __init__(self, number):
        self.number = number

    def optimized(self, variable_binding={}):
        if self.number in variable_binding:
            return ConstantExpression(variable_binding[self.number])
        return self

    def __eq__(self, other):
        return type(self) == type(other) and \
                self.number == other.number

    def to_gerber(self, _unit=None):
        return f'${self.number}'


class OperatorExpression(Expression):
    def __init__(self, op, l, r):
        self.op = op
        self.l = ConstantExpression(l) if isinstance(l, (int, float)) else l
        self.r = ConstantExpression(r) if isinstance(r, (int, float)) else r

    def __eq__(self, other):
        return type(self) == type(other) and \
                self.op == other.op and \
                self.l == other.l and \
                self.r == other.r

    def optimized(self, variable_binding={}):
        l = self.l.optimized(variable_binding)
        r = self.r.optimized(variable_binding)
        
        if self.op in (operator.add, operator.mul):
            if id(r) < id(l):
                l, r = r, l

        if isinstance(l, ConstantExpression) and isinstance(r, ConstantExpression):
            return ConstantExpression(self.op(float(r), float(l)))

        return OperatorExpression(self.op, l, r)
        
    def to_gerber(self, unit=None):
        lval = self.l.to_gerber(unit)
        rval = self.r.to_gerber(unit)

        if isinstance(self.l, OperatorExpression):
            lval = f'({lval})'
        if isinstance(self.r, OperatorExpression):
            rval = f'({rval})'

        op = {operator.add: '+',
              operator.sub: '-',
              operator.mul: 'x',
              operator.truediv: '/'} [self.op]

        return f'{lval}{op}{rval}'


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

def parse_macro(macro, unit):
    blocks = re.sub(r'\s', '', macro).split('*')
    variables = {}
    for block in blocks:
        block = block.strip()

        if block[0:1] == '0 ': # comment
            continue

        elif block[0] == '$': # variable definition
            name, expr = block.partition('=')
            variables[int(name[1:])] = _parse_expression(expr)

        else: # primitive
            primitive, args = block.split(',')
            yield PRIMITIVE_CLASSES[int(primitive)](unit=unit, args=list(map(_parse_expression, args)))

if __name__ == '__main__':
    import sys
    for line in sys.stdin:
        expr = _parse_expression(line.strip())
        print(expr, '->', expr.optimized())
