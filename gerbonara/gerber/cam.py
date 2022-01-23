#! /usr/bin/env python
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

import math
from dataclasses import dataclass
from copy import deepcopy

from .utils import LengthUnit, MM, Inch, Tag
from . import graphic_primitives as gp

@dataclass
class FileSettings:
    '''
    .. note::
        Format and zero suppression are configurable. Note that the Excellon
        and Gerber formats use opposite terminology with respect to leading
        and trailing zeros. The Gerber format specifies which zeros are
        suppressed, while the Excellon format specifies which zeros are
        included. This function uses the Gerber-file convention, so an
        Excellon file in LZ (leading zeros) mode would use
        `zeros='trailing'`
    '''
    notation : str = 'absolute'
    unit : LengthUnit = MM
    angle_unit : str = 'degree'
    zeros : bool = None
    number_format : tuple = (2, 5)

    # input validation
    def __setattr__(self, name, value):
        if name == 'unit' and value not in [MM, Inch]:
            raise ValueError(f'Unit must be either Inch or MM, not {value}')
        elif name == 'notation' and value not in ['absolute', 'incremental']:
            raise ValueError(f'Notation must be either "absolute" or "incremental", not {value}')
        elif name == 'angle_unit' and value not in ('degree', 'radian'):
            raise ValueError(f'Angle unit may be "degree" or "radian", not {value}')
        elif name == 'zeros' and value not in [None, 'leading', 'trailing']:
            raise ValueError(f'zeros must be either "leading" or "trailing" or None, not {value}')
        elif name == 'number_format':
            if len(value) != 2:
                raise ValueError(f'Number format must be a (integer, fractional) tuple of integers, not {value}')

            if value != (None, None) and (value[0] > 6 or value[1] > 7):
                raise ValueError(f'Requested precision of {value} is too high. Only up to 6.7 digits are supported by spec.')


        super().__setattr__(name, value)

    def copy(self):
        return deepcopy(self)

    def __str__(self):
        return f'<File settings: unit={self.unit}/{self.angle_unit} notation={self.notation} zeros={self.zeros} number_format={self.number_format}>'

    @property
    def incremental(self):
        return self.notation == 'incremental'

    @property
    def absolute(self):
        return not self.incremental # default to absolute

    def parse_gerber_value(self, value):
        if not value:
            return None

        # Handle excellon edge case with explicit decimal. "That was easy!"
        if '.' in value:
            return float(value)

        # TARGET3001! exports zeros as "00" even when it uses an explicit decimal point everywhere else.
        if int(value) == 0:
            return 0

        # Format precision
        integer_digits, decimal_digits = self.number_format
        if integer_digits is None or decimal_digits is None:
            raise SyntaxError('No number format set and value does not contain a decimal point. If this is an Allegro '
                    'Excellon drill file make sure either nc_param.txt or ncdrill.log ends up in the same folder as '
                    'it, because Allegro does not include this critical information in their Excellon output. If you '
                    'call this through ExcellonFile.from_string, you must manually supply from_string with a '
                    'FileSettings object from excellon.parse_allegro_ncparam.')

        # Remove extraneous information
        sign = '-' if value[0] == '-' else ''
        value = value.lstrip('+-')

        if self.zeros == 'leading':
            value = '0'*decimal_digits + value # pad with zeros to ensure we have enough decimals
            return float(sign + value[:-decimal_digits] + '.' + value[-decimal_digits:])

        else: # no or trailing zero suppression
            return float(sign + value[:integer_digits] + '.' + value[integer_digits:])

    def write_gerber_value(self, value, unit=None):
        """ Convert a floating point number to a Gerber/Excellon-formatted string.  """

        if unit is not None:
            value = self.unit(value, unit)
        
        integer_digits, decimal_digits = self.number_format
        if integer_digits is None:
            integer_digits = 3
        if decimal_digits is None:
            decimal_digits = 3

        # negative sign affects padding, so deal with it at the end...
        sign = '-' if value < 0 else ''

        # FIXME never use exponential notation here
        num = format(abs(value), f'0{integer_digits+decimal_digits+1}.{decimal_digits}f').replace('.', '')

        # Suppression...
        if self.zeros == 'trailing':
            num = num.rstrip('0')

        elif self.zeros == 'leading':
            num = num.lstrip('0')

        # Edge case. Per Gerber spec if the value is 0 we should return a single '0' in all cases, see page 77.
        elif not num.strip('0'):
            num = '0'

        return sign + (num or '0')

    def write_excellon_value(self, value, unit=None):
        if unit is not None:
            value = self.unit(value, unit)
        
        integer_digits, decimal_digits = self.number_format
        if integer_digits is None:
            integer_digits = 2
        if decimal_digits is None:
            decimal_digits = 6

        return format(value, f'0{integer_digits+decimal_digits+1}.{decimal_digits}f')


