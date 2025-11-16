#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2022 Jan Sebastian Götte <gerbonara@jaseg.de>
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

import warnings
import math
from dataclasses import dataclass, replace, field, fields, InitVar, KW_ONLY
from functools import lru_cache

from .aperture_macros.parse import GenericMacros
from .utils import LengthUnit, MM, Inch, sum_bounds

from . import graphic_primitives as gp


def _flash_hole(self, x, y, unit=None, polarity_dark=True):
    if self.hole_dia is not None:
        return [*self._primitives(x, y, unit, polarity_dark),
                gp.Circle(x, y, self.unit.convert_to(unit, self.hole_dia/2), polarity_dark=(not polarity_dark))]
    else:
        return self._primitives(x, y, unit, polarity_dark)

def _strip_right(*args):
    args = list(args)
    while args and args[-1] is None:
        args.pop()
    return tuple(args)

def _none_close(a, b):
    if a is None and b is None:
        return True
    elif a is not None and b is not None:
        return math.isclose(a, b)
    else:
        return False

class Length:
    """ Marker indicating that a dataclass field of an :py:class:`.Aperture` contains a physical length or coordinate
    measured in the :py:class:`.Aperture`'s native unit from :py:attr:`.Aperture.unit`.
    """
    def __init__(self, obj_type):
        self.type = obj_type

@dataclass(frozen=True, slots=True)
class Aperture:
    """ Base class for all apertures. """
    _ : KW_ONLY
    unit: LengthUnit = None
    attrs: tuple = None
    original_number: int = field(default=None, hash=False, compare=False)
    _bounding_box: tuple = field(default=None, hash=False, compare=False)

    def _params(self, unit=None):
        out = []
        for f in fields(self):
            if f.kw_only:
                continue

            val = getattr(self, f.name)
            if isinstance(f.type, Length):
                val = self.unit.convert_to(unit, val)
            out.append(val)

        return out

    def flash(self, x, y, unit=None, polarity_dark=True):
        """ Render this aperture into a ``list`` of :py:class:`.GraphicPrimitive` instances in the given unit. If no
        unit is given, use this aperture's local unit.

        :param float x: X coordinate of center of flash.
        :param float y: Y coordinate of center of flash.
        :param LengthUnit unit: Physical length unit to use for the returned primitives.
        :param bool polarity_dark: Polarity of this flash. ``True`` renders this aperture as usual. ``False`` flips the polarity of all primitives.

        :returns: Rendered graphic primitivees.
        :rtype: list(:py:class:`.GraphicPrimitive`)
        """
        return self._primitives(x, y, unit, polarity_dark)

    def bounding_box(self, unit=None):
        if self._bounding_box is None:
            object.__setattr__(self, '_bounding_box',
                               sum_bounds((prim.bounding_box() for prim in self.flash(0, 0, MM, True))))
        return MM.convert_bounds_to(unit, self._bounding_box)

    def equivalent_width(self, unit=None):
        """ Get the width of a line interpolated using this aperture in the given :py:class:`~.LengthUnit`.

        :rtype: float
        """
        raise ValueError('Non-circular aperture used in interpolation statement, line width is not properly defined.')

    def to_gerber(self, settings=None):
        """ Return the Gerber aperture definition for this aperture using the given :py:class:`.FileSettings`.

        :rtype: str
        """
        unit = settings.unit if settings else None
        params = 'X'.join(f'{float(par):.4}' for par in self._params(unit) if par is not None)
        if params:
            return f'{self._gerber_shape_code},{params}'
        else:
            return self._gerber_shape_code

    def to_macro(self):
        """ Convert this :py:class:`.Aperture` into an :py:class:`.ApertureMacro` inside an
        :py:class:`.ApertureMacroInstance`.
        """
        raise NotImplementedError()

