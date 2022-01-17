#!/usr/bin/env python
# -*- coding: utf-8 -*-

# copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Gerber (RS-274X) Statements
===========================
**Gerber RS-274X file statement classes**

"""

# FIXME make this entire file obsolete and just return strings from graphical objects directly instead

class Statement:
    pass

class ParamStmt(Statement):
    pass

class FormatSpecStmt(ParamStmt):
    """ FS - Gerber Format Specification Statement """

    def to_gerber(self, settings):
        zeros = 'T' if settings.zeros == 'trailing' else 'L' # default to leading if "None" is specified
        notation = 'I' if settings.notation == 'incremental' else 'A' # default to absolute
        number_format = str(settings.number_format[0]) + str(settings.number_format[1])

        return f'%FS{zeros}{notation}X{number_format}Y{number_format}*%'

    def __str__(self):
        return '<FS Format Specification>'


class UnitStmt(ParamStmt):
    """ MO - Coordinate unit mode statement """

    def to_gerber(self, settings):
        return '%MOMM*%' if settings.unit == 'mm' else '%MOIN*%'

    def __str__(self):
        return ('<MO Coordinate unit mode statement>' % mode_str)


class LoadPolarityStmt(ParamStmt):
    """ LP - Gerber Load Polarity statement """

    def __init__(self, dark):
        self.dark = dark

    def to_gerber(self, settings=None):
        lp = 'D' if self.dark else 'C'
        return f'%LP{lp}*%'

    def __str__(self):
        lp = 'dark' if self.dark else 'clear'
        return f'<LP Level Polarity: {lp}>'


class ApertureDefStmt(ParamStmt):
    """ AD - Aperture Definition Statement """

    def __init__(self, number, aperture):
        self.number = number
        self.aperture = aperture

    def to_gerber(self, settings=None):
        return f'%ADD{self.number}{self.aperture.to_gerber(settings)}*%'

    def __str__(self):
        return f'<AD aperture def for {str(self.aperture).strip("<>")}>'

    def __repr__(self):
        return f'ApertureDefStmt({self.number}, {repr(self.aperture)})'


class ApertureMacroStmt(ParamStmt):
    """ AM - Aperture Macro Statement """

    def __init__(self, macro):
        self.macro = macro

    def to_gerber(self, settings=None):
        unit = settings.unit if settings else None
        return f'%AM{self.macro.name}*\n{self.macro.to_gerber(unit=unit)}*\n%'

    def __str__(self):
        return f'<AM Aperture Macro {self.macro.name}: {self.macro}>'


class ImagePolarityStmt(ParamStmt):
    """ IP - Image Polarity Statement. (Deprecated) """

    def to_gerber(self, settings):
        #ip = 'POS' if settings.image_polarity == 'positive' else 'NEG'
        return f'%IPPOS*%'

    def __str__(self):
        return '<IP Image Polarity>'


class CoordStmt(Statement):
    """ D01 - D03 operation statements """

    def __init__(self, x, y, i=None, j=None, unit=None):
        self.x, self.y, self.i, self.j = x, y, i, j
        self.unit = unit

    def to_gerber(self, settings=None):
        ret = ''
        for var in 'xyij':
            val = self.unit.to(settings.unit, getattr(self, var))
            if val is not None:
                ret += var.upper() + settings.write_gerber_value(val)
        return ret + self.code + '*'

    def __str__(self):
        if self.i is None:
            return f'<{self.__name__.strip()} x={self.x} y={self.y}>'
        else:
            return f'<{self.__name__.strip()} x={self.x} y={self.y} i={self.i} j={self.j}>'

class InterpolateStmt(CoordStmt):
    """ D01 Interpolation """
    code = 'D01'

class MoveStmt(CoordStmt):
    """ D02 Move """
    code = 'D02'

class FlashStmt(CoordStmt):
    """ D03 Flash """
    code = 'D03'

class InterpolationModeStmt(Statement):
    """ G01 / G02 / G03 interpolation mode statement """
    def to_gerber(self, settings=None):
        return self.code + '*'

    def __str__(self):
        return f'<{self.__doc__.strip()}>'

class LinearModeStmt(InterpolationModeStmt):
    """ G01 linear interpolation mode statement """
    code = 'G01'

class CircularCWModeStmt(InterpolationModeStmt):
    """ G02 circular interpolation mode statement """
    code = 'G02'

class CircularCCWModeStmt(InterpolationModeStmt):
    """ G03 circular interpolation mode statement """
    code = 'G03'

class SingleQuadrantModeStmt(InterpolationModeStmt):
    """ G75 single-quadrant arc interpolation mode statement """
    code = 'G75'

class RegionStartStmt(InterpolationModeStmt):
    """ G36 Region Mode Start Statement. """
    code = 'G36'

class RegionEndStmt(InterpolationModeStmt):
    """ G37 Region Mode End Statement. """
    code = 'G37'

class ApertureStmt(Statement):
    def __init__(self, d):
        self.d = int(d)

    def to_gerber(self, settings=None):
        return 'D{0}*'.format(self.d)

    def __str__(self):
        return '<Aperture: %d>' % self.d


class CommentStmt(Statement):
    """ G04 Comment Statment """

    def __init__(self, comment):
        self.comment = comment if comment is not None else ""

    def to_gerber(self, settings=None):
        return f'G04{self.comment}*'

    def __str__(self):
        return f'<G04 Comment: {self.comment}>'


class EofStmt(Statement):
    """ M02 EOF Statement """

    def to_gerber(self, settings=None):
        return 'M02*'

    def __str__(self):
        return '<M02 EOF Statement>'

class UnknownStmt(Statement):
    def __init__(self, line):
        self.line = line

    def to_gerber(self, settings=None):
        return self.line

    def __str__(self):
        return f'<Unknown Statement: "{self.line}">'
