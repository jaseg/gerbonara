#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Sebastian Götte <gerbonara@jaseg.de>

import operator
import re
import ast

from ..utils import MM, Inch, MILLIMETERS_PER_INCH


def expr(obj):
    return obj if isinstance(obj, Expression) else ConstantExpression(obj)


class Expression:
    def optimized(self, variable_binding={}):
        return self

    def __str__(self):
        return f'<{self.to_gerber()}>'

    def __repr__(self):
        return f'<E {self.to_gerber()}>'

    def converted(self, unit):
        return self

    def calculate(self, variable_binding={}, unit=None):
        expr = self.converted(unit).optimized(variable_binding)
        if not isinstance(expr, ConstantExpression):
            raise IndexError(f'Cannot fully resolve expression due to unresolved variables: {expr} with variables {variable_binding}')
        return expr.value

    def __add__(self, other):
        return OperatorExpression(operator.add, self, expr(other)).optimized()

    def __radd__(self, other):
        return expr(other) + self

    def __sub__(self, other):
        return OperatorExpression(operator.sub, self, expr(other)).optimized()

    def __rsub__(self, other):
        return expr(other) - self

    def __mul__(self, other):
        return OperatorExpression(operator.mul, self, expr(other)).optimized()

    def __rmul__(self, other):
        return expr(other) * self

    def __truediv__(self, other):
        return OperatorExpression(operator.truediv, self, expr(other)).optimized()

    def __rtruediv__(self, other):
        return expr(other) / self

    def __neg__(self):
        return 0 - self

    def __pos__(self):
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
        return f'<{self._expr.to_gerber()} {self.unit}>'

    def __repr__(self):
        return f'<UE {self._expr.to_gerber()} {self.unit}>'

    def converted(self, unit):
        if self.unit is None or unit is None or self.unit == unit:
            return self._expr

        elif MM == unit:
            return self._expr * MILLIMETERS_PER_INCH

        elif Inch == unit:
            return self._expr / MILLIMETERS_PER_INCH

        else:
            raise ValueError(f'invalid unit {unit}, must be "inch" or "mm".')

    def __add__(self, other):
        if not isinstance(other, UnitExpression):
            raise ValueError('Unit mismatch: Can only add/subtract UnitExpression from UnitExpression, not scalar.')

        if self.unit == other.unit or self.unit is None or other.unit is None:
            return UnitExpression(self._expr + other._expr, self.unit)

        if other.unit == 'mm': # -> and self.unit == 'inch'
            return UnitExpression(self._expr + (other._expr / MILLIMETERS_PER_INCH), self.unit)
        else: # other.unit == 'inch' and self.unit == 'mm'
            return UnitExpression(self._expr + (other._expr * MILLIMETERS_PER_INCH), self.unit)

    def __radd__(self, other):
        # left hand side cannot have been an UnitExpression or __radd__ would not have been called
        raise ValueError('Unit mismatch: Can only add/subtract UnitExpression from UnitExpression, not scalar.')

    def __sub__(self, other):
        return (self + (-other)).optimize()

    def __rsub__(self, other):
        # see __radd__ above
        raise ValueError('Unit mismatch: Can only add/subtract UnitExpression from UnitExpression, not scalar.')

    def __mul__(self, other):
        return UnitExpression(self._expr * other, self.unit)

    def __rmul__(self, other):
        return UnitExpression(other * self._expr, self.unit)

    def __truediv__(self, other):
        return UnitExpression(self._expr / other, self.unit)

    def __rtruediv__(self, other):
        return UnitExpression(other / self._expr, self.unit)

    def __neg__(self):
        return UnitExpression(-self._expr, self.unit)

    def __pos__(self):
        return self


class ConstantExpression(Expression):
    def __init__(self, value):
        self.value = value

    def __float__(self):
        return float(self.value)

    def __eq__(self, other):
        return type(self) == type(other) and self.value == other.value

    def to_gerber(self, _unit=None):
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
            return ConstantExpression(self.op(float(l), float(r)))

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

