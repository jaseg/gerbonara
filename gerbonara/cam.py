#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
# Copyright 2022 Jan Götte <code@jaseg.de>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import math
from dataclasses import dataclass
from copy import deepcopy
from enum import Enum
import string
import shutil
from pathlib import Path
from functools import cached_property

from .utils import LengthUnit, MM, Inch, Tag, sum_bounds, setup_svg
from . import graphic_primitives as gp
from . import graphic_objects as go

@dataclass
class FileSettings:
    ''' Format settings for Gerber/Excellon import/export.

    .. note::
        Format and zero suppression are configurable. Note that the Excellon and Gerber formats use opposite terminology
        with respect to leading and trailing zeros. The Gerber format specifies which zeros are suppressed, while the
        Excellon format specifies which zeros are included. This function uses the Gerber-file convention, so an
        Excellon file in LZ (leading zeros) mode would use ``zeros='trailing'``
    '''
    #: Coordinate notation. ``'absolute'`` or ``'incremental'``. Absolute mode is universally used today. Incremental
    #: (relative) mode is technically still supported, but exceedingly rare in the wild.
    notation : str = 'absolute'
    #: Export unit. :py:attr:`~.utilities.MM` or :py:attr:`~.utilities.Inch`
    unit : LengthUnit = MM
    #: Angle unit. Should be ``'degree'`` unless you really know what you're doing.
    angle_unit : str = 'degree'
    #: Zero suppression settings. See note at :py:class:`.FileSettings` for meaning.
    zeros : bool = None
    #: Number format. ``(integer, decimal)`` tuple of number of integer and decimal digits. At most ``(6,7)`` by spec.
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

        if name in ('zeros', 'number_format'):
            num = self.number_format[1 if self.zeros == 'leading' else 0] or 0
            self._pad = '0'*num

    def to_radian(self, value):
        """ Convert a given numeric string or a given float from file units into radians. """
        value = float(value)
        return math.radians(value) if self.angle_unit == 'degree' else value

    def parse_ipc_length(self, value, default=None):
        if value is None or not str(value).strip():
            return default

        if isinstance(value, str) and value[0].isalpha():
            value = value[1:]

        value = int(value)
        value *= 0.0001 if self.is_inch else 0.001
        return value

    def format_ipc_number(self, value, digits, key='', sign=False):
        if value is None:
            return ' ' * (digits + int(bool(sign)) + len(key))

        if isinstance(value, Enum):
            value = value.value
        num = format(round(value), f'{"+" if sign else ""}0{digits+int(bool(sign))}d')

        if len(num) > digits + int(bool(sign)):
            raise ValueError('Error: Number {num} to wide for IPC-356 field of width {digits}')

        return key + num

    def format_ipc_length(self, value, digits, key='', unit=None, sign=False):
        if value is not None:
            value = self.unit(value, unit)
            value /= 0.0001 if self.is_inch else  0.001

        return self.format_ipc_number(value, digits, key, sign=sign)

    @property
    def is_metric(self):
        return self.unit == MM

    @property
    def is_inch(self):
        return self.unit == Inch

    def copy(self):
        return deepcopy(self)

    def __str__(self):
        notation = f'notation={self.notation} ' if self.notation != 'absolute' else ''
        return f'<File settings: unit={self.unit}/{self.angle_unit} {notation}zeros={self.zeros} number_format={self.number_format}>'

    @property
    def is_incremental(self):
        return self.notation == 'incremental'

    @property
    def is_absolute(self):
        return not self.is_incremental # default to absolute

    def parse_gerber_value(self, value):
        """ Parse a numeric string in gerber format using this file's settings. """
        if not value:
            return None

        if '.' in value or value == '00':
            return float(value)

        integer_digits, decimal_digits = self.number_format

        if self.zeros == 'leading':
            value = self._pad + value # pad with zeros to ensure we have enough decimals
            return float(value[:-decimal_digits] + '.' + value[-decimal_digits:])

        else: # no or trailing zero suppression
            value = value + self._pad
            return float(value[:integer_digits] + '.' + value[integer_digits:])

    def write_gerber_value(self, value, unit=None):
        """ Convert a floating point number to a Gerber-formatted string.  """

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
        """ Convert a floating point number to an Excellon-formatted string.  """
        if unit is not None:
            value = self.unit(value, unit)
        
        integer_digits, decimal_digits = self.number_format
        if integer_digits is None:
            integer_digits = 2
        if decimal_digits is None:
            decimal_digits = 6

        return format(value, f'0{integer_digits+decimal_digits+1}.{decimal_digits}f')


