#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
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
from dataclasses import dataclass, replace, field, fields, InitVar, KW_ONLY

from .aperture_macros.parse import GenericMacros
from .utils import MM, Inch

from . import graphic_primitives as gp


def _flash_hole(self, x, y, unit=None, polarity_dark=True):
    if getattr(self, 'hole_rect_h', None) is not None:
        w, h = self.unit.convert_to(unit, self.hole_dia), self.unit.convert_to(unit, self.hole_rect_h)
        return [*self._primitives(x, y, unit, polarity_dark),
                gp.Rectangle(x, y, w, h, rotation=self.rotation, polarity_dark=(not polarity_dark))]
    elif self.hole_dia is not None:
        return [*self._primitives(x, y, unit, polarity_dark),
                gp.Circle(x, y, self.unit.convert_to(unit, self.hole_dia/2), polarity_dark=(not polarity_dark))]
    else:
        return self._primitives(x, y, unit, polarity_dark)

def _strip_right(*args):
    args = list(args)
    while args and args[-1] is None:
        args.pop()
    return args

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

@dataclass
class Aperture:
    """ Base class for all apertures. """
    _ : KW_ONLY
    #: :py:class:`gerbonara.utils.LengthUnit` used for all length fields of this aperture.
    unit : str = None
    #: GerberX2 attributes of this aperture. Note that this will only contain aperture attributes, not file attributes.
    #: File attributes are stored in the :py:attr:`~.GerberFile.attrs` of the :py:class:`.GerberFile`.
    attrs : dict = field(default_factory=dict)
    #: Aperture index this aperture had when it was read from the Gerber file. This field is purely informational since
    #: apertures are de-duplicated and re-numbered when writing a Gerber file. For `D10`, this field would be `10`. When
    #: you programmatically create a new aperture, you do not have to set this.
    original_number : int = None

    @property
    def hole_shape(self):
        """ Get shape of hole based on :py:attr:`hole_dia` and :py:attr:`hole_rect_h`: "rect" or "circle" or None. """
        if getattr(self, 'hole_rect_h') is not None:
            return 'rect'
        elif getattr(self, 'hole_dia') is not None:
            return 'circle'
        else:
            return None

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

    def equivalent_width(self, unit=None):
        """ Get the width of a line interpolated using this aperture in the given :py:class:`~.LengthUnit`.

        :rtype: float
        """
        raise ValueError('Non-circular aperture used in interpolation statement, line width is not properly defined.')

    def to_gerber(self, settings=None):
        """ Return the Gerber aperture definition for this aperture using the given :py:class:`.FileSettings`.

        :rtype: str
        """
        # Hack: The standard aperture shapes C, R, O do not have a rotation parameter. To make this API easier to use,
        # we emulate this parameter. Our circle, rectangle and oblong classes below have a rotation parameter. Only at
        # export time during to_gerber, this parameter is evaluated. 
        unit = settings.unit if settings else None
        actual_inst = self._rotated()
        params = 'X'.join(f'{float(par):.4}' for par in actual_inst._params(unit) if par is not None)
        if params:
            return f'{actual_inst._gerber_shape_code},{params}'
        else:
            return actual_inst._gerber_shape_code

    def to_macro(self):
        """ Convert this :py:class:`.Aperture` into an :py:class:`.ApertureMacro` inside an
        :py:class:`.ApertureMacroInstance`.
        """
        raise NotImplementedError()

    def __eq__(self, other):
        """ Compare two apertures. Apertures are compared based on their Gerber representation. Two apertures are
        considered equal if their Gerber aperture definitions are identical.
        """
        # We need to choose some unit here.
        return hasattr(other, 'to_gerber') and self.to_gerber(MM) == other.to_gerber(MM)

    def _rotate_hole_90(self):
        if self.hole_rect_h is None:
            return {'hole_dia': self.hole_dia, 'hole_rect_h': None}
        else:
            return {'hole_dia': self.hole_rect_h, 'hole_rect_h': self.hole_dia}

