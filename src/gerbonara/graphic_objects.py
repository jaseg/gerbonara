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

import math
import copy
from dataclasses import dataclass, astuple, field, fields
from itertools import zip_longest, pairwise, islice, cycle

from .utils import MM, InterpMode, to_unit, rotate_point, sum_bounds, approximate_arc, sweep_angle
from . import graphic_primitives as gp
from .aperture_macros import primitive as amp


def convert(value, src, dst):
        if src == dst or src is None or dst is None or value is None:
            return value
        elif dst == MM:
            return value * 25.4
        else:
            return value / 25.4

class Length:
    def __init__(self, obj_type):
        self.type = obj_type

    def __repr__(self):
        # This makes the automatically generated method signatures in the Sphinx docs look nice
        return 'float'

class GraphicObject:
    """ Base class for the graphic objects that make up a :py:class:`.GerberFile` or :py:class:`.ExcellonFile`. """

    # hackety hack: Work around python < 3.10 not having dataclasses.KW_ONLY. Once we drop python 3.8 and 3.9, we can
    # get rid of this, just set these as normal fields, and decorate GraphicObject with @dataclass.
    # 
    # See also: apertures.py, graphic_primitives.py
    def __init_subclass__(cls):
        #: bool representing the *color* of this feature: whether this is a *dark* or *clear* feature. Clear and dark are
        #: meant in the sense that they are used in the Gerber spec and refer to whether the transparency film that this
        #: file describes ends up black or clear at this spot. In a standard green PCB, a *polarity_dark=True* line will
        #: show up as copper on the copper layer, white ink on the silkscreen layer, or an opening on the soldermask layer.
        #: Clear features erase dark features, they are not transparent in the colloquial meaning. This property is ignored
        #: for features of an :py:class:`.ExcellonFile`.
        cls.polarity_dark = True

        #: :py:class:`.LengthUnit` used for all coordinate fields of this object (such as ``x`` or ``y``).
        cls.unit = None

        #: `dict` containing GerberX2 attributes attached to this feature. Note that this does not include file attributes,
        #: which are stored in the :py:class:`.GerberFile` object instead.
        cls.attrs = field(default_factory=dict)

        d = {'polarity_dark' : bool, 'unit' : str, 'attrs': dict}
        if hasattr(cls, '__annotations__'):
            cls.__annotations__.update(d)
        else:
            cls.__annotations__ = d


    def converted(self, unit):
        """ Convert this gerber object to another :py:class:`.LengthUnit`.

        :param unit: Either a :py:class:`.LengthUnit` instance or one of the strings ``'mm'`` or ``'inch'``.

        :returns: A copy of this object using the new unit. 
        """
        obj = copy.copy(self)
        obj.convert_to(unit)
        return obj

    def convert_to(self, unit):
        """ Convert this gerber object to another :py:class:`.LengthUnit` in-place.

        :param unit: Either a :py:class:`.LengthUnit` instance or one of the strings ``'mm'`` or ``'inch'``.
        """

        for f in fields(self):
            if type(f.type) is Length:
                setattr(self, f.name, self.unit.convert_to(unit, getattr(self, f.name)))

        self.unit = to_unit(unit)

    def offset(self, dx, dy, unit=MM):
        """ Add an offset to the location of this feature. The location can be given in either unit, and is
        automatically converted into this object's local unit.
        
        :param float dx: X offset, positive values move the object right.
        :param float dy: Y offset, positive values move the object up. This is the opposite of the normal screen
                         coordinate system used in SVG and other computer graphics APIs.
        """

        dx, dy = self.unit(dx, unit), self.unit(dy, unit)
        self._offset(dx, dy)

    def scale(self, factor, unit=MM):
        """ Scale this feature in both its dimensions and location.

        .. note:: The scale factor is a scalar, and the unit argument is irrelevant, but is kept for API consistency.
        
        .. note:: If this object references an aperture, this aperture is not modified. You will have to transform this
                  aperture yourself.

        :param float factor: Scale factor, 1 to keep the object as is, larger values to enlarge, smaller values to
                             shrink. Negative values are permitted.
        """

        self._scale(factor)

    def rotate(self, rotation, cx=0, cy=0, unit=MM):
        """ Rotate this object. The center of rotation can be given in either unit, and is automatically converted into
        this object's local unit.

        .. note:: The center's Y coordinate as well as the angle's polarity are flipped compared to computer graphics
                  convention since Gerber uses a bottom-to-top Y axis.

        .. note:: If this object references an aperture, this aperture is not modified. You will have to transform this
                  aperture yourself.

        :param float rotation: rotation in radians clockwise.
        :param float cx: X coordinate of center of rotation in *unit* units.
        :param float cy: Y coordinate of center of rotation. (0,0) is at the bottom left of the image.
        :param unit: :py:class:`.LengthUnit` or str with unit for *cx* and *cy*
        """

        cx, cy = self.unit(cx, unit), self.unit(cy, unit)
        self._rotate(rotation, cx, cy)

    def bounding_box(self, unit=None):
        """ Return axis-aligned bounding box of this object in given unit. If no unit is given, return the bounding box
        in the object's local unit (``self.unit``).

        .. note:: This method returns bounding boxes in a different format than legacy pcb-tools_, which used
                  ``(min_x, max_x), (min_y, max_y)``

        :param unit: :py:class:`.LengthUnit` or str with unit for return value.

        :returns: tuple of tuples of floats: ``(min_x, min_y), (max_x, max_y)``
        """

        return sum_bounds(p.bounding_box() for p in self.to_primitives(unit))

    def to_primitives(self, unit=None):
        """ Render this object into low-level graphical primitives (subclasses of :py:class:`.GraphicPrimitive`). This
        computes out all coordinates in case aperture macros are involved, and resolves units. The output primitives are
        converted into the given unit, and will be stripped of unit information. If no unit is given, use this object's
        native unit (``self.unit``).

        :param unit: :py:class:`.LengthUnit` or str with unit for return value.

        :rtype: Iterator[:py:class:`.GraphicPrimitive`]
        """

    def to_statements(self, gs):
        """ Serialize this object into Gerber statements.

        :param gs: :py:class:`~.rs274x.GraphicsState` object containing current Gerber state (polarity, selected
                             aperture, interpolation mode etc.).

        :returns: Iterator yielding one string per line of output Gerber
        :rtype: Iterator[str]
        """

    def to_xnc(self, ctx):
        """ Serialize this object into XNC Excellon statements.

        :param ctx: :py:class:`.ExcellonContext` object containing current Excellon state (selected tool,
                              interpolation mode etc.).

        :returns: Iterator yielding one string per line of output XNC code
        :rtype: Iterator[str]
        """


