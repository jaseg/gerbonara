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
from .utils import (parse_gerber_value, write_gerber_value, decimal_string,
                    inch, metric)

from .am_statements import *
from .am_read import read_macro
from .am_primitive import eval_macro
from .primitives import AMGroup


class Statement:
    """ Gerber statement Base class

    The statement class provides a type attribute.

    Parameters
    ----------
    type : string
        String identifying the statement type.

    Attributes
    ----------
    type : string
        String identifying the statement type.
    """

    def __str__(self):
        s = "<{0} ".format(self.__class__.__name__)

        for key, value in self.__dict__.items():
            s += "{0}={1} ".format(key, value)

        s = s.rstrip() + ">"
        return s

    def offset(self, x_offset=0, y_offset=0):
        pass

    def __eq__(self, other):
        return self.__dict__ == other.__dict__


class ParamStmt(Statement):
    pass

class FormatSpecStmt(ParamStmt):
    """ FS - Gerber Format Specification Statement """
    code = 'FS'

    def to_gerber(self, settings):
        zeros = 'L' if settings.zero_suppression == 'leading' else 'T'
        notation = 'A' if settings.notation == 'absolute' else 'I'
        fmt = settings.number_format
        number_format = str(settings.number_format[0]) + str(settings.number_format[1])

        return f'%FS{zeros}{notation}X{number_format}Y{number_format}*%'

    def __str__(self):
        return '<FS Format Specification>'


class UnitStmt(ParamStmt):
    """ MO - Coordinate unit mode statement """

    def to_gerber(self, settings):
        return '%MOMM*%' if settings.units == 'mm' else '%MOIN*%'

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


class ADParamStmt(ParamStmt):
    """ AD - Aperture Definition Statement """

    @classmethod
    def rect(cls, dcode, width, height, hole_diameter=None, hole_width=None, hole_height=None):
        '''Create a rectangular aperture definition statement'''
        if hole_diameter is not None and hole_diameter > 0:
            return cls('AD', dcode, 'R', ([width, height, hole_diameter],))
        elif (hole_width is not None and hole_width > 0
              and hole_height is not None and hole_height > 0):
            return cls('AD', dcode, 'R', ([width, height, hole_width, hole_height],))
        return cls('AD', dcode, 'R', ([width, height],))

    @classmethod
    def circle(cls, dcode, diameter, hole_diameter=None, hole_width=None, hole_height=None):
        '''Create a circular aperture definition statement'''
        if hole_diameter is not None and hole_diameter > 0:
            return cls('AD', dcode, 'C', ([diameter, hole_diameter],))
        elif (hole_width is not None and hole_width > 0
              and hole_height is not None and hole_height > 0):
            return cls('AD', dcode, 'C', ([diameter, hole_width, hole_height],))
        return cls('AD', dcode, 'C', ([diameter],))

    @classmethod
    def obround(cls, dcode, width, height, hole_diameter=None, hole_width=None, hole_height=None):
        '''Create an obround aperture definition statement'''
        if hole_diameter is not None and hole_diameter > 0:
            return cls('AD', dcode, 'O', ([width, height, hole_diameter],))
        elif (hole_width is not None and hole_width > 0
              and hole_height is not None and hole_height > 0):
            return cls('AD', dcode, 'O', ([width, height, hole_width, hole_height],))
        return cls('AD', dcode, 'O', ([width, height],))

    @classmethod
    def polygon(cls, dcode, diameter, num_vertices, rotation, hole_diameter=None, hole_width=None, hole_height=None):
        '''Create a polygon aperture definition statement'''
        if hole_diameter is not None and hole_diameter > 0:
            return cls('AD', dcode, 'P', ([diameter, num_vertices, rotation, hole_diameter],))
        elif (hole_width is not None and hole_width > 0
              and hole_height is not None and hole_height > 0):
            return cls('AD', dcode, 'P', ([diameter, num_vertices, rotation, hole_width, hole_height],))
        return cls('AD', dcode, 'P', ([diameter, num_vertices, rotation],))


    @classmethod
    def macro(cls, dcode, name):
        return cls('AD', dcode, name, '')

    @classmethod
    def from_dict(cls, stmt_dict):
        param = stmt_dict.get('param')
        d = int(stmt_dict.get('d'))
        shape = stmt_dict.get('shape')
        modifiers = stmt_dict.get('modifiers')
        return cls(param, d, shape, modifiers)

    def __init__(self, param, d, shape, modifiers):
        """ Initialize ADParamStmt class

        Parameters
        ----------
        param : string
            Parameter code

        d : int
            Aperture D-code

        shape : string
            aperture name

        modifiers : list of lists of floats
            Shape modifiers

        Returns
        -------
        ParamStmt : ADParamStmt
            Initialized ADParamStmt class.

        """
        ParamStmt.__init__(self, param)
        self.d = d
        self.shape = shape
        if isinstance(modifiers, tuple):
            self.modifiers = modifiers
        elif modifiers:
            self.modifiers = [tuple([float(x) for x in m.split("X") if len(x)])
                              for m in modifiers.split(",") if len(m)]
        else:
            self.modifiers = [tuple()]

    def to_inch(self):
        if self.units == 'metric':
            self.units = 'inch'
            self.modifiers = [tuple([inch(x) for x in modifier])
                              for modifier in self.modifiers]

    def to_metric(self):
        if self.units == 'inch':
            self.units = 'metric'
            self.modifiers = [tuple([metric(x) for x in modifier])
                              for modifier in self.modifiers]

    def to_gerber(self, settings=None):
        if any(self.modifiers):
            return '%ADD{0}{1},{2}*%'.format(self.d, self.shape, ','.join(['X'.join(["%.4g" % x for x in modifier]) for modifier in self.modifiers]))
        else:
            return '%ADD{0}{1}*%'.format(self.d, self.shape)

    def __str__(self):
        if self.shape == 'C':
            shape = 'circle'
        elif self.shape == 'R':
            shape = 'rectangle'
        elif self.shape == 'O':
            shape = 'obround'
        else:
            shape = self.shape

        return '<Aperture Definition: %d: %s>' % (self.d, shape)


