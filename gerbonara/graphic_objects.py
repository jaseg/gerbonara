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
import copy
from dataclasses import dataclass, KW_ONLY, astuple, replace, field, fields

from .utils import MM, InterpMode, to_unit, rotate_point
from . import graphic_primitives as gp


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

@dataclass
class GraphicObject:
    """ Base class for the graphic objects that make up a :py:class:`.GerberFile` or :py:class:`.ExcellonFile`. """
    _ : KW_ONLY

    #: bool representing the *color* of this feature: whether this is a *dark* or *clear* feature. Clear and dark are
    #: meant in the sense that they are used in the Gerber spec and refer to whether the transparency film that this
    #: file describes ends up black or clear at this spot. In a standard green PCB, a *polarity_dark=True* line will
    #: show up as copper on the copper layer, white ink on the silkscreen layer, or an opening on the soldermask layer.
    #: Clear features erase dark features, they are not transparent in the colloquial meaning. This property is ignored
    #: for features of an :py:class:`.ExcellonFile`.
    polarity_dark : bool = True

    #: :py:class:`.LengthUnit` used for all coordinate fields of this object (such as ``x`` or ``y``).
    unit : str = None


    #: `dict` containing GerberX2 attributes attached to this feature. Note that this does not include file attributes,
    #: which are stored in the :py:class:`.GerberFile` object instead.
    attrs : dict = field(default_factory=dict)

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

    def rotate(self, rotation, cx=0, cy=0, unit=MM):
        """ Rotate this object. The center of rotation can be given in either unit, and is automatically converted into
        this object's local unit.

        .. note:: The center's Y coordinate as well as the angle's polarity are flipped compared to computer graphics
                  convention since Gerber uses a bottom-to-top Y axis.

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

        bboxes = [ p.bounding_box() for p in self.to_primitives(unit) ]
        min_x = min(min_x for (min_x, _min_y), _ in bboxes)
        min_y = min(min_y for (_min_x, min_y), _ in bboxes)
        max_x = max(max_x for _, (max_x, _max_y) in bboxes)
        max_y = max(max_y for _, (_max_x, max_y) in bboxes)
        return ((min_x, min_y), (max_x, max_y))

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

    There is one exception from the last two rules: To emulate a region with a hole in it, *cut-ins* are allowed. At a
    cut-in, the region is allowed to touch (but never overlap!) itself.

    :attr poly: :py:class:`~.graphic_primitives.ArcPoly` describing the actual outline of this Region. The coordinates of
                this poly are in the unit of this instance's :py:attr:`unit` field.
    """

    def __init__(self, outline=None, arc_centers=None, *, unit, polarity_dark):
        super().__init__(unit=unit, polarity_dark=polarity_dark)
        outline = [] if outline is None else outline
        arc_centers = [] if arc_centers is None else arc_centers
        self.poly = gp.ArcPoly(outline, arc_centers)

    def __len__(self):
        return len(self.poly)

    def __bool__(self):
        return bool(self.poly)

    def _offset(self, dx, dy):
        self.poly.outline = [ (x+dx, y+dy) for x, y in self.poly.outline ]

    def _rotate(self, angle, cx=0, cy=0):
        self.poly.outline = [ gp.rotate_point(x, y, angle, cx, cy) for x, y in self.poly.outline ]
        self.poly.arc_centers = [
                (arc[0], gp.rotate_point(*arc[1], angle, cx-p[0], cy-p[1])) if arc else None
                for p, arc in zip(self.poly.outline, self.poly.arc_centers) ]

    def append(self, obj):
        if obj.unit != self.unit:
            obj = obj.converted(self.unit)

        if not self.poly.outline:
            self.poly.outline.append(obj.p1)
        self.poly.outline.append(obj.p2)

        if isinstance(obj, Arc):
            self.poly.arc_centers.append((obj.clockwise, obj.center_relative))
        else:
            self.poly.arc_centers.append(None)

    def to_primitives(self, unit=None):
        self.poly.polarity_dark = self.polarity_dark # FIXME: is this the right spot to do this?
        if unit == self.unit:
            yield self.poly

        else:
            to = lambda value: self.unit.convert_to(unit, value)
            conv_outline = [ (to(x), to(y)) for x, y in self.poly.outline ]
            convert_entry = lambda entry: (entry[0], (to(entry[1][0]), to(entry[1][1])))
            conv_arc = [ None if entry is None else convert_entry(entry) for entry in self.poly.arc_centers ]

            yield gp.ArcPoly(conv_outline, conv_arc, polarity_dark=self.polarity_dark)

    def to_statements(self, gs):
        yield from gs.set_polarity(self.polarity_dark)
        yield 'G36*'
        # Repeat interpolation mode at start of region statement to work around gerbv bug. Without this, gerbv will
        # not display a region consisting of only a single arc.
        # TODO report gerbv issue upstream
        yield gs.interpolation_mode_statement() + '*'

        yield from gs.set_current_point(self.poly.outline[0], unit=self.unit)

        for point, arc_center in zip(self.poly.outline[1:], self.poly.arc_centers):
            if arc_center is None:
                yield from gs.set_interpolation_mode(InterpMode.LINEAR)

                x = gs.file_settings.write_gerber_value(point[0], self.unit)
                y = gs.file_settings.write_gerber_value(point[1], self.unit)
                yield f'X{x}Y{y}D01*'

                gs.update_point(*point, unit=self.unit)

            else:
                clockwise, (cx, cy) = arc_center
                x2, y2 = point
                yield from gs.set_interpolation_mode(InterpMode.CIRCULAR_CW if clockwise else InterpMode.CIRCULAR_CCW)

                x = gs.file_settings.write_gerber_value(x2, self.unit)
                y = gs.file_settings.write_gerber_value(y2, self.unit)
                # TODO are these coordinates absolute or relative now?!
                i = gs.file_settings.write_gerber_value(cx, self.unit)
                j = gs.file_settings.write_gerber_value(cy, self.unit)
                yield f'X{x}Y{y}I{i}J{j}D01*'

                gs.update_point(x2, y2, unit=self.unit)

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

    def to_primitives(self, unit=None):
        conv = self.converted(unit)
        w = self.aperture.equivalent_width(unit) if self.aperture else 0.1 # for debugging
        yield gp.Line(*conv.p1, *conv.p2, w, polarity_dark=self.polarity_dark)

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
        cx, cy = self.cx + self.x1, self.cy + self.y1
        x1, y1 = self.x1 - cx, self.y1 - cy
        x2, y2 = self.x2 - cx, self.y2 - cy

        a1, a2 = math.atan2(y1, x1), math.atan2(y2, x2)
        f = abs(a2 - a1)
        if not self.clockwise:
            if a2 > a1:
                return a2 - a1
            else:
                return 2*math.pi - abs(a2 - a1)
        else:
            if a1 > a2:
                return a1 - a2
            else:
                return 2*math.pi - abs(a1 - a2)

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
        # TODO the max_angle calculation below is a bit off -- we over-estimate the error, and thus produce finer
        # results than necessary. Fix this.
            
        r = math.hypot(self.cx, self.cy)

        max_error = self.unit(max_error, unit)
        if clip_max_error:
            # 1 - math.sqrt(1 - 0.5*math.sqrt(2))
            max_error = min(max_error, r*0.4588038998538031)

        elif max_error >= r:
            return [Line(*self.p1, *self.p2, aperture=self.aperture, polarity_dark=self.polarity_dark)]

        # see https://www.mathopenref.com/sagitta.html
        l = math.sqrt(r**2 - (r - max_error)**2)

        angle_max = math.asin(l/r)
        sweep_angle = self.sweep_angle()
        num_segments = math.ceil(sweep_angle / angle_max)
        angle = sweep_angle / num_segments

        if not self.clockwise:
            angle = -angle

        cx, cy = self.center
        points = [ rotate_point(self.x1, self.y1, i*angle, cx, cy) for i in range(num_segments + 1) ]
        return [ Line(*p1, *p2, aperture=self.aperture, polarity_dark=self.polarity_dark)
                for p1, p2 in zip(points[0::], points[1::]) ]

    def _rotate(self, rotation, cx=0, cy=0):
        # rotate center first since we need old x1, y1 here
        new_cx, new_cy = gp.rotate_point(*self.center, rotation, cx, cy)
        self.x1, self.y1 = gp.rotate_point(self.x1, self.y1, rotation, cx, cy)
        self.x2, self.y2 = gp.rotate_point(self.x2, self.y2, rotation, cx, cy)
        self.cx, self.cy = new_cx - self.x1, new_cy - self.y1

    def to_primitives(self, unit=None):
        conv = self.converted(unit)
        w = self.aperture.equivalent_width(unit) if self.aperture else 0.1 # for debugging
        yield gp.Arc(x1=conv.x1, y1=conv.y1,
                x2=conv.x2, y2=conv.y2,
                cx=conv.cx, cy=conv.cy,
                clockwise=self.clockwise,
                width=w,
                polarity_dark=self.polarity_dark)

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