@dataclass
class Flash(GraphicObject):
    """ A flash is what happens when you "stamp" a Gerber aperture at some location. The :py:attr:`polarity_dark`
    attribute that Flash inherits from :py:class:`.GraphicObject` is ``True`` for normal flashes. If you set a Flash's
    ``polarity_dark`` to ``False``, you invert the polarity of all of its features.

    Flashes are also used to represent drilled holes in an :py:class:`.ExcellonFile`. In this case,
    :py:attr:`aperture` should be an instance of :py:class:`.ExcellonTool`.
    """

    #: float with X coordinate of the center of this flash.
    x : Length(float)

    #: float with Y coordinate of the center of this flash.
    y : Length(float)

    #: Flashed Aperture. must be a subclass of :py:class:`.Aperture`.
    aperture : object

    @property
    def tool(self):
        """ Alias for :py:attr:`aperture` for use inside an :py:class:`.ExcellonFile`. """
        return self.aperture

    @tool.setter
    def tool(self, value):
        self.aperture = value

    def bounding_box(self, unit=None):
        (min_x, min_y), (max_x, max_y) = self.aperture.bounding_box(unit)
        x, y = self.unit.convert_to(unit, self.x), self.unit.convert_to(unit, self.y)
        return (min_x+x, min_y+y), (max_x+x, max_y+y)

    @property
    def plated(self):
        """ (Excellon only) Returns if this is a plated hole. ``True`` (plated), ``False`` (non-plated) or ``None``
        (plating undefined)
        """
        return getattr(self.tool, 'plated', None)

    def _offset(self, dx, dy):
        self.x += dx
        self.y += dy

    def _rotate(self, rotation, cx=0, cy=0):
        self.x, self.y = gp.rotate_point(self.x, self.y, rotation, cx, cy)

    def _scale(self, factor):
        self.x *= factor
        self.y *= factor

    def to_primitives(self, unit=None):
        conv = self.converted(unit)
        yield from self.aperture.flash(conv.x, conv.y, unit, self.polarity_dark)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)

        x = gs.file_settings.write_gerber_value(self.x, self.unit)
        y = gs.file_settings.write_gerber_value(self.y, self.unit)
        yield f'X{x}Y{y}D03*'

        gs.update_point(self.x, self.y, unit=self.unit)

    def to_xnc(self, ctx):
        yield from ctx.select_tool(self.tool)
        yield from ctx.drill_mode()

        x = ctx.settings.write_excellon_value(self.x, self.unit)
        y = ctx.settings.write_excellon_value(self.y, self.unit)
        yield f'X{x}Y{y}'

        ctx.set_current_point(self.unit, self.x, self.y)

    # internally used to compute Excellon file path length
    def curve_length(self, unit=MM):
        return 0