class AMParamStmt(ParamStmt):
    """ AM - Aperture Macro Statement
    """

    @classmethod
    def from_dict(cls, stmt_dict, units):
        return cls(**stmt_dict, units=units)

    def __init__(self, param, name, macro, units):
        """ Initialize AMParamStmt class

        Parameters
        ----------
        param : string
            Parameter code

        name : string
            Aperture macro name

        macro : string
            Aperture macro string

        Returns
        -------
        ParamStmt : AMParamStmt
            Initialized AMParamStmt class.

        """
        ParamStmt.__init__(self, param)
        self.name = name
        self.macro = macro
        self.units = units
        self.primitives = list(eval_macro(read_macro(macro), units))

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

    def to_gerber(self, unit=None):
        primitive_defs = '\n'.join(primitive.to_gerber(unit=unit) for primitive in self.primitives)
        return f'%AM{self.name}*\n{primitive_defs}%'

    def rotate(self, angle, center=None):
        for primitive_def in self.primitives:
            primitive_def.rotate(angle, center)

    def __str__(self):
        return '<AM Aperture Macro %s: %s>' % (self.name, self.macro)


class AxisSelectionStmt(ParamStmt):
    """ AS - Axis Selection Statement. (Deprecated) """

    def to_gerber(self, settings):
        return f'%AS{settings.output_axes}*%'

    def __str__(self):
        return '<AS Axis Select>'

class ImagePolarityStmt(ParamStmt):
    """ IP - Image Polarity Statement. (Deprecated) """

    def to_gerber(self, settings):
        ip = 'POS' if settings.image_polarity == 'positive' else 'NEG'
        return f'%IP{ip}*%'

    def __str__(self):
        return '<IP Image Polarity>'


class ImageRotationStmt(ParamStmt):
    """ IR - Image Rotation Statement. (Deprecated) """

    def to_gerber(self, settings):
        return f'%IR{settings.image_rotation}*%'

    def __str__(self):
        return '<IR Image Rotation>'

class MirrorImageStmt(ParamStmt):
    """ MI - Mirror Image Statement. (Deprecated) """

    def to_gerber(self, settings):
        return f'%SFA{int(bool(settings.mirror_image[0]))}B{int(bool(settings.mirror_image[1]))}*%'

    def __str__(self):
        return '<MI Mirror Image>'

class OffsetStmt(ParamStmt):
    """ OF - File Offset Statement. (Deprecated) """

    def __init__(self, a, b):
        self.a, self.b = a, b

    def to_gerber(self, settings=None):
        # FIXME unit conversion
        return f'%OFA{decimal_string(self.a, precision=5)}B{decimal_string(self.b, precision=5)}*%'

    def __str__(self):
        return f'<OF Offset a={self.a} b={self.b}>'


class SFParamStmt(ParamStmt):
    """ SF - Scale Factor Statement. (Deprecated) """

    def __init__(self, a, b):
        self.a, self.b = a, b

    def to_gerber(self, settings=None):
        return '%SFA{decimal_string(self.a, precision=5)}B{decimal_string(self.b, precision=5)}*%'

    def __str__(self):
        return '<SF Scale Factor>'

