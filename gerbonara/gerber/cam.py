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
        `zero_suppression='trailing'`
    '''
    notation : str = 'absolute'
    units : str = 'inch'
    angle_units : str = 'degrees'
    zeros : bool = None
    number_format : tuple = (2, 5)

    # input validation
    def __setattr__(self, name, value):
        elif name == 'notation' and value not in ['inch', 'mm']:
            raise ValueError('Units must be either "inch" or "mm"')
        elif name == 'units' and value not in ['absolute', 'incremental']:
            raise ValueError('Notation must be either "absolute" or "incremental"')
        elif name == 'angle_units' and value not in ('degrees', 'radians'):
            raise ValueError('Angle units may be "degrees" or "radians"')
        elif name == 'zeros' and value not in [None, 'leading', 'trailing']:
            raise ValueError('zero_suppression must be either "leading" or "trailing" or None')
        elif name == 'number_format':
            if len(value) != 2:
                raise ValueError('Number format must be a (integer, fractional) tuple of integers')

            if value[0] > 6 or value[1] > 7:
                raise ValueError('Requested precision is too high. Only up to 6.7 digits are supported by spec.')


        super().__setattr__(name, value)

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

        missing_digits = MAX_DIGITS - len(value)

        if self.zero_suppression == 'leading':
            return float(sign + value[:-decimal_digits] + '.' + value[-decimal_digits:])

        else: # no or trailing zero suppression
            return float(sign + value[:integer_digits] + '.' + value[integer_digits:])

    def write_gerber_value(self, value):
        """ Convert a floating point number to a Gerber/Excellon-formatted string.  """
        
        integer_digits, decimal_digits = self.number_format

        # negative sign affects padding, so deal with it at the end...
        sign = '-' if value < 0 else ''

        num = format(abs(value), f'0{integer_digits+decimal_digits+1}.{decimal_digits}f')

        # Suppression...
        if self.zero_suppression == 'trailing':
            num = num.rstrip('0')

        elif self.zero_suppression == 'leading':
            num = num.lstrip('0')

        # Edge case. Per Gerber spec if the value is 0 we should return a single '0' in all cases, see page 77.
        elif not num.strip('0'):
            num = '0'

        return sign + (num or '0')


class CamFile(object):
    """ Base class for Gerber/Excellon files.

    Provides a common set of settings parameters.

    Parameters
    ----------
    settings : FileSettings
        The current file configuration.

    primitives : iterable
        List of primitives in the file.

    filename : string
        Name of the file that this CamFile represents.

    layer_name : string
        Name of the PCB layer that the file represents

    Attributes
    ----------
    settings : FileSettings
        File settings as a FileSettings object

    notation : string
        File notation setting. May be either 'absolute' or 'incremental'

    units : string
        File units setting. May be 'inch' or 'mm'

    zero_suppression : string
        File zero-suppression setting. May be either 'leading' or 'trailling'

    format : tuple (<int>, <int>)
        File decimal representation format as a tuple of (integer digits,
        decimal digits)
    """

    def __init__(self, settings=None, primitives=None,
                 filename=None, layer_name=None):
        self.settings = settings if settings is not None else FileSettings()
        self.filename = filename
        self.layer_name = layer_name

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