class Polyline:
    """ Class that is internally used to generate compact SVG renderings. Collectes a number of subsequent
    :py:class:`~.graphic_objects.Line` and :py:class:`~.graphic_objects.Arc` instances into one SVG <path>. """

    def __init__(self, *lines):
        self.coords = []
        self.polarity_dark = None
        self.width = None

        for line in lines:
            self.append(line)

    def append(self, line):
        assert isinstance(line, gp.Line)
        if not self.coords:
            self.coords.append((line.x1, line.y1))
            self.coords.append((line.x2, line.y2))
            self.polarity_dark = line.polarity_dark
            self.width = line.width
            return True

        else:
            x, y = self.coords[-1]
            if self.polarity_dark == line.polarity_dark and self.width == line.width \
                    and math.isclose(line.x1, x) and math.isclose(line.y1, y):
                self.coords.append((line.x2, line.y2))
                return True

            else:
                return False

    def to_svg(self, fg='black', bg='white', tag=Tag):
        color = fg if self.polarity_dark else bg
        if not self.coords:
            return None

        (x0, y0), *rest = self.coords
        d = f'M {x0:.6} {y0:.6} ' + ' '.join(f'L {x:.6} {y:.6}' for x, y in rest)
        width = f'{self.width:.6}' if not math.isclose(self.width, 0) else '0.01mm'
        return tag('path', d=d, style=f'fill: none; stroke: {color}; stroke-width: {width:.6}; stroke-linejoin: round; stroke-linecap: round')


