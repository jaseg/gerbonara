#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

import operator

from ..utils import *
from ..am_eval import OpCode
from ..am_statements import *

class AMExpression(object):
    CONSTANT = 1
    VARIABLE = 2
    OPERATOR = 3

    def __init__(self, kind):
        self.kind = kind

    @property
    def value(self):
        return self

    def optimize(self):
        return self
    
    def to_inch(self):
        return AMOperatorExpression.div(self, MILLIMETERS_PER_INCH)

    def to_metric(self):
        return AMOperatorExpression.mul(self, MILLIMETERS_PER_INCH)

    #def to_gerber(self, settings=None):
    #    pass

    #def to_instructions(self):
    #    pass
    
class AMConstantExpression(AMExpression):
    def __init__(self, value):
        super(AMConstantExpression, self).__init__(AMExpression.CONSTANT)
        self._value = value

    @property
    def value(self):
        return self._value

    def __float__(self):
        return float(self._value)

    @staticmethod
    def _amex_val(other):
        return float(other) if isinstance(other, AMConstantExpression) else other

    def __eq__(self, val):
        return self._value == AMConstantExpression._amex_val(val)

    def __ne__(self, val):
        return self._value != AMConstantExpression._amex_val(val)

    def __lt__(self, val):
        return self._value < AMConstantExpression._amex_val(val)

    def __gt__(self, val):
        return self._value > AMConstantExpression._amex_val(val)

    def __le__(self, val):
        return self._value <= AMConstantExpression._amex_val(val)

    def __ge__(self, val):
        return self._value >= AMConstantExpression._amex_val(val)

    def to_gerber(self, settings=None):
        if isinstance(self._value, str):
            return self._value
        return f'{self.value:.6f}'.rstrip('0').rstrip('.')

    def to_instructions(self):
        return [(OpCode.PUSH, self._value)]
    
class AMVariableExpression(AMExpression):
    def __init__(self, number):
        super(AMVariableExpression, self).__init__(AMExpression.VARIABLE)
        self.number = number

    def to_gerber(self, settings=None):
        return f'${self.number}'
    
    def to_instructions(self):
        return (OpCode.LOAD, self.number)

class AMOperatorExpression(AMExpression):
    def __init__(self, op, lvalue, rvalue):
        super(AMOperatorExpression, self).__init__(AMExpression.OPERATOR)
        self.op = op
        self.lvalue = AMConstantExpression(lvalue) if isinstance(lvalue, (int, float)) else lvalue
        self.rvalue = AMConstantExpression(rvalue) if isinstance(rvalue, (int, float)) else rvalue

    @classmethod
    def add(kls, lvalue, rvalue):
        return kls(operator.add, lvalue, rvalue)
    
    @classmethod
    def sub(kls, lvalue, rvalue):
        return kls(operator.sub, lvalue, rvalue)
    
    @classmethod
    def mul(kls, lvalue, rvalue):
        return kls(operator.mul, lvalue, rvalue)
    
    @classmethod
    def div(kls, lvalue, rvalue):
        return kls(operator.truediv, lvalue, rvalue)
    
    def optimize(self):
        l = self.lvalue = self.lvalue.optimize()
        r = self.rvalue = self.rvalue.optimize()

        if isinstance(l, AMConstantExpression) and isinstance(r, AMConstantExpression):
            return AMConstantExpression(self.op(float(r), float(l)))

        elif self.op == operator.ADD:
            if r == 0:
                return l
            elif l == 0:
                return r

        elif self.op == operator.SUB:
            if r == 0:
                return l
            elif l == 0 and isinstance(r, AMConstantExpression):
                return AMConstantExpression(-float(r))

        elif self.op == operator.MUL:
            if r == 1:
                return l
            elif l == 1:
                return r
            elif l == 0 or r == 0:
                return AMConstantExpression(0)

        elif self.op == operator.TRUEDIV:
            if r == 1:
                return self.lvalue
            elif l == 0:
                return AMConstantExpression(0)
        
        return self
        
    def to_gerber(self, settings=None):
        lval = self.lvalue.to_gerber(settings)
        rval = self.rvalue.to_gerber(settings))
        op = {AMOperatorExpression.ADD: '+',
              AMOperatorExpression.SUB: '-',
              AMOperatorExpression.MUL: 'x',
              AMOperatorExpression.DIV: '/'} [self.op]
        return '(' + lval + op + rval + ')'

    def to_instructions(self):
        for i in self.lvalue.to_instructions():
            yield i

        for i in self.rvalue.to_instructions():
            yield i

        op = {AMOperatorExpression.ADD: OpCode.ADD,
              AMOperatorExpression.SUB: OpCode.SUB,
              AMOperatorExpression.MUL: OpCode.MUL,
              AMOperatorExpression.DIV: OpCode.DIV} [self.op]
        yield (op, None)

def eval_macro(instructions):
    stack = []

    def pop():
        return stack.pop()

    def push(op):
        stack.append(op)

    def top():
        return stack[-1]

    def empty():
        return len(stack) == 0

    for opcode, argument in instructions:
        if opcode == OpCode.PUSH:
            push(AMConstantExpression(argument))

        elif opcode == OpCode.LOAD:
            push(AMVariableExpression(argument))

        elif opcode == OpCode.STORE:
            yield (-argument, [pop()])

        elif opcode == OpCode.ADD:
            op1 = pop()
            op2 = pop()
            push(AMOperatorExpression(AMOperatorExpression.ADD, op2, op1))

        elif opcode == OpCode.SUB:
            op1 = pop()
            op2 = pop()
            push(AMOperatorExpression(AMOperatorExpression.SUB, op2, op1))

        elif opcode == OpCode.MUL:
            op1 = pop()
            op2 = pop()
            push(AMOperatorExpression(AMOperatorExpression.MUL, op2, op1))

        elif opcode == OpCode.DIV:
            op1 = pop()
            op2 = pop()
            push(AMOperatorExpression(AMOperatorExpression.DIV, op2, op1))

        elif opcode == OpCode.PRIM:
            yield (argument, stack)
            stack = []