class Region(GraphicObject):
    """ Gerber "region", roughly equivalent to what in computer graphics you would call a polygon. A region is a single
    filled area defined by a list of coordinates on its contour. A region's polarity is its "fill". A region does not
    have a "stroke", and thus does not have an `aperture` field. Note that regions are a strict subset of what modern
    computer graphics considers a polygon or path. Be careful when converting shapes from somewhere else into Gerber
    regions. For arbitrary shapes (e.g. SVG paths) this is non-trivial, and I recommend you hava look at Gerbolyze_ /
    svg-flatten_. Here's a list of special features of Gerber regions:

     * A region's outline consists of straigt line segments and circular arcs and must always be closed.
     * A region is always exactly one connected component.
     * A region must not overlap itself anywhere.
     * A region cannot have holes.
     * The last outline point of the region must be equal to the first.

    There is one exception from the last two rules: To emulate a region with a hole in it, *cut-ins* are allowed. At a
    cut-in, the region is allowed to touch (but never overlap!) itself.

    When ``arc_centers`` is empty, this region has only straight outline segments. When ``arc_centers`` is not empty,
    the i-th entry defines the i-th outline segment, with a ``None`` entry designating a straight line segment.
    An arc is defined by a ``(clockwise, (cx, cy))`` tuple, where ``clockwise`` can be ``True`` for a clockwise arc, or
    ``False`` for a counter-clockwise arc. ``cx`` and ``cy`` are the absolute coordinates of the arc's center. 
    """

    def __init__(self, outline=None, arc_centers=None, *, unit=MM, polarity_dark=True):
        self.unit = unit
        self.polarity_dark = polarity_dark
        self.outline = [] if outline is None else outline
        self.arc_centers = [] if arc_centers is None else arc_centers
        self.close()

    def __len__(self):
        return len(self.outline)

    def __bool__(self):
        return bool(self.outline)

    def __str__(self):
        return f'<Region with {len(self.outline)} points and {sum(1 if c else 0 for c in self.arc_centers)} arc segments at {hex(id(self))}'

    def _offset(self, dx, dy):
        self.outline = [ (x+dx, y+dy) for x, y in self.outline ]

    def _rotate(self, angle, cx=0, cy=0):
        self.outline = [ gp.rotate_point(x, y, angle, cx, cy) for x, y in self.outline ]
        self.arc_centers = [
                (arc[0], gp.rotate_point(*arc[1], angle, cx, cy)) if arc else None
                for arc in self.arc_centers ]

    def _scale(self, factor):
        self.outline = [ (x*factor, y*factor) for x, y in self.outline ]
        self.arc_centers = [
                (arc[0], (arc[1][0]*factor, arc[1][1]*factor)) if arc else None
                for p, arc in zip_longest(self.outline, self.arc_centers) ]

    def close(self):
        if self.outline and self.outline[-1] != self.outline[0]:
            self.outline.append(self.outline[-1])
            if self.arc_centers:
                self.arc_centers.append((None, (None, None)))

    @classmethod
    def from_rectangle(kls, x, y, w, h, unit=MM):
        return kls([
            (x, y),
            (x+w, y),
            (x+w, y+h),
            (x, y+h),
            ], unit=unit)

    @classmethod
    def from_arc_poly(kls, arc_poly, polarity_dark=True, unit=MM):
        return kls(arc_poly.outline, arc_poly.arc_centers, polarity_dark=polarity_dark, unit=unit)

    def append(self, obj):
        if obj.unit != self.unit:
            obj = obj.converted(self.unit)

        if not self.outline:
            self.outline.append(obj.p1)
        self.outline.append(obj.p2)

        if isinstance(obj, Arc):
            self.arc_centers.append((obj.clockwise, obj.center))
        else:
            self.arc_centers.append(None)

    def iter_segments(self, tolerance=1e-6):
        for points, arc in zip_longest(pairwise(self.outline), self.arc_centers):
            if arc:
                if points:
                    yield *points, arc
                else:
                    yield self.outline[-1], self.outline[0], arc
                    return
            else:
                if not points:
                    break
                yield *points, (None, (None, None))

        # Close outline if necessary.
        if math.dist(self.outline[0], self.outline[-1]) > tolerance:
            yield self.outline[-1], self.outline[0], (None, (None, None))

    def outline_objects(self, aperture=None):
        for p1, p2, (clockwise, center) in self.iter_segments():
            if clockwise is not None:
                yield Arc(*p1, *p2, *center, clockwise, aperture=aperture, unit=self.unit, polarity_dark=self.polarity_dark)
            else:
                yield Line(*p1, *p2, aperture=aperture, unit=self.unit, polarity_dark=self.polarity_dark)

    def _aperture_macro_primitives(self, max_error=1e-2, clip_max_error=True, unit=MM):
        # unit is only for max_error, the resulting primitives will always be in MM
        
        if len(self.outline) < 2:
            return

        points = []
        for p1, p2, (clockwise, center) in self.iter_segments():
            if clockwise is not None:
                for p in approximate_arc(*center, *p1, *p2, clockwise,
                                             max_error=max_error, clip_max_error=clip_max_error):
                    points.append(p)
                    points.pop()
            else:
                points.append(p1)
        points.append(p2)

        if points[0] != points[-1]:
            points.append(points[0])

        yield amp.Outline(self.unit, int(self.polarity_dark), len(points)-1, tuple(coord for p in points for coord in p))

    def to_primitives(self, unit=None):
        if unit == self.unit:
            yield gp.ArcPoly(outline=self.outline, arc_centers=self.arc_centers, polarity_dark=self.polarity_dark)

        else:
            to = lambda value: self.unit.convert_to(unit, value)
            conv_outline = [ (to(x), to(y)) for x, y in self.outline ]
            convert_entry = lambda entry: (entry[0], (to(entry[1][0]), to(entry[1][1])))
            conv_arc = [ None if entry is None else convert_entry(entry) for entry in self.arc_centers ]

            yield gp.ArcPoly(conv_outline, conv_arc, polarity_dark=self.polarity_dark)

    def to_statements(self, gs):
        if len(self.outline) < 3:
            return

        yield from gs.set_polarity(self.polarity_dark)
        yield 'G36*'
        # Repeat interpolation mode at start of region statement to work around gerbv bug. Without this, gerbv will
        # not display a region consisting of only a single arc.
        # TODO report gerbv issue upstream
        yield gs.interpolation_mode_statement() + '*'

        yield from gs.set_current_point(self.outline[0], unit=self.unit)

        for previous_point, point, (clockwise, center) in self.iter_segments():
            if point is None and center is None:
                break

            x = gs.file_settings.write_gerber_value(point[0], self.unit)
            y = gs.file_settings.write_gerber_value(point[1], self.unit)

            if clockwise is None:
                yield from gs.set_interpolation_mode(InterpMode.LINEAR)
                yield f'X{x}Y{y}D01*'

            else:
                yield from gs.set_interpolation_mode(InterpMode.CIRCULAR_CW if clockwise else InterpMode.CIRCULAR_CCW)
                i = gs.file_settings.write_gerber_value(center[0]-previous_point[0], self.unit)
                j = gs.file_settings.write_gerber_value(center[1]-previous_point[1], self.unit)
                yield f'X{x}Y{y}I{i}J{j}D01*'

            gs.update_point(*point, unit=self.unit)

        yield 'G37*'