class CamFile:
    """ Base class for all layer classes (:py:class:`.GerberFile`, :py:class:`.ExcellonFile`, and :py:class:`.Netlist`).

    Provides some common functions such as :py:meth:`~.CamFile.to_svg`.
    """
    def __init__(self, original_path=None, layer_name=None, import_settings=None):
        self.original_path = original_path
        self.layer_name = layer_name
        self.import_settings = import_settings

    @property
    def is_lazy(self):
        return False

    @property
    def instance(self):
        return self

    def to_svg(self, margin=0, arg_unit=MM, svg_unit=MM, force_bounds=None, fg='black', bg='white', tag=Tag):
        if force_bounds:
            bounds = svg_unit.convert_bounds_from(arg_unit, force_bounds)
        else:
            bounds = self.bounding_box(svg_unit, default=((0, 0), (0, 0)))

        tags = list(self.svg_objects(svg_unit=svg_unit, tag=tag, fg=fg, bg=bg))

        # setup viewport transform flipping y axis
        (content_min_x, content_min_y), (content_max_x, content_max_y) = bounds
        content_w, content_h = content_max_x - content_min_x, content_max_y - content_min_y
        xform = f'translate({content_min_x:.6} {content_min_y+content_h:.6}) scale(1 -1) translate({-content_min_x:.6} {-content_min_y:.6})'
        tags = [tag('g', tags, transform=xform)]

        return setup_svg(tags, bounds, margin=margin, arg_unit=arg_unit, svg_unit=svg_unit,
                pagecolor=bg, tag=tag)

    def svg_objects(self, svg_unit=MM, fg='black', bg='white', tag=Tag):
        pl = None
        for i, obj in enumerate(self.objects):
            #if isinstance(obj, go.Flash):
            #    if pl:
            #        tags.append(pl.to_svg(tag, fg, bg))
            #        pl = None

            #    mask_tags = [ prim.to_svg(tag, 'white', 'black') for prim in obj.to_primitives(unit=svg_unit) ]
            #    mask_tags.insert(0, tag('rect', width='100%', height='100%', fill='black'))
            #    mask_id = f'mask{i}'
            #    tag('mask', mask_tags, id=mask_id)
            #    tag('rect', width='100%', height='100%', mask='url(#{mask_id})', fill=fg)

            #else:
                for primitive in obj.to_primitives(unit=svg_unit):
                    if isinstance(primitive, gp.Line):
                        if not pl:
                            pl = Polyline(primitive)
                        else:
                            if not pl.append(primitive):
                                yield pl.to_svg(fg, bg, tag=tag)
                                pl = Polyline(primitive)
                    else:
                        if pl:
                            yield pl.to_svg(fg, bg, tag=tag)
                            pl = None
                        yield primitive.to_svg(fg, bg, tag=tag)
        if pl:
            yield pl.to_svg(fg, bg, tag=tag)

    def size(self, unit=MM):
        """ Get the dimensions of the file's axis-aligned bounding box, i.e. the difference in x- and y-direction
        between the minimum x and y coordinates and the maximum x and y coordinates.

        :param unit: :py:class:`.LengthUnit` or str (``'mm'`` or ``'inch'``). Which unit to return results in. Default: mm
        :returns: ``(w, h)`` tuple of floats.
        :rtype: tuple
        """

        (x0, y0), (x1, y1) = self.bounding_box(unit, default=((0, 0), (0, 0)))
        return (x1 - x0, y1 - y0)

    def bounding_box(self, unit=MM, default=None):
        """ Calculate the axis-aligned bounding box of file. Returns value given by the ``default`` argument when the
        file is empty. This file calculates the accurate bounding box, even for features such as arcs.

        .. note:: Gerbonara returns bounding boxes as a ``(bottom_left, top_right)`` tuple of points, not in the
                  ``((min_x, max_x), (min_y, max_y))`` format used by pcb-tools.

        :param unit: :py:class:`.LengthUnit` or str (``'mm'`` or ``'inch'``). Which unit to return results in. Default: mm
        :returns: ``((x_min, y_min), (x_max, y_max))`` tuple of floats.
        :rtype: tuple
        """

        return sum_bounds(( p.bounding_box(unit) for p in self.objects ), default=default)

    def to_excellon(self):
        """ Convert to a :py:class:`.ExcellonFile`. Returns ``self`` if it already is one. """
        raise NotImplementedError()

    def to_gerber(self):
        """ Convert to a :py:class:`.GerberFile`. Returns ``self`` if it already is one. """
        raise NotImplementedError()

    def merge(self, other):
        """ Merge ``other`` into ``self``, i.e. add all objects that are in ``other`` to ``self``. This resets
        :py:attr:`.import_settings` and :py:attr:`~.CamFile.generator`. Units and other file-specific settings are
        automatically handled.
        """
        raise NotImplementedError()

    @property
    def generator(self):
        """ Return our best guess as to which software produced this file.

        :returns: a str like ``'kicad'`` or ``'allegro'``
        """
        raise NotImplementedError()

    def offset(self, x=0, y=0, unit=MM):
        """ Add a coordinate offset to this file. The offset is given in Gerber/Excellon coordinates, so the Y axis
        points upwards. Gerbonara does not use the poorly-supported Gerber file offset options, but instead actually
        changes the coordinates of every object in the file. This means that you can load the generated file with any
        Gerber viewer, and things should just work.

        :param float x: X offset
        :param float y: Y offset
        :param unit: :py:class:`.LengthUnit` or str (``'mm'`` or ``'inch'``). Unit ``x`` and ``y`` are passed in. Default: mm
        """
        raise NotImplementedError()

    def rotate(self, angle, cx=0, cy=0, unit=MM):
        """ Apply a rotation to this file. The center of rotation is given in Gerber/Excellon coordinates, so the Y axis
        points upwards. Gerbonara does not use the poorly-supported Gerber file rotation options, but instead actually
        changes the coordinates and rotation of every object in the file. This means that you can load the generated
        file with any Gerber viewer, and things should just work.

        Note that when rotating certain apertures, they will be automatically converted to aperture macros during export
        since the standard apertures do not support rotation by spec. This is the same way most CAD packages deal with
        this issue so it should work with most Gerber viewers.
    
        :param float angle: Rotation angle in radians, *clockwise*.
        :param float cx: Center of rotation X coordinate
        :param float cy: Center of rotation Y coordinate
        :param unit: :py:class:`.LengthUnit` or str (``'mm'`` or ``'inch'``). Unit ``cx`` and ``cy`` are passed in. Default: mm
        """
        raise NotImplementedError()

    @property
    def is_empty(self):
        """ Check if there are any objects in this file. """
        return not bool(list(self.objects))

    def __len__(self):
        """ Return the number of objects in this file. Note that a e.g. a long trace or a long slot consisting of
        multiple segments is counted as one object per segment. Gerber regions are counted as only one object. """
        raise NotImplementedError()

    def __bool__(self):
        """ Test if this file contains any objects """
        return not self.is_empty

class LazyCamFile:
    def __init__(self, klass, path, *args, **kwargs):
        self._class = klass
        self.original_path = Path(path)
        self._args = args
        self._kwargs = kwargs

    @cached_property
    def instance(self):
        return self._class.open(self.original_path, *self._args, **self._kwargs)

    @property
    def is_lazy(self):
        return True

    def save(self, filename, *args, **kwargs):
        """ Copy this Gerber file to the new path. """
        shutil.copy(self.original_path, filename)

