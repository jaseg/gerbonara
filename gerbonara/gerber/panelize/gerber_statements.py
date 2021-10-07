#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

from ..gerber_statements import AMParamStmt, ADParamStmt
from ..utils import inch, metric
from .am_primitive import to_primitive_defs

class ADParamStmtEx(ADParamStmt):
    GEOMETRIES = {
        'C': [0,1],
        'R': [0,1,2],
        'O': [0,1,2],
        'P': [0,3],
    }

    @classmethod
    def from_stmt(cls, stmt):
        modstr = ','.join([
            'X'.join(['{0}'.format(x) for x in modifier])
        for modifier in stmt.modifiers])
        return cls(stmt.param, stmt.d, stmt.shape, modstr, stmt.units)

    def __init__(self, param, d, shape, modifiers, units):
        super(ADParamStmtEx, self).__init__(param, d, shape, modifiers)
        self.units = units

    def to_inch(self):
        if self.units == 'inch':
            return
        self.units = 'inch'
        if self.shape in self.GEOMETRIES:
            indices = self.GEOMETRIES[self.shape]
            self.modifiers = [tuple([
                inch(self.modifiers[0][i]) if i in indices else self.modifiers[0][i] \
                    for i in range(len(self.modifiers[0]))
            ])]

    def to_metric(self):
        if self.units == 'metric':
            return
        self.units = 'metric'
        if self.shape in self.GEOMETRIES:
            indices = self.GEOMETRIES[self.shape]
            self.modifiers = [tuple([
                metric(self.modifiers[0][i]) if i in indices else self.modifiers[0][i] \
                    for i in range(len(self.modifiers[0]))
            ])]