@dataclass
class Line(GraphicObject):
    """ A line is what happens when you "drag" a Gerber :py:class:`.Aperture` from one point to another. Note that
    Gerber lines are substantially funkier than normal lines as we know them from modern computer graphics such as SVG.
    A Gerber line is defined as the area that is covered when you drag its aperture along. This means that for a
    rectangular aperture, a horizontal line and a vertical line using the same aperture will have different widths.

    .. warning:: Try to only ever use :py:class:`.CircleAperture` with :py:class:`~.graphic_objects.Line` and
                 :py:class:`~.graphic_objects.Arc` since other aperture types are not widely supported by renderers /
                 photoplotters even though they are part of the spec.

    .. note:: If you manipulate a :py:class:`~.graphic_objects.Line`, it is okay to assume that it has round end caps
              and a defined width as exceptions are really rare.
    """

    #: X coordinate of start point
    x1 : Length(float)
    #: Y coordinate of start point
    y1 : Length(float)
    #: X coordinate of end point
    x2 : Length(float)
    #: Y coordinate of end point
    y2 : Length(float)
    #: Aperture for this line. Should be a subclass of :py:class:`.CircleAperture`, whose diameter determines the line
    #: width.
    aperture : object

    def _offset(self, dx, dy):
        self.x1 += dx
        self.y1 += dy
        self.x2 += dx
        self.y2 += dy

    def _rotate(self, rotation, cx=0, cy=0):
        self.x1, self.y1 = gp.rotate_point(self.x1, self.y1, rotation, cx, cy)
        self.x2, self.y2 = gp.rotate_point(self.x2, self.y2, rotation, cx, cy)

    def _scale(self, factor):
        self.x1 *= factor
        self.y1 *= factor
        self.x2 *= factor
        self.y2 *= factor

    @property
    def p1(self):
        """ Convenience alias for ``(self.x1, self.y1)`` returning start point of the line. """
        return self.x1, self.y1

    @property
    def p2(self):
        """ Convenience alias for ``(self.x2, self.y2)`` returning end point of the line. """
        return self.x2, self.y2

    @property
    def tool(self):
        """ Alias for :py:attr:`aperture` for use inside an :py:class:`.ExcellonFile`. """
        return self.aperture

    @tool.setter
    def tool(self, value):
        self.aperture = value

    @property
    def plated(self):
        """ (Excellon only) Returns if this is a plated hole. ``True`` (plated), ``False`` (non-plated) or ``None``
        (plating undefined)
        """
        return self.tool.plated

    def as_primitive(self, unit=None):
        conv = self.converted(unit)
        w = self.aperture.equivalent_width(unit) if self.aperture else 0.1 # for debugging
        return gp.Line(*conv.p1, *conv.p2, w, polarity_dark=self.polarity_dark)

    def to_primitives(self, unit=None):
        yield self.as_primitive(unit=unit)

    def _aperture_macro_primitives(self):
        obj = self.converted(MM) # Gerbonara aperture macros use MM units.
        width = obj.aperture.equivalent_width(MM)
        yield amp.VectorLine(MM, int(self.polarity_dark), width, obj.x1, obj.y1, obj.x2, obj.y2, 0)
        yield amp.Circle(MM, int(self.polarity_dark), width, obj.x1, obj.y1)
        yield amp.Circle(MM, int(self.polarity_dark), width, obj.x2, obj.y2)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)
        yield from gs.set_interpolation_mode(InterpMode.LINEAR)
        yield from gs.set_current_point(self.p1, unit=self.unit)

        x = gs.file_settings.write_gerber_value(self.x2, self.unit)
        y = gs.file_settings.write_gerber_value(self.y2, self.unit)
        yield f'X{x}Y{y}D01*'

        gs.update_point(*self.p2, unit=self.unit)

    def to_xnc(self, ctx):
        yield from ctx.select_tool(self.tool)
        yield from ctx.route_mode(self.unit, *self.p1)

        x = ctx.settings.write_excellon_value(self.x2, self.unit)
        y = ctx.settings.write_excellon_value(self.y2, self.unit)
        yield f'G01X{x}Y{y}'

        ctx.set_current_point(self.unit, *self.p2)

    # internally used to compute Excellon file path length
    def curve_length(self, unit=MM):
        return self.unit.convert_to(unit, math.dist(self.p1, self.p2))


