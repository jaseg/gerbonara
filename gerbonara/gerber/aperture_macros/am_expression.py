#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Götte <gerbonara@jaseg.de>

import operator
import re

class Expression(object):
    @property
    def value(self):
        return self

    def optimized(self):
        return self


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
        return f'<{str(self.expr)[1:-1]} {self.unit}>'

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

    def __str__(self):
        return f'<{self._value}>'

    
class VariableExpression(Expression):
    def __init__(self, number):
        self.number = number

    def optimized(variable_binding={}):
        if self.number in variable_binding:
            return ConstantExpression(variable_binding[self.number])
        return self

    def __eq__(self, other):
        return type(self) == type(other) and \
                self.number == other.number

    def to_gerber(self, _unit=None):
        return f'${self.number}'

    def __str__(self):
        return f'<@{self.number}>'


class OperatorExpression(Expression):
    def __init__(self, op, l, r):
        super(OperatorExpression, self).__init__(Expression.OPERATOR)
        self.op = op
        self.l = ConstantExpression(l) if isinstance(l, (int, float)) else l
        self.r = ConstantExpression(r) if isinstance(r, (int, float)) else r

    def __eq__(self, other):
        return type(self) == type(other) and \
                self.op == other.op and \
                self.lvalue == other.lvalue and \
                self.rvalue == other.rvalue

    def optimized(self, variable_binding={}):
        l = self.lvalue.optimized(variable_binding)
        r = self.rvalue.optimized(variable_binding)
        
        if self.op in (operator.add, operator.mul):
            if hash(r) < hash(l):
                l, r = r, l

        if isinstance(l, ConstantExpression) and isinstance(r, ConstantExpression):
            return ConstantExpression(self.op(float(r), float(l)))

        return OperatorExpression(self.op, l, r)
        
    def to_gerber(self, unit=None):
        lval = self.lvalue.to_gerber(unit)
        rval = self.rvalue.to_gerber(unit)
        op = {OperatorExpression.ADD: '+',
              OperatorExpression.SUB: '-',
              OperatorExpression.MUL: 'x',
              OperatorExpression.DIV: '/'} [self.op]
        return f'({lval}{op}{rval})'

    def __str__(self):
        op = {operator.add: '+', operator.sub: '-', operator.mul: '*', operator.truediv: '/'}[self.op]
        return f'<{str(self.lvalue)[1:-1]} {op} {str(self.rvalue)[1:-1]}>'

operator_map = {
        '+': operator.add,
        '-': operator.sub,
        'x': operator.mul,
        'X': operator.mul,
        '/': operator.truediv,
    }

precedence_map = {
        operator.add : 0,
        operator.sub : 0,
        operator.mul : 1,
        operator.truediv : 1,
    }

def _parse_expression(expr_str):
    output_stack = []
    operator_stack = []

    drop_unary = lambda s: (s[0] == '-', s[1:] if s[0] in '-+' else s)
    negate = lambda expr: OperatorExpression(operator.sub, ConstantExpression(0), expr)

    # See http://faculty.cs.niu.edu/~hutchins/csci241/eval.htm
    # We handle the unary +/- operators by including them into variable/number/parenthesis tokens.
    for variable, number, operator, parenthesis in re.findall(r'([-+]?\$[0-9]+)|([-+]?[0-9]+)|([-+]?\(|\))|([-+xX/])', expr_str):
        
        if variable:
            is_negative, variable = drop_unary(variable)
            var_ex = VariableExpression(int(variable[1:]))
            output_stack.append(negate(var_ex) if is_negative else var_ex)


def _parse_expression(expr_str):
    output_stack = []
    operator_stack = []

    drop_unary = lambda s: (s[0] == '-', s[1:] if s[0] in '-+' else s)
    negate = lambda expr: OperatorExpression(operator.sub, ConstantExpression(0), expr)

    # See http://faculty.cs.niu.edu/~hutchins/csci241/eval.htm
    # We handle the unary +/- operators by including them into variable/number/parenthesis tokens.
    for variable, number, operator, parenthesis in re.findall(r'([-+xX/])|([-+]?\$[0-9]+)|([-+]?[0-9]+\.?[0-9]*)|([()])', expr_str):
        
        if variable:
            is_negative, variable = drop_unary(variable)
            var_ex = VariableExpression(int(variable[1:]))
            output_stack.append(negate(var_ex) if is_negative else var_ex)

        elif number:
            output_stack.append(ConstantExpression(float(number)))

        elif parenthesis[-1] == '(': # be careful, we might have a leading unary +/- here!
            is_negative, parenthesis = drop_unary(parenthesis)
            if is_negative:
                operator_stack.push('-')
            operator_stack.push('(')

        elif parenthesis == ')': # here we cannot have a leading unary +/-
            if not operator_stack:
                raise SyntaxError('Unbalanced parenthesis in aperture macro expression')

            while operator_stack and not operator_stack[-1] == '(':
                op = operator_stack.pop()
                l, r = output_stack.pop(), output_stack.pop()
                output_stack.append(OperatorExpression(op, l, r))

            assert output_stack.pop() == '('
            if output_stack[-1] == '-':
                output_stack.append(negate(output_stack.pop()))

        elif operator:
            operator = operator_map[operator]

            if not operator_stack or operator_stack[-1] == '(':
                operator_stack.push(operator)

            else:
                while operator_stack and operator_stack[-1] != '(' and\
                        precedence_map[operator] <= precedence_map[operator_stack[-1]]:
                    output_stack.append(OperatorExpression(operator_stack.pop(), output_stack.pop(), output_stack.pop()))
                operator_stack.push(operator)

    for operator in reversed(operator_stack):
        if operator == '(':
            raise SyntaxError('Unbalanced parenthesis in aperture macro expression')

        output_stack.append(OperatorExpression(operator_stack.pop(), output_stack.pop(), output_stack.pop()))
    print(output_stack, operator_stack)

    if len(output_stack) != 1:
        raise SyntaxError('Invalid aperture macro expression')

    return output_stack[0]

def parse_macro(macro, unit):
    blocks = re.sub(r'\s', '', macro).split('*')
    variables = {}
    for block in blocks:
        block = block.strip()
        if block[0] == '$': # variable definition
            name, expr = block.partition('=')
            variables[int(name[1:])] = _parse_expression(expr)
        else: # primitive
            primitive, args = block.split(',')
            yield PRIMITIVE_CLASSES[int(primitive)](unit=unit, args=list(map(_parse_expression, args)))

if __name__ == '__main__':
    import sys
    for line in sys.stdin:
        print(_parse_expression(line.strip()))