class CamFile:
    def __init__(self, filename=None, layer_name=None):
        self.filename = filename
        self.layer_name = layer_name
        self.import_settings = None
        self.objects = []

    def to_svg(self, tag=Tag, margin=0, arg_unit=MM, svg_unit=MM, force_bounds=None, color='black'):

        if force_bounds is None:
            (min_x, min_y), (max_x, max_y) = self.bounding_box(svg_unit, default=((0, 0), (0, 0)))
        else:
            (min_x, min_y), (max_x, max_y) = force_bounds
            min_x = svg_unit(min_x, arg_unit)
            min_y = svg_unit(min_y, arg_unit)
            max_x = svg_unit(max_x, arg_unit)
            max_y = svg_unit(max_y, arg_unit)

        if margin:
            margin = svg_unit(margin, arg_unit)
            min_x -= margin
            min_y -= margin
            max_x += margin
            max_y += margin

        w, h = max_x - min_x, max_y - min_y
        w = 1.0 if math.isclose(w, 0.0) else w
        h = 1.0 if math.isclose(h, 0.0) else h

        primitives = [ prim for obj in self.objects for prim in obj.to_primitives(unit=svg_unit) ]
        tags = []
        polyline = None
        for primitive in primitives:
            if isinstance(primitive, gp.Line):
                if not polyline:
                    polyline = gp.Polyline(primitive)
                else:
                    if not polyline.append(primitive):
                        tags.append(polyline.to_svg(tag, color))
                        polyline = gp.Polyline(primitive)
            else:
                if polyline:
                    tags.append(polyline.to_svg(tag, color))
                    polyline = None
                tags.append(primitive.to_svg(tag, color))
        if polyline:
            tags.append(polyline.to_svg(tag, color))

        # setup viewport transform flipping y axis
        xform = f'translate({min_x} {min_y+h}) scale(1 -1) translate({-min_x} {-min_y})'

        svg_unit = 'in' if svg_unit == 'inch' else 'mm'
        # TODO export apertures as <uses> where reasonable.
        return tag('svg', [tag('g', tags, transform=xform)],
                width=f'{w}{svg_unit}', height=f'{h}{svg_unit}',
                viewBox=f'{min_x} {min_y} {w} {h}',
                xmlns="http://www.w3.org/2000/svg", xmlns__xlink="http://www.w3.org/1999/xlink", root=True)

    def size(self, unit=MM):
        (x0, y0), (x1, y1) = self.bounding_box(unit, default=((0, 0), (0, 0)))
        return (x1 - x0, y1 - y0)

    def bounding_box(self, unit=MM, default=None):
        """ Calculate bounding box of file. Returns value given by 'default' argument when there are no graphical
        objects (default: None)
        """
        bounds = [ p.bounding_box(unit) for p in self.objects ]
        if not bounds:
            return default

        min_x = min(x0 for (x0, y0), (x1, y1) in bounds)
        min_y = min(y0 for (x0, y0), (x1, y1) in bounds)
        max_x = max(x1 for (x0, y0), (x1, y1) in bounds)
        max_y = max(y1 for (x0, y0), (x1, y1) in bounds)

        return ((min_x, min_y), (max_x, max_y))

