#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2021 Jan Sebastian Götte <gerbonara@jaseg.de>

from dataclasses import dataclass
import operator
import re
import ast
import math

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
            raise IndexError(f'Cannot fully resolve expression due to unresolved parameters: residual expression {expr} under parameters {variable_binding}')
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
        return NegatedExpression(self)

    def __pos__(self):
        return self

    def parameters(self):
        return tuple()

    @property
    def _operator(self):
        return None


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

    def to_gerber(self, register_variable=None, unit=None):
        return self.converted(unit).optimized().to_gerber(register_variable)

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

    def parameters(self):
        return self.expr.parameters()


@dataclass(frozen=True, slots=True)
class ConstantExpression(Expression):
    value: float

    def __float__(self):
        return float(self.value)

    def __eq__(self, other):
        try:
            return math.isclose(self.value, float(other), abs_tol=1e-9)
        except TypeError:
            return False

    def to_gerber(self, register_variable=None, unit=None):
        if self == 0: # Avoid producing "-0" for negative floating point zeros
            return '0'
        return f'{self.value:.6f}'.rstrip('0').rstrip('.')

    
@dataclass(frozen=True, slots=True)
class VariableExpression(Expression):
    ''' An expression that encapsulates some other complex expression and will replace all occurences of it with a newly
    allocated variable at export time.
    '''
    expr: Expression

    def optimized(self, variable_binding={}):
        opt = self.expr.optimized(variable_binding)
        if isinstance(opt, OperatorExpression):
            return self
        else:
            return opt

    def __eq__(self, other):
        return type(self) == type(other) and self.expr == other.expr

    def to_gerber(self, register_variable=None, unit=None):
        if register_variable is None:
            return self.expr.to_gerber(None, unit)
        else:
            num = register_variable(self.expr.converted(unit).optimized())
            return f'${num}'

@dataclass(frozen=True, slots=True)
class ParameterExpression(Expression):
    ''' An expression that refers to a macro variable or parameter '''
    number: int

    def optimized(self, variable_binding={}):
        if self.number in variable_binding:
            return expr(variable_binding[self.number]).optimized(variable_binding)
        return self

    def __eq__(self, other):
        return type(self) == type(other) and \
                self.number == other.number

    def to_gerber(self, register_variable=None, unit=None):
        return f'${self.number}'

    def parameters(self):
        yield self


@dataclass(frozen=True, slots=True)
class NegatedExpression(Expression):
    value: Expression

    def optimized(self, variable_binding={}):
        match self.value.optimized(variable_binding):
            # -(-x) == x
            case NegatedExpression(inner_value):
                return inner_value
            # -(x) == -x
            case ConstantExpression(inner_value):
                return ConstantExpression(-inner_value)
            # -(x-y) == y-x
            case OperatorExpression(operator.sub, l, r):
                return OperatorExpression(operator.sub, r, l)
            # Round very small values and negative floating point zeros to a (positive) zero
            case 0:
                return expr(0)
            # Default case
            case x:
                return NegatedExpression(x)

    @property
    def _operator(self):
        return self.value._operator

    def __eq__(self, other):
        return type(self) == type(other) and \
                self.value == other.value

    def to_gerber(self, register_variable=None, unit=None):
        val_str = self.value.to_gerber(register_variable, unit)
        if isinstance(self.value, (VariableExpression, ParameterExpression)):
            return f'-{val_str}'
        else:
            return f'-({val_str})'


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

    @property
    def _operator(self):
        return self.op

    def optimized(self, variable_binding={}):
        l = self.l.optimized(variable_binding)
        r = self.r.optimized(variable_binding)
        
        match (l, self.op, r):
            case (ConstantExpression(), op, ConstantExpression()):
                return ConstantExpression(self.op(float(l), float(r)))

            # Minimize operations with neutral elements and zeros
            # 0 + x == x
            case (0, operator.add, r):
                return r
            # x + 0 == x
            case (l, operator.add, 0):
                return l
            # 0 * x == 0
            case (0, operator.mul, r):
                return expr(0)
            # x * 0 == 0
            case (l, operator.mul, 0):
                return expr(0)
            # x * 1 == x
            case (l, operator.mul, 1):
                return l
            # 1 * x == x
            case (1, operator.mul, r):
                return r
            # x * -1 == -x
            case (l, operator.mul, -1):
                rv = -l
            # -1 * x == -x
            case (-1, operator.mul, r):
                rv = -r
            # x - 0 == x
            case (l, operator.sub, 0):
                return l
            # 0 - x == -x (unary minus)
            case (0, operator.sub, r):
                rv = -r
            # x - x == 0
            case (l, operator.sub, r) if l == r:
                return expr(0)
            # x - -y == x + y
            case (l, operator.sub, NegatedExpression(r)):
                rv = (l + r)
            # x / 1 == x
            case (l, operator.truediv, 1):
                return l
            # x / -1 == -x
            case (l, operator.truediv, -1):
                rv = -l
            # x / x == 1
            case (l, operator.truediv, r) if l == r:
                return expr(1)
            # -x [*/] -y == x [*/] y
            case (NegatedExpression(l), (operator.truediv | operator.mul) as op, NegatedExpression(r)):
                rv = op(l, r)
            # x + -y == x - y
            case (l, operator.add, NegatedExpression(r)):
                rv = l-r
            # -x + y == y - x
            case (NegatedExpression(l), operator.add, r):
                rv = r-l

            case _: # default
                return OperatorExpression(self.op, l, r)

        return expr(rv).optimized(variable_binding)

    def to_gerber(self, register_variable=None, unit=None):
        lval = self.l.to_gerber(register_variable, unit)
        rval = self.r.to_gerber(register_variable, unit)

        if isinstance(self.l, OperatorExpression):
            lval = f'({lval})'
        if isinstance(self.r, OperatorExpression):
            rval = f'({rval})'

        op = {operator.add: '+',
              operator.sub: '-',
              operator.mul: 'x',
              operator.truediv: '/'} [self.op]

        return f'{lval}{op}{rval}'

    def parameters(self):
        yield from self.l.parameters()
        yield from self.r.parameters()

