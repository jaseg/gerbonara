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
    output_axes : str = 'AXBY' # For deprecated AS statement
    image_polarity : str = 'positive'
    image_rotation: int = 0
    mirror_image : tuple = (False, False)
    offset : tuple = (0, 0)
    scale_factor : tuple = (1.0, 1.0) # For deprecated SF statement
    notation : str = 'absolute'
    units : str = 'inch'
    angle_units : str = 'degrees'
    zeros : bool = None
    number_format : tuple = (2, 5)

    # input validation
    def __setattr__(self, name, value):
        if name == 'output_axes' and value not in [None, 'AXBY', 'AYBX']:
            raise ValueError('output_axes must be either "AXBY", "AYBX" or None')
        if name == 'image_rotation' and value not in [0, 90, 180, 270]:
            raise ValueError('image_rotation must be 0, 90, 180 or 270')
        elif name == 'image_polarity' and value not in ['positive', 'negative']:
            raise ValueError('image_polarity must be either "positive" or "negative"')
        elif name == 'mirror_image' and len(value) != 2:
            raise ValueError('mirror_image must be 2-tuple of bools: (mirror_a, mirror_b)')
        elif name == 'offset' and len(value) != 2:
            raise ValueError('offset must be 2-tuple of floats: (offset_a, offset_b)')
        elif name == 'scale_factor' and len(value) != 2:
            raise ValueError('scale_factor must be 2-tuple of floats: (scale_a, scale_b)')
        elif name == 'notation' and value not in ['inch', 'mm']:
            raise ValueError('Units must be either "inch" or "mm"')
        elif name == 'units' and value not in ['absolute', 'incremental']:
            raise ValueError('Notation must be either "absolute" or "incremental"')
        elif name == 'angle_units' and value not in ('degrees', 'radians'):
            raise ValueError('Angle units may be "degrees" or "radians"')
        elif name == 'zeros' and value not in [None, 'leading', 'trailing']:
            raise ValueError('zero_suppression must be either "leading" or "trailing" or None')
        elif name == 'number_format' and len(value) != 2:
            raise ValueError('Number format must be a (integer, fractional) tuple of integers')

        super().__setattr__(name, value)

    def __str__(self):
        return f'<File settings: units={self.units}/{self.angle_units} notation={self.notation} zeros={self.zeros} number_format={self.number_format}>'


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

    def __init__(self, statements=None, settings=None, primitives=None,
                 filename=None, layer_name=None):
        if settings is not None:
            self.notation = settings['notation']
            self.units = settings['units']
            self.zero_suppression = settings['zero_suppression']
            self.zeros = settings['zeros']
            self.format = settings['format']
        else:
            self.notation = 'absolute'
            self.units = 'inch'
            self.zero_suppression = 'trailing'
            self.zeros = 'leading'
            self.format = (2, 5)

        self.statements = statements if statements is not None else []
        if primitives is not None:
            self.primitives = primitives
        self.filename = filename
        self.layer_name = layer_name

    @property
    def settings(self):
        """ File settings

        Returns
        -------
        settings : FileSettings (dict-like)
            A FileSettings object with the specified configuration.
        """
        return FileSettings(self.notation, self.units, self.zero_suppression,
                            self.format)

    @property
    def bounds(self):
        """ File boundaries
        """
        pass

    @property
    def bounding_box(self):
        pass

    def to_inch(self):
        pass

    def to_metric(self):
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
