#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

from gerber.gerber_statements import AMParamStmt, ADParamStmt
from gerber.utils import inch, metric
from gerberex.am_primitive import to_primitive_defs

class AMParamStmtEx(AMParamStmt):
    @classmethod
    def from_stmt(cls, stmt):
        return cls(stmt.param, stmt.name, stmt.macro, stmt.units)

    @classmethod
    def circle(cls, name, units):
        return cls('AM', name, '1,1,$1,0,0,0*1,0,$2,0,0,0', units)

    @classmethod
    def rectangle(cls, name, units):
        return cls('AM', name, '21,1,$1,$2,0,0,0*1,0,$3,0,0,0', units)
    
    @classmethod
    def landscape_obround(cls, name, units):
        return cls(
            'AM', name,
            '$4=$1-$2*'
            '$5=$1-$4*'
            '21,1,$5,$2,0,0,0*'
            '1,1,$4,$4/2,0,0*'
            '1,1,$4,-$4/2,0,0*'
            '1,0,$3,0,0,0', units)

    @classmethod
    def portrate_obround(cls, name, units):
        return cls(
            'AM', name,
            '$4=$2-$1*'
            '$5=$2-$4*'
            '21,1,$1,$5,0,0,0*'
            '1,1,$4,0,$4/2,0*'
            '1,1,$4,0,-$4/2,0*'
            '1,0,$3,0,0,0', units)
    
    @classmethod
    def polygon(cls, name, units):
        return cls('AM', name, '5,1,$2,0,0,$1,$3*1,0,$4,0,0,0', units)

    def __init__(self, param, name, macro, units):
        super(AMParamStmtEx, self).__init__(param, name, macro)
        self.units = units
        self.primitive_defs = list(to_primitive_defs(self.instructions))
    
    def to_inch(self):
        if self.units == 'metric':
            self.units = 'inch'
            for p in self.primitive_defs:
                p.to_inch()

    def to_metric(self):
        if self.units == 'inch':
            self.units = 'metric'
            for p in self.primitive_defs:
                p.to_metric()

    def to_gerber(self, settings = None):
        def plist():
            for p in self.primitive_defs:
                yield p.to_gerber(settings)
        return "%%AM%s*\n%s%%" % (self.name, '\n'.join(plist()))

    def rotate(self, angle, center=None):
        for primitive_def in self.primitive_defs:
            primitive_def.rotate(angle, center)

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