@dataclass(frozen=True, slots=True)
class ExcellonTool(Aperture):
    """ Special Aperture_ subclass for use in :py:class:`.ExcellonFile`. Similar to :py:class:`.CircleAperture`, but
    does not have :py:attr:`.CircleAperture.hole_dia`, and has the additional :py:attr:`plated` attribute.
    """
    _gerber_shape_code = 'C'
    _human_readable_shape = 'drill'
    #: float with diameter of this tool in :py:attr:`unit` units.
    diameter : Length(float)
    #: bool or ``None`` for "unknown", indicating whether this tool creates plated (``True``) or non-plated (``False``)
    #: holes.
    plated : bool = None
    
    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Circle(x, y, self.unit.convert_to(unit, self.diameter/2), polarity_dark=polarity_dark) ]

    def to_xnc(self, settings):
        return 'C' + settings.write_excellon_value(self.diameter, self.unit)

    def __str__(self):
        plated = '' if self.plated is None else (' plated' if self.plated else ' non-plated')
        return f'<Excellon Tool d={self.diameter:.3f}{plated} [{self.unit}]>'

    def equivalent_width(self, unit=MM):
        return unit(self.diameter, self.unit)

    # Internal use, for layer dilation.
    def dilated(self, offset, unit=MM):
        offset = unit(offset, self.unit)
        if math.isclose(offset, 0, abs_tol=1e-6):
            return self
        return replace(self, diameter=self.diameter+2*offset)

    @lru_cache()
    def rotated(self, angle=0):
        return self

    def to_macro(self, rotation=0):
        return ApertureMacroInstance(GenericMacros.circle, self._params(unit=MM))

    def _params(self, unit=None):
        return (self.unit.convert_to(unit, self.diameter),)