@dataclass
class Arc(GraphicObject):
    """ Like :py:class:`~.graphic_objects.Line`, but a circular arc. Has start ``(x1, y1)`` and end ``(x2, y2)``
    attributes like a :py:class:`~.graphic_objects.Line`, but additionally has a center ``(cx, cy)`` specified relative
    to the start point ``(x1, y1)``, as well as a ``clockwise`` attribute indicating the arc's direction.

    .. note:: The same warning on apertures that applies to :py:class:`~.graphic_objects.Line` applies to
              :py:class:`~.graphic_objects.Arc`, too.
    
    .. warning:: When creating your own circles, you have to take care yourself that the center is actually the center
                 of a circle that goes through both (x1,y1) and (x2,y2). Elliptical arcs are *not* supported by either
                 us or the Gerber standard.
    """
    #: X coordinate of start point
    x1 : Length(float)
    #: Y coordinate of start point
    y1 : Length(float)
    #: X coordinate of end point
    x2 : Length(float)
    #: Y coordinate of end point
    y2 : Length(float)
    #: X coordinate of arc center relative to ``x1``
    cx : Length(float)
    #: Y coordinate of arc center relative to ``x1``
    cy : Length(float)
    #: Direction of arc. ``True`` means clockwise. For a given center coordinate and endpoints there are always two
    #: possible arcs, the large one and the small one. Flipping this switches between them.
    clockwise : bool
    #: Aperture for this arc. Should be a subclass of :py:class:`.CircleAperture`, whose diameter determines the line
    #: width.
    aperture : object

    @classmethod
    def from_circle(kls, cx, cy, r, aperture, unit=MM):
        return kls(cx-r, cy, cx-r, cy, r, 0, aperture=aperture, clockwise=True, unit=MM)
    
    def _offset(self, dx, dy):
        self.x1 += dx
        self.y1 += dy
        self.x2 += dx
        self.y2 += dy

    def numeric_error(self, unit=None):
        """ Gerber arcs are sligtly over-determined. Since we have not just a radius, but center X and Y coordinates, an
        "impossible" arc can be specified, where the start and end points do not lie on a circle around its center. This
        function returns the absolute difference between the two radii (start - center) and (end - center) as an
        indication on how bad this arc is.

        .. note:: For arcs read from a Gerber file, this value can easily be in the order of magnitude of 1e-4. Gerber
                  files have very limited numerical resolution, and rounding errors will necessarily lead to numerical
                  accuracy issues with arcs.

        :rtype: float
        """
        # This function is used internally to determine the right arc in multi-quadrant mode
        conv = self.converted(unit)
        cx, cy = conv.cx + conv.x1, conv.cy + conv.y1
        r1 = math.dist((cx, cy), conv.p1)
        r2 = math.dist((cx, cy), conv.p2)
        return abs(r1 - r2)

    def sweep_angle(self):
        """ Calculate absolute sweep angle of arc. This is always a positive number.

        :returns: Angle in clockwise radian between ``0`` and ``2*math.pi``
        :rtype: float
        """

        return sweep_angle(self.cx+self.x1, self.cy+self.y1, self.x1, self.y1, self.x2, self.y2, self.clockwise)

    @property
    def p1(self):
        """ Convenience alias for ``(self.x1, self.y1)`` returning start point of the arc. """
        return self.x1, self.y1

    @property
    def p2(self):
        """ Convenience alias for ``(self.x2, self.y2)`` returning end point of the arc. """
        return self.x2, self.y2

    @property
    def center(self):
        """ Returns the center of the arc in **absolute** coordinates.

        :returns: ``(self.x1 + self.cx, self.y1 + self.cy)``
        :rtype: tuple(float)
        """
        return self.cx + self.x1, self.cy + self.y1

    @property
    def center_relative(self):
        """ Returns the center of the arc in relative coordinates.

        :returns: ``(self.cx, self.cy)``
        :rtype: tuple(float)
        """
        return self.cx, self.cy

    @property
    def tool(self):
        """ Alias for :py:attr:`aperture` for use inside an :py:class:`.ExcellonFile`. """
        return self.aperture

    @tool.setter
    def tool(self, value):
        self.aperture = value

    @property
    def plated(self):
        """ (Excellon only) Returns if this is a plated hole. ``True`` (plated), ``False`` (non-plated) or ``None``
        (plating undefined)
        """
        return self.tool.plated

    def approximate(self, max_error=1e-2, unit=MM, clip_max_error=True):
        """ Approximate this :py:class:`~.graphic_objects.Arc` using a list of multiple
        :py:class:`~.graphic_objects.Line`  instances to the given precision.

        :param float max_error: Maximum approximation error in ``unit`` units.
        :param unit: Either a :py:class:`.LengthUnit` instance or one of the strings ``'mm'`` or ``'inch'``.
        :param bool clip_max_error: Clip max error such that at least a square is always rendered.

        :returns: list of :py:class:`~.graphic_objects.Line` instances.
        :rtype: list
        """

        max_error = self.unit(max_error, unit)
        return [Line(*p1, *p2, aperture=self.aperture, polarity_dark=self.polarity_dark, unit=self.unit)
                for p1, p2 in pairwise(approximate_arc(
                    self.cx+self.x1, self.cy+self.y1,
                    self.x1, self.y1,
                    self.x2, self.y2,
                    self.clockwise,
                    max_error=max_error,
                    clip_max_error=clip_max_error))]

    def _rotate(self, rotation, cx=0, cy=0):
        # rotate center first since we need old x1, y1 here
        new_cx, new_cy = gp.rotate_point(*self.center, rotation, cx, cy)
        self.x1, self.y1 = gp.rotate_point(self.x1, self.y1, rotation, cx, cy)
        self.x2, self.y2 = gp.rotate_point(self.x2, self.y2, rotation, cx, cy)
        self.cx, self.cy = new_cx - self.x1, new_cy - self.y1

    def _scale(self, factor):
        self.x1 *= factor
        self.y1 *= factor
        self.x2 *= factor
        self.y2 *= factor
        self.cx *= factor
        self.cy *= factor

    def as_primitive(self, unit=None):
        conv = self.converted(unit)
        w = self.aperture.equivalent_width(unit) if self.aperture else 0
        return gp.Arc(x1=conv.x1, y1=conv.y1,
                x2=conv.x2, y2=conv.y2,
                cx=conv.cx+conv.x1, cy=conv.cy+conv.y1,
                clockwise=self.clockwise,
                width=w,
                polarity_dark=self.polarity_dark)

    def to_primitives(self, unit=None):
        yield self.as_primitive(unit=unit)

    def to_region(self):
        reg = Region(unit=self.unit, polarity_dark=self.polarity_dark)
        reg.append(self)
        reg.close()
        return reg

    def _aperture_macro_primitives(self, max_error=1e-2, unit=MM):
        # unit is only for max_error, the resulting primitives will always be in MM
        for line in self.approximate(max_error=max_error, unit=unit):
            yield from line._aperture_macro_primitives()

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield from gs.set_aperture(self.aperture)
        # TODO is the following line correct?
        yield from gs.set_interpolation_mode(InterpMode.CIRCULAR_CW if self.clockwise else InterpMode.CIRCULAR_CCW)
        yield from gs.set_current_point(self.p1, unit=self.unit)

        x = gs.file_settings.write_gerber_value(self.x2, self.unit)
        y = gs.file_settings.write_gerber_value(self.y2, self.unit)
        i = gs.file_settings.write_gerber_value(self.cx, self.unit)
        j = gs.file_settings.write_gerber_value(self.cy, self.unit)
        yield f'X{x}Y{y}I{i}J{j}D01*'

        gs.update_point(*self.p2, unit=self.unit)

    def to_xnc(self, ctx):
        yield from ctx.select_tool(self.tool)
        yield from ctx.route_mode(self.unit, self.x1, self.y1)
        code = 'G02' if self.clockwise else 'G03'

        x = ctx.settings.write_excellon_value(self.x2, self.unit)
        y = ctx.settings.write_excellon_value(self.y2, self.unit)
        i = ctx.settings.write_excellon_value(self.cx, self.unit)
        j = ctx.settings.write_excellon_value(self.cy, self.unit)
        yield f'{code}X{x}Y{y}I{i}J{j}'

        ctx.set_current_point(self.unit, self.x2, self.y2)

    # internally used to compute Excellon file path length
    def curve_length(self, unit=MM):
        return self.unit.convert_to(unit, math.hypot(self.cx, self.cy) * self.sweep_angle)