class CoordStmt(Statement):
    """ D01 - D03 operation statements """

    def __init__(self, x, y, i, j):
        self.x = x
        self.y = y
        self.i = i
        self.j = j

    @classmethod
    def move(cls, func, point):
        if point:
            return cls(func, point[0], point[1], None, None, CoordStmt.OP_MOVE, None)
        # No point specified, so just write the function. This is normally for ending a region (D02*)
        return cls(func, None, None, None, None, CoordStmt.OP_MOVE, None)

    @classmethod
    def line(cls, func, point):
        return cls(func, point[0], point[1], None, None, CoordStmt.OP_DRAW, None)

    @classmethod
    def mode(cls, func):
        return cls(func, None, None, None, None, None, None)

    @classmethod
    def arc(cls, func, point, center):
        return cls(func, point[0], point[1], center[0], center[1], CoordStmt.OP_DRAW, None)

    @classmethod
    def flash(cls, point):
        if point:
            return cls(None, point[0], point[1], None, None, CoordStmt.OP_FLASH, None)
        else:
            return cls(None, None, None, None, None, CoordStmt.OP_FLASH, None)

    def to_gerber(self, settings=None):
        ret = ''
        if self.x is not None:
            ret += 'X{0}'.format(write_gerber_value(self.x, settings.format, settings.zero_suppression))
        if self.y is not None:
            ret += 'Y{0}'.format(write_gerber_value(self.y, settings.format, settings.zero_suppression))
        if self.i is not None:
            ret += 'I{0}'.format(write_gerber_value(self.i, settings.format, settings.zero_suppression))
        if self.j is not None:
            ret += 'J{0}'.format(write_gerber_value(self.j, settings.format, settings.zero_suppression))
        if self.op:
            ret += self.op
        return ret + '*'

    def offset(self, x_offset=0, y_offset=0):
        if self.x is not None:
            self.x += x_offset
        if self.y is not None:
            self.y += y_offset
        if self.i is not None:
            self.i += x_offset
        if self.j is not None:
            self.j += y_offset

    def __str__(self):
        coord_str = ''
        if self.function:
            coord_str += 'Fn: %s ' % self.function
        if self.x is not None:
            coord_str += 'X: %g ' % self.x
        if self.y is not None:
            coord_str += 'Y: %g ' % self.y
        if self.i is not None:
            coord_str += 'I: %g ' % self.i
        if self.j is not None:
            coord_str += 'J: %g ' % self.j
        if self.op:
            if self.op == 'D01':
                op = 'Lights On'
            elif self.op == 'D02':
                op = 'Lights Off'
            elif self.op == 'D03':
                op = 'Flash'
            else:
                op = self.op
            coord_str += 'Op: %s' % op

        return '<Coordinate Statement: %s>' % coord_str

    @property
    def only_function(self):
        """
        Returns if the statement only set the function.
        """

        # TODO I would like to refactor this so that the function is handled separately and then
        # TODO this isn't required
        return self.function != None and self.op == None and self.x == None and self.y == None and self.i == None and self.j == None

class InterpolateStmt(CoordStmt):
    """ D01 interpolation operation """
    code = 'D01'

class MoveStmt(CoordStmt):
    """ D02 move operation """
    code = 'D02'

class FlashStmt(CoordStmt):
    """ D03 flash operation """
    code = 'D03'

class InterpolationStmt(Statement):
    """ G01 / G02 / G03 interpolation mode statement """
    def to_gerber(self, **_kwargs):
        return self.code + '*'

    def __str__(self):
        return f'<{self.__doc__.strip()}>'

class LinearModeStmt(InterpolationStmt):
    """ G01 linear interpolation mode statement """
    code = 'G01'

class CircularCWModeStmt(InterpolationStmt):
    """ G02 circular interpolation mode statement """
    code = 'G02'

class CircularCCWModeStmt(InterpolationStmt):
    """ G03 circular interpolation mode statement """
    code = 'G03'

class SingleQuadrantModeStmt(InterpolationStmt):
    """ G75 single-quadrant arc interpolation mode statement """
    code = 'G75'

class MultiQuadrantModeStmt(InterpolationStmt):
    """ G74 multi-quadrant arc interpolation mode statement """
    code = 'G74'

class RegionStartStatement(InterpolationStmt):
    """ G36 Region Mode Start Statement. """
    code = 'G36'

class RegionEndStatement(InterpolationStmt):
    """ G37 Region Mode End Statement. """
    code = 'G37'

class ApertureStmt(Statement):
    def __init__(self, d):
        self.d = int(d)
        self.deprecated = True if deprecated is not None and deprecated is not False else False

    def to_gerber(self, settings=None):
        if self.deprecated:
            return 'G54D{0}*'.format(self.d)
        else:
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

    def __init__(self):
        Statement.__init__(self, "EOF")

    def to_gerber(self, settings=None):
        return 'M02*'

    def __str__(self):
        return '<M02 EOF Statement>'

class UnknownStmt(Statement):
    def __init__(self, line):
        self.line = line

    def to_gerber(self, settings):
        return self.line

    def __str__(self):
        return f'<Unknown Statement: "{self.line}">'