@dataclass(unsafe_hash=True)
class ExcellonTool(Aperture):
    """ Special Aperture_ subclass for use in :py:class:`.ExcellonFile`. Similar to :py:class:`.CircleAperture`, but
    does not have :py:attr:`.CircleAperture.hole_dia` or :py:attr:`.CircleAperture.hole_rect_h`, and has the additional
    :py:attr:`plated` attribute.
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

    def __eq__(self, other):
        """ Compare two :py:class:`.ExcellonTool` instances. They are considered equal if their diameter and plating
        match.
        """
        if not isinstance(other, ExcellonTool):
            return False

        if not self.plated == other.plated:
            return False

        return _none_close(self.diameter, self.unit(other.diameter, other.unit))

    def __str__(self):
        plated = '' if self.plated is None else (' plated' if self.plated else ' non-plated')
        return f'<Excellon Tool d={self.diameter:.3f}{plated} [{self.unit}]>'

    def equivalent_width(self, unit=MM):
        return unit(self.diameter, self.unit)

    # Internal use, for layer dilation.
    def dilated(self, offset, unit=MM):
        offset = unit(offset, self.unit)
        return replace(self, diameter=self.diameter+2*offset)

    def _rotated(self):
        return self

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.circle, self._params(unit=MM))

    def _params(self, unit=None):
        return [self.unit.convert_to(unit, self.diameter)]


@dataclass
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
    #: float or None. If not None, specifies a rectangular hole of size `hole_dia * hole_rect_h` instead of a round hole.
    hole_rect_h : Length(float) = None
    # float with radians. This is only used for rectangular holes (as circles are rotationally symmetric).
    rotation : float = 0

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Circle(x, y, self.unit.convert_to(unit, self.diameter/2), polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<circle aperture d={self.diameter:.3} [{self.unit}]>'

    flash = _flash_hole

    def equivalent_width(self, unit=None):
        return self.unit.convert_to(unit, self.diameter)

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        return replace(self, diameter=self.diameter+2*offset, hole_dia=None, hole_rect_h=None)

    def _rotated(self):
        if math.isclose(self.rotation % (2*math.pi), 0) or self.hole_rect_h is None:
            return self
        else:
            return self.to_macro(self.rotation)

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.circle, self._params(unit=MM))

    def _params(self, unit=None):
        return _strip_right(
                self.unit.convert_to(unit, self.diameter),
                self.unit.convert_to(unit, self.hole_dia),
                self.unit.convert_to(unit, self.hole_rect_h))


@dataclass
class RectangleAperture(Aperture):
    _gerber_shape_code = 'R'
    _human_readable_shape = 'rect'
    #: float with the width of the rectangle in :py:attr:`unit` units.
    w : Length(float)
    #: float with the height of the rectangle in :py:attr:`unit` units.
    h : Length(float)
    #: float with the hole diameter of this aperture in :py:attr:`unit` units. ``0`` for no hole.
    hole_dia : Length(float) = None
    #: float or None. If not None, specifies a rectangular hole of size `hole_dia * hole_rect_h` instead of a round hole.
    hole_rect_h : Length(float) = None
    # Rotation in radians. This rotates both the aperture and the rectangular hole if it has one.
    rotation : float = 0 # radians

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Rectangle(x, y, self.unit.convert_to(unit, self.w), self.unit.convert_to(unit, self.h),
            rotation=self.rotation, polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<rect aperture {self.w:.3}x{self.h:.3} [{self.unit}]>'

    flash = _flash_hole

    def equivalent_width(self, unit=None):
        return self.unit.convert_to(unit, math.sqrt(self.w**2 + self.h**2))

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        return replace(self, w=self.w+2*offset, h=self.h+2*offset, hole_dia=None, hole_rect_h=None)

    def _rotated(self):
        if math.isclose(self.rotation % math.pi, 0):
            return self
        elif math.isclose(self.rotation % math.pi, math.pi/2):
            return replace(self, w=self.h, h=self.w, **self._rotate_hole_90(), rotation=0)
        else: # odd angle
            return self.to_macro()

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.rect,
                [MM(self.w, self.unit),
                    MM(self.h, self.unit),
                    MM(self.hole_dia, self.unit) or 0,
                    MM(self.hole_rect_h, self.unit) or 0,
                    self.rotation])

    def _params(self, unit=None):
        return _strip_right(
                self.unit.convert_to(unit, self.w),
                self.unit.convert_to(unit, self.h),
                self.unit.convert_to(unit, self.hole_dia),
                self.unit.convert_to(unit, self.hole_rect_h))


@dataclass
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
    #: float or None. If not None, specifies a rectangular hole of size `hole_dia * hole_rect_h` instead of a round hole.
    hole_rect_h : Length(float) = None
    #: Rotation in radians. This rotates both the aperture and the rectangular hole if it has one.
    rotation : float = 0

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.Line.from_obround(x, y, self.unit.convert_to(unit, self.w), self.unit.convert_to(unit, self.h),
            rotation=self.rotation, polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<obround aperture {self.w:.3}x{self.h:.3} [{self.unit}]>'

    flash = _flash_hole

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        return replace(self, w=self.w+2*offset, h=self.h+2*offset, hole_dia=None, hole_rect_h=None)

    def _rotated(self):
        if math.isclose(self.rotation % math.pi, 0):
            return self
        elif math.isclose(self.rotation % math.pi, math.pi/2):
            return replace(self, w=self.h, h=self.w, **self._rotate_hole_90(), rotation=0)
        else:
            return self.to_macro()

    def to_macro(self):
        # generic macro only supports w > h so flip x/y if h > w
        inst = self if self.w > self.h else replace(self, w=self.h, h=self.w, **_rotate_hole_90(self), rotation=self.rotation-90)
        return ApertureMacroInstance(GenericMacros.obround,
                [MM(inst.w, self.unit),
                 MM(ints.h, self.unit),
                 MM(inst.hole_dia, self.unit),
                 MM(inst.hole_rect_h, self.unit),
                 inst.rotation])

    def _params(self, unit=None):
        return _strip_right(
                self.unit.convert_to(unit, self.w),
                self.unit.convert_to(unit, self.h),
                self.unit.convert_to(unit, self.hole_dia),
                self.unit.convert_to(unit, self.hole_rect_h))


@dataclass
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
        self.n_vertices = int(self.n_vertices)

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        return [ gp.ArcPoly.from_regular_polygon(x, y, self.unit.convert_to(unit, self.diameter)/2, self.n_vertices,
            rotation=self.rotation, polarity_dark=polarity_dark) ]

    def __str__(self):
        return f'<{self.n_vertices}-gon aperture d={self.diameter:.3} [{self.unit}]>'

    def dilated(self, offset, unit=MM):
        offset = self.unit(offset, unit)
        return replace(self, diameter=self.diameter+2*offset, hole_dia=None)

    flash = _flash_hole

    def _rotated(self):
        return self

    def to_macro(self):
        return ApertureMacroInstance(GenericMacros.polygon, self._params(MM))

    def _params(self, unit=None):
        rotation = self.rotation % (2*math.pi / self.n_vertices) if self.rotation is not None else None
        if self.hole_dia is not None:
            return self.unit.convert_to(unit, self.diameter), self.n_vertices, rotation, self.unit.convert_to(unit, self.hole_dia)
        elif rotation is not None and not math.isclose(rotation, 0):
            return self.unit.convert_to(unit, self.diameter), self.n_vertices, rotation
        else:
            return self.unit.convert_to(unit, self.diameter), self.n_vertices

@dataclass
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
    parameters : list
    #: Aperture rotation in radians. When saving, a copy of the :py:class:`.ApertureMacro` is re-written with this
    #: rotation.
    rotation : float = 0

    @property
    def _gerber_shape_code(self):
        return self.macro.name

    def _primitives(self, x, y, unit=None, polarity_dark=True):
        out = list(self.macro.to_graphic_primitives(
                offset=(x, y), rotation=self.rotation,
                parameters=self.parameters, unit=unit, polarity_dark=polarity_dark))
        return out

    def dilated(self, offset, unit=MM):
        return replace(self, macro=self.macro.dilated(offset, unit))

    def _rotated(self):
        if math.isclose(self.rotation % (2*math.pi), 0):
            return self
        else:
            return self.to_macro()

    def to_macro(self):
        return replace(self, macro=self.macro.rotated(self.rotation), rotation=0)

    def __eq__(self, other):
        return hasattr(other, 'macro') and self.macro == other.macro and \
                hasattr(other, 'params') and self.params == other.params and \
                hasattr(other, 'rotation') and self.rotation == other.rotation

    def _params(self, unit=None):
        # We ignore "unit" here as we convert the actual macro, not this instantiation.
        # We do this because here we do not have information about which parameter has which physical units.
        return tuple(self.parameters)


