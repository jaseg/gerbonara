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

from dataclasses import dataclass
from copy import deepcopy

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
    units : str = 'inch'
    angle_units : str = 'degrees'
    zeros : bool = None
    number_format : tuple = (2, 5)

    # input validation
    def __setattr__(self, name, value):
        if name == 'units' and value not in ['inch', 'mm']:
            raise ValueError(f'Units must be either "inch" or "mm", not {value}')
        elif name == 'notation' and value not in ['absolute', 'incremental']:
            raise ValueError(f'Notation must be either "absolute" or "incremental", not {value}')
        elif name == 'angle_units' and value not in ('degrees', 'radians'):
            raise ValueError(f'Angle units may be "degrees" or "radians", not {value}')
        elif name == 'zeros' and value not in [None, 'leading', 'trailing']:
            raise ValueError(f'zeros must be either "leading" or "trailing" or None, not {value}')
        elif name == 'number_format':
            if len(value) != 2:
                raise ValueError(f'Number format must be a (integer, fractional) tuple of integers, not {value}')

            if value[0] > 6 or value[1] > 7:
                raise ValueError(f'Requested precision of {value} is too high. Only up to 6.7 digits are supported by spec.')


        super().__setattr__(name, value)

    def copy(self):
        return deepcopy(self)

    def __str__(self):
        return f'<File settings: units={self.units}/{self.angle_units} notation={self.notation} zeros={self.zeros} number_format={self.number_format}>'

    def parse_gerber_value(self, value):
        if not value:
            return None

        # Handle excellon edge case with explicit decimal. "That was easy!"
        if '.' in value:
            return float(value)

        # Format precision
        integer_digits, decimal_digits = self.number_format

        # Remove extraneous information
        sign = '-' if value[0] == '-' else ''
        value = value.lstrip('+-')

        if self.zeros == 'leading':
            return float(sign + value[:-decimal_digits] + '.' + value[-decimal_digits:])

        else: # no or trailing zero suppression
            return float(sign + value[:integer_digits] + '.' + value[integer_digits:])

    def write_gerber_value(self, value):
        """ Convert a floating point number to a Gerber/Excellon-formatted string.  """
        
        integer_digits, decimal_digits = self.number_format

        # negative sign affects padding, so deal with it at the end...
        sign = '-' if value < 0 else ''

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


class CamFile:
    def __init__(self, filename=None, layer_name=None):
        self.filename = filename
        self.layer_name = layer_name
        self.import_settings = None

    @property
    def bounds(self):
        """ File boundaries
        """
        pass

    @property
    def bounding_box(self):
        pass

    def render(self, ctx=None, invert=False, filename=None):
        """ Generate image of layer.

        Parameters
        ----------
        ctx : :class:`GerberContext`
            GerberContext subclass used for rendering the image

        filename : string <optional>
            If provided, save the rendered image to `filename`
        """
        if ctx is None:
            from .render import GerberCairoContext
            ctx = GerberCairoContext()
        ctx.set_bounds(self.bounding_box)
        ctx.paint_background()
        ctx.invert = invert
        ctx.new_render_layer()
        for p in self.primitives:
            ctx.render(p)
        ctx.flatten()

        if filename is not None:
            ctx.dump(filename)