@dataclass(frozen=True, slots=True)
class CircleAperture(Aperture):
    """ Besides flashing circles or rings, CircleApertures are used to set the width of a
    :py:class:`~.graphic_objects.Line` or :py:class:`~.graphic_objects.Arc`.
    """
    _gerber_shape_code = 'C'
    _human_readable_shape = 'circle'
    #: float with diameter of the circle in :py:attr:`unit` units.
    diameter : Length(float)
    #: float with the hole diameter of this aperture in :py:attr:`unit` units. ``0`` for no hole.
    hole_dia : Length(float) = None

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Circle(x, y, self.unit.convert_to(unit, self.diameter/2), polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<circle aperture d={self.diameter:.3} [{self.unit}]>'

    flash = _flash_hole

    def equivalent_width(self, unit=None):
        return self.unit.convert_to(unit, self.diameter)

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        if math.isclose(offset, 0, abs_tol=1e-6):
            return self
        return replace(self, diameter=self.diameter+2*offset, hole_dia=None)

    @lru_cache()
    def rotated(self, angle=0):
        return self

    def scaled(self, scale):
        return replace(self, 
                       diameter=self.diameter*scale,
                       hole_dia=None if self.hole_dia is None else self.hole_dia*scale)

    def to_macro(self, rotation=0):
        return ApertureMacroInstance(GenericMacros.circle, self._params(unit=MM))

    def _params(self, unit=None):
        return _strip_right(
                self.unit.convert_to(unit, self.diameter),
                self.unit.convert_to(unit, self.hole_dia))


@dataclass(frozen=True, slots=True)
class RectangleAperture(Aperture):
    """ Gerber rectangle aperture. Can only be used for flashes, since the line width of an interpolation of a rectangle
    aperture is not well-defined and there is no tool that implements it in a geometrically correct way. """
    _gerber_shape_code = 'R'
    _human_readable_shape = 'rect'
    #: float with the width of the rectangle in :py:attr:`unit` units.
    w : Length(float)
    #: float with the height of the rectangle in :py:attr:`unit` units.
    h : Length(float)
    #: float with the hole diameter of this aperture in :py:attr:`unit` units. ``0`` for no hole.
    hole_dia : Length(float) = None

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Rectangle(x, y, self.unit.convert_to(unit, self.w), self.unit.convert_to(unit, self.h),
            rotation=0, polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<rect aperture {self.w:.3}x{self.h:.3} [{self.unit}]>'

    flash = _flash_hole

    def equivalent_width(self, unit=None):
        return self.unit.convert_to(unit, math.sqrt(self.w**2 + self.h**2))

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        if math.isclose(offset, 0, abs_tol=1e-6):
            return self
        return replace(self, w=self.w+2*offset, h=self.h+2*offset, hole_dia=None)

    @lru_cache()
    def rotated(self, angle=0):
        if math.isclose(angle % math.pi, 0, abs_tol=1e-6):
            return self
        elif math.isclose(angle % math.pi, math.pi/2, abs_tol=1e-6):
            return replace(self, w=self.h, h=self.w, hole_dia=self.hole_dia)
        else: # odd angle
            return self.to_macro(angle)

    def scaled(self, scale):
        return replace(self, 
                       w=self.w*scale,
                       h=self.h*scale,
                       hole_dia=None if self.hole_dia is None else self.hole_dia*scale)

    def to_macro(self, rotation=0):
        return ApertureMacroInstance(GenericMacros.rect,
                (MM(self.w, self.unit),
                    MM(self.h, self.unit),
                    MM(self.hole_dia, self.unit) or 0,
                    0,
                    rotation))

    def _params(self, unit=None):
        return _strip_right(
                self.unit.convert_to(unit, self.w),
                self.unit.convert_to(unit, self.h),
                self.unit.convert_to(unit, self.hole_dia))


@dataclass(frozen=True, slots=True)
class ObroundAperture(Aperture):
    """ Aperture whose shape is the convex hull of two circles of equal radii.

    Obrounds are specified through width and height of their bounding rectangle.. The smaller one of these will be the
    diameter of the obround's ends. If :py:attr:`w` is larger, the result will be a landscape obround. If :py:attr:`h`
    is larger, it will be a portrait obround.
    """ 
    _gerber_shape_code = 'O'
    _human_readable_shape = 'obround'
    #: float with the width of the bounding rectangle of this obround in :py:attr:`unit` units.
    w : Length(float)
    #: float with the height of the bounding rectangle of this obround in :py:attr:`unit` units.
    h : Length(float)
    #: float with the hole diameter of this aperture in :py:attr:`unit` units. ``0`` for no hole.
    hole_dia : Length(float) = None

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Line.from_obround(x, y, self.unit.convert_to(unit, self.w), self.unit.convert_to(unit, self.h),
            polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<obround aperture {self.w:.3}x{self.h:.3} [{self.unit}]>'

    flash = _flash_hole

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        if math.isclose(offset, 0, abs_tol=1e-6):
            return self
        return replace(self, w=self.w+2*offset, h=self.h+2*offset, hole_dia=None)

    @lru_cache()
    def rotated(self, angle=0):
        if math.isclose(angle % math.pi, 0, abs_tol=1e-6):
            return self
        elif math.isclose(angle % math.pi, math.pi/2, abs_tol=1e-6):
            return replace(self, w=self.h, h=self.w, hole_dia=self.hole_dia)
        else:
            return self.to_macro(angle)

    def scaled(self, scale):
        return replace(self, 
                       w=self.w*scale,
                       h=self.h*scale,
                       hole_dia=None if self.hole_dia is None else self.hole_dia*scale)

    def to_macro(self, rotation=0):
        # generic macro only supports w > h so flip x/y if h > w
        if self.w > self.h:
            inst = self
        else:
            rotation -= -math.pi/2
            inst = replace(self, w=self.h, h=self.w, hole_dia=self.hole_dia)

        return ApertureMacroInstance(GenericMacros.obround,
                (MM(inst.w, self.unit),
                 MM(inst.h, self.unit),
                 MM(inst.hole_dia, self.unit) or 0,
                 0,
                 rotation))

    def _params(self, unit=None):
        return _strip_right(
                self.unit.convert_to(unit, self.w),
                self.unit.convert_to(unit, self.h),
                self.unit.convert_to(unit, self.hole_dia))


@dataclass(frozen=True, slots=True)
class PolygonAperture(Aperture):
    """ Aperture whose shape is a regular n-sided polygon (e.g. pentagon, hexagon etc.). Note that this only supports
    round holes.
    """
    _gerber_shape_code = 'P'
    #: Diameter of circumscribing circle, i.e. the circle that all the polygon's corners lie on. In
    #: :py:attr:`unit` units.
    diameter : Length(float)
    #: Number of corners of this polygon. Three for a triangle, four for a square, five for a pentagon etc.
    n_vertices : int
    #: Rotation in radians.
    rotation : float = 0
    #: float with the hole diameter of this aperture in :py:attr:`unit` units. ``0`` for no hole.
    hole_dia : Length(float) = None

    def __post_init__(self):
        object.__setattr__(self, 'n_vertices', int(self.n_vertices))

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.ArcPoly.from_regular_polygon(x, y, self.unit.convert_to(unit, self.diameter)/2, self.n_vertices,
            rotation=self.rotation, polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<{self.n_vertices}-gon aperture d={self.diameter:.3} [{self.unit}]>'

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        if math.isclose(offset, 0, abs_tol=1e-6):
            return self
        return replace(self, diameter=self.diameter+2*offset, hole_dia=None)

    flash = _flash_hole

    @lru_cache()
    def rotated(self, angle=0):
        if angle != 0:
            return replace(self, rotation=self.rotation + angle)
        else:
            return self

    def scaled(self, scale):
        return replace(self, 
                       diameter=self.diameter*scale,
                       hole_dia=None if self.hole_dia is None else self.hole_dia*scale)

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.polygon, self._params(MM))

    def _params(self, unit=None):
        rotation = self.rotation % (2*math.pi / self.n_vertices)
        if math.isclose(rotation, 0, abs_tol=1e-6):
            rotation = None

        if self.hole_dia is not None:
            return self.unit.convert_to(unit, self.diameter), self.n_vertices, rotation, self.unit.convert_to(unit, self.hole_dia)
        elif rotation is not None and not math.isclose(rotation, 0, abs_tol=1e-6):
            return self.unit.convert_to(unit, self.diameter), self.n_vertices, rotation
        else:
            return self.unit.convert_to(unit, self.diameter), self.n_vertices

@dataclass(frozen=True, slots=True)
class ApertureMacroInstance(Aperture):
    """ One instance of an aperture macro. An aperture macro defined with an ``AM`` statement can be instantiated by
    multiple ``AD`` aperture definition statements using different parameters. An :py:class:`.ApertureMacroInstance` is
    one such binding of a macro to a particular set of parameters. Note that you still need an
    :py:class:`.ApertureMacroInstance` even if your :py:class:`.ApertureMacro` has no parameters since an
    :py:class:`.ApertureMacro` is not an :py:class:`.Aperture` by itself.
    """
    #: The :py:class:`.ApertureMacro` bound in this instance
    macro : object
    #: The parameters to the :py:class:`.ApertureMacro`. All elements should be floats or ints. The first item in the
    #: list is parameter ``$1``, the second is ``$2`` etc.
    parameters : tuple = ()

    @property
    def _gerber_shape_code(self):
        return self.macro.name

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        out = list(self.macro.to_graphic_primitives(
                offset=(x, y), rotation=0,
                parameters=self.parameters, unit=unit, polarity_dark=polarity_dark))
        return out

    def dilated(self, offset, unit=MM):
        if math.isclose(offset, 0, abs_tol=1e-6):
            return self
        return replace(self, macro=self.macro.dilated(offset, unit))

    @lru_cache()
    def rotated(self, angle=0.0):
        if math.isclose(angle % (2*math.pi), 0, abs_tol=1e-6):
            return self
        else:
            return self.to_macro(angle)

    def to_macro(self, rotation=0.0):
        return replace(self, macro=self.macro.rotated(rotation))

    def scaled(self, scale):
        return replace(self, macro=self.macro.scaled(scale))

    def calculate_out(self, unit=None, macro_name=None):
        return replace(self,
                       parameters=tuple(),
                       macro=self.macro.substitute_params(self._params(unit), unit, macro_name))

    def _params(self, unit=None):
        # We ignore "unit" here as we convert the actual macro, not this instantiation.
        # We do this because here we do not have information about which parameter has which physical units.
        parameters = self.parameters
        if len(parameters) > self.macro.num_parameters:
            warnings.warn(f'Aperture definition using macro {self.macro.name} has more parameters than the macro uses.')
            parameters = parameters[:self.macro.num_parameters]
        return tuple(parameters)

