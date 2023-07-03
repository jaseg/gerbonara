#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Sebastian Götte <gerbonara@jaseg.de>

from dataclasses import dataclass
import operator
import re
import ast

from ..utils import LengthUnit, MM, Inch, MILLIMETERS_PER_INCH


def expr(obj):
    return obj if isinstance(obj, Expression) else ConstantExpression(obj)
_make_expr = expr


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class UnitExpression(Expression):
    expr: Expression
    unit: LengthUnit

    def __init__(self, expr, unit):
        expr = _make_expr(expr)
        if isinstance(expr, UnitExpression):
            expr = expr.converted(unit)
        object.__setattr__(self, 'expr', expr)
        object.__setattr__(self, 'unit', unit)

    def to_gerber(self, unit=None):
        return self.converted(unit).optimized().to_gerber()

    def __eq__(self, other):
        return type(other) == type(self) and \
            self.unit == other.unit and\
            self.expr == other.expr

    def __str__(self):
        return f'<{self.expr.to_gerber()} {self.unit}>'

    def __repr__(self):
        return f'<UE {self.expr.to_gerber()} {self.unit}>'

    def converted(self, unit):
        if self.unit is None or unit is None or self.unit == unit:
            return self.expr

        elif MM == unit:
            return self.expr * MILLIMETERS_PER_INCH

        elif Inch == unit:
            return self.expr / MILLIMETERS_PER_INCH

        else:
            raise ValueError(f'invalid unit {unit}, must be "inch" or "mm".')

    def __add__(self, other):
        if not isinstance(other, UnitExpression):
            raise ValueError('Unit mismatch: Can only add/subtract UnitExpression from UnitExpression, not scalar.')

        if self.unit == other.unit or self.unit is None or other.unit is None:
            return UnitExpression(self.expr + other.expr, self.unit)

        if other.unit == 'mm': # -> and self.unit == 'inch'
            return UnitExpression(self.expr + (other.expr / MILLIMETERS_PER_INCH), self.unit)
        else: # other.unit == 'inch' and self.unit == 'mm'
            return UnitExpression(self.expr + (other.expr * MILLIMETERS_PER_INCH), self.unit)

    def __radd__(self, other):
        # left hand side cannot have been an UnitExpression or __radd__ would not have been called
        raise ValueError('Unit mismatch: Can only add/subtract UnitExpression from UnitExpression, not scalar.')

    def __sub__(self, other):
        return (self + (-other)).optimized()

    def __rsub__(self, other):
        # see __radd__ above
        raise ValueError('Unit mismatch: Can only add/subtract UnitExpression from UnitExpression, not scalar.')

    def __mul__(self, other):
        return UnitExpression(self.expr * other, self.unit)

    def __rmul__(self, other):
        return UnitExpression(other * self.expr, self.unit)

    def __truediv__(self, other):
        return UnitExpression(self.expr / other, self.unit)

    def __rtruediv__(self, other):
        return UnitExpression(other / self.expr, self.unit)

    def __neg__(self):
        return UnitExpression(-self.expr, self.unit)

    def __pos__(self):
        return self

@dataclass(frozen=True, slots=True)
class ConstantExpression(Expression):
    value: float

    def __float__(self):
        return float(self.value)

    def __eq__(self, other):
        return type(self) == type(other) and self.value == other.value

    def to_gerber(self, _unit=None):
        return f'{self.value:.6f}'.rstrip('0').rstrip('.')

    
@dataclass(frozen=True, slots=True)
class VariableExpression(Expression):
    number: int

    def optimized(self, variable_binding={}):
        if self.number in variable_binding:
            return expr(variable_binding[self.number]).optimized(variable_binding)
        return self

    def __eq__(self, other):
        return type(self) == type(other) and \
                self.number == other.number

    def to_gerber(self, _unit=None):
        return f'${self.number}'


@dataclass(frozen=True, slots=True)
class OperatorExpression(Expression):
    op: str
    l: Expression
    r: Expression

    def __init__(self, op, l, r):
        object.__setattr__(self, 'op', op)
        object.__setattr__(self, 'l', expr(l))
        object.__setattr__(self, 'r', expr(r))

    def __eq__(self, other):
        return type(self) == type(other) and \
                self.op == other.op and \
                self.l == other.l and \
                self.r == other.r

    def optimized(self, variable_binding={}):
        l = self.l.optimized(variable_binding)
        r = self.r.optimized(variable_binding)
        
        #if self.op in (operator.add, operator.mul):
        #    if id(r) < id(l):
        #        l, r = r, l

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

