#! /usr/bin/env python
# -*- coding: utf-8 -*-

# copyright 2016 Hamilton Kibbe <ham@hamiltonkib.be>

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
from operator import add
from itertools import combinations
from .utils import validate_coordinates, inch, metric, convex_hull
from .utils import rotate_point, nearly_equal



class Primitive:
    def __init__(self, polarity_dark=True, rotation=0, **meta):
        self.polarity_dark = polarity_dark
        self.meta = meta
        self.rotation = rotation

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def aperture(self):
        return None


class Line(Primitive):
    def __init__(self, start, end, aperture=None, polarity_dark=True, rotation=0, **meta):
        super().__init__(polarity_dark, rotation, **meta)
        self.start = start
        self.end = end
        self.aperture = aperture

    @property
    def angle(self):
        delta_x, delta_y = tuple(end - start for end, start in zip(self.end, self.start))
        return math.atan2(delta_y, delta_x)

    @property
    def bounding_box(self):
        if isinstance(self.aperture, Circle):
            width_2 = self.aperture.radius
            height_2 = width_2
        else:
            width_2 = self.aperture.width / 2.
            height_2 = self.aperture.height / 2.
        min_x = min(self.start[0], self.end[0]) - width_2
        max_x = max(self.start[0], self.end[0]) + width_2
        min_y = min(self.start[1], self.end[1]) - height_2
        max_y = max(self.start[1], self.end[1]) + height_2
        return (min_x, min_y), (max_x, max_y)

    @property
    def bounding_box_no_aperture(self):
        '''Gets the bounding box without the aperture'''
        min_x = min(self.start[0], self.end[0])
        max_x = max(self.start[0], self.end[0])
        min_y = min(self.start[1], self.end[1])
        max_y = max(self.start[1], self.end[1])
        return ((min_x, min_y), (max_x, max_y))

    @property
    def vertices(self):
        if self._vertices is None:
            start = self.start
            end = self.end
            if isinstance(self.aperture, Rectangle):
                width = self.aperture.width
                height = self.aperture.height

                # Find all the corners of the start and end position
                start_ll = (start[0] - (width / 2.), start[1] - (height / 2.))
                start_lr = (start[0] + (width / 2.), start[1] - (height / 2.))
                start_ul = (start[0] - (width / 2.), start[1] + (height / 2.))
                start_ur = (start[0] + (width / 2.), start[1] + (height / 2.))
                end_ll = (end[0] - (width / 2.), end[1] - (height / 2.))
                end_lr = (end[0] + (width / 2.), end[1] - (height / 2.))
                end_ul = (end[0] - (width / 2.), end[1] + (height / 2.))
                end_ur = (end[0] + (width / 2.), end[1] + (height / 2.))

                # The line is defined by the convex hull of the points
                self._vertices = convex_hull((start_ll, start_lr, start_ul, start_ur, end_ll, end_lr, end_ul, end_ur))
            elif isinstance(self.aperture, Polygon):
                points = [map(add, point, vertex)
                          for vertex in self.aperture.vertices
                          for point in (start, end)]
                self._vertices = convex_hull(points)
        return self._vertices

    def offset(self, x_offset=0, y_offset=0):
        self._changed()
        self.start = tuple([coord + offset for coord, offset
                            in zip(self.start, (x_offset, y_offset))])
        self.end = tuple([coord + offset for coord, offset
                          in zip(self.end, (x_offset, y_offset))])

    def equivalent(self, other, offset):

        if not isinstance(other, Line):
            return False

        equiv_start = tuple(map(add, other.start, offset))
        equiv_end = tuple(map(add, other.end, offset))


        return nearly_equal(self.start, equiv_start) and nearly_equal(self.end, equiv_end)

    def __str__(self):
        return "<Line {} to {}>".format(self.start, self.end)

    def __repr__(self):
        return str(self)

class Arc(Primitive):
    def __init__(self, start, end, center, direction, aperture, level_polarity=None, **kwargs):
        super(Arc, self).__init__(**kwargs)
        self.level_polarity = level_polarity
        self._start = start
        self._end = end
        self._center = center
        self.direction = direction
        self.aperture = aperture
        self._to_convert = ['start', 'end', 'center', 'aperture']

    @property
    def flashed(self):
        return False

    @property
    def start(self):
        return self._start

    @start.setter
    def start(self, value):
        self._changed()
        self._start = value

    @property
    def end(self):
        return self._end

    @end.setter
    def end(self, value):
        self._changed()
        self._end = value

    @property
    def center(self):
        return self._center

    @center.setter
    def center(self, value):
        self._changed()
        self._center = value

    @property
    def radius(self):
        dy, dx = tuple([start - center for start, center
                        in zip(self.start, self.center)])
        return math.sqrt(dy ** 2 + dx ** 2)

    @property
    def start_angle(self):
        dx, dy = tuple([start - center for start, center
                        in zip(self.start, self.center)])
        return math.atan2(dy, dx)

    @property
    def end_angle(self):
        dx, dy = tuple([end - center for end, center
                        in zip(self.end, self.center)])
        return math.atan2(dy, dx)

    @property
    def sweep_angle(self):
        two_pi = 2 * math.pi
        theta0 = (self.start_angle + two_pi) % two_pi
        theta1 = (self.end_angle + two_pi) % two_pi
        if self.direction == 'counterclockwise':
            return abs(theta1 - theta0)
        else:
            theta0 += two_pi
            return abs(theta0 - theta1) % two_pi

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            two_pi = 2 * math.pi
            theta0 = (self.start_angle + two_pi) % two_pi
            theta1 = (self.end_angle + two_pi) % two_pi
            points = [self.start, self.end]
            x, y = zip(*points)
            if hasattr(self.aperture, 'radius'):
                min_x = min(x) - self.aperture.radius
                max_x = max(x) + self.aperture.radius
                min_y = min(y) - self.aperture.radius
                max_y = max(y) + self.aperture.radius
            else:
                min_x = min(x) - self.aperture.width
                max_x = max(x) + self.aperture.width
                min_y = min(y) - self.aperture.height
                max_y = max(y) + self.aperture.height

            self._bounding_box = ((min_x, min_y), (max_x, max_y))
        return self._bounding_box

    @property
    def bounding_box_no_aperture(self):
        '''Gets the bounding box without considering the aperture'''
        two_pi = 2 * math.pi
        theta0 = (self.start_angle + two_pi) % two_pi
        theta1 = (self.end_angle + two_pi) % two_pi
        points = [self.start, self.end]
        x, y = zip(*points)

        min_x = min(x)
        max_x = max(x)
        min_y = min(y)
        max_y = max(y)
        return ((min_x, min_y), (max_x, max_y))

    def offset(self, x_offset=0, y_offset=0):
        self._changed()
        self.start = tuple(map(add, self.start, (x_offset, y_offset)))
        self.end = tuple(map(add, self.end, (x_offset, y_offset)))
        self.center = tuple(map(add, self.center, (x_offset, y_offset)))


class Circle(Primitive):
    def __init__(self, position, diameter, polarity_dark=True):
        super(Circle, self).__init__(**kwargs)
        validate_coordinates(position)
        self._position = position
        self._diameter = diameter
        self.hole_diameter = hole_diameter
        self.hole_width = hole_width
        self.hole_height = hole_height
        self._to_convert = ['position', 'diameter', 'hole_diameter', 'hole_width', 'hole_height']

    @property
    def flashed(self):
        return True

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._changed()
        self._position = value

    @property
    def diameter(self):
        return self._diameter

    @diameter.setter
    def diameter(self, value):
        self._changed()
        self._diameter = value

    @property
    def radius(self):
        return self.diameter / 2.

    @property
    def hole_radius(self):
        if self.hole_diameter != None:
            return self.hole_diameter / 2.
        return None

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            min_x = self.position[0] - self.radius
            max_x = self.position[0] + self.radius
            min_y = self.position[1] - self.radius
            max_y = self.position[1] + self.radius
            self._bounding_box = ((min_x, min_y), (max_x, max_y))
        return self._bounding_box

    def offset(self, x_offset=0, y_offset=0):
        self.position = tuple(map(add, self.position, (x_offset, y_offset)))

    def equivalent(self, other, offset):
        '''Is this the same as the other circle, ignoring the offiset?'''

        if not isinstance(other, Circle):
            return False

        if self.diameter != other.diameter or self.hole_diameter != other.hole_diameter:
            return False

        equiv_position = tuple(map(add, other.position, offset))

        return nearly_equal(self.position, equiv_position)


class Rectangle(Primitive):
    """
    When rotated, the rotation is about the center point.

    Only aperture macro generated Rectangle objects can be rotated. If you aren't in a AMGroup,
    then you don't need to worry about rotation
    """

    def __init__(self, position, width, height, hole_diameter=0,
                 hole_width=0, hole_height=0, **kwargs):
        super(Rectangle, self).__init__(**kwargs)
        validate_coordinates(position)
        self._position = position
        self._width = width
        self._height = height
        self.hole_diameter = hole_diameter
        self.hole_width = hole_width
        self.hole_height = hole_height
        self._to_convert = ['position', 'width', 'height', 'hole_diameter',
                            'hole_width', 'hole_height']
        # TODO These are probably wrong when rotated
        self._lower_left = None
        self._upper_right = None

    @property
    def flashed(self):
        return True

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._changed()
        self._position = value

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        self._changed()
        self._width = value

    @property
    def height(self):
        return self._height

    @height.setter
    def height(self, value):
        self._changed()
        self._height = value

    @property
    def hole_radius(self):
        """The radius of the hole. If there is no hole, returns None"""
        if self.hole_diameter != None:
            return self.hole_diameter / 2.
        return None

    @property
    def upper_right(self):
        return (self.position[0] + (self.axis_aligned_width / 2.),
                self.position[1] + (self.axis_aligned_height / 2.))

    @property
    def lower_left(self):
        return (self.position[0] - (self.axis_aligned_width / 2.),
                self.position[1] - (self.axis_aligned_height / 2.))

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            ll = (self.position[0] - (self.axis_aligned_width / 2.),
                  self.position[1] - (self.axis_aligned_height / 2.))
            ur = (self.position[0] + (self.axis_aligned_width / 2.),
                  self.position[1] + (self.axis_aligned_height / 2.))
            self._bounding_box = ((ll[0], ll[1]), (ur[0], ur[1]))
        return self._bounding_box

    @property
    def vertices(self):
        if self._vertices is None:
            delta_w = self.width / 2.
            delta_h = self.height / 2.
            ll = ((self.position[0] - delta_w), (self.position[1] - delta_h))
            ul = ((self.position[0] - delta_w), (self.position[1] + delta_h))
            ur = ((self.position[0] + delta_w), (self.position[1] + delta_h))
            lr = ((self.position[0] + delta_w), (self.position[1] - delta_h))
            self._vertices = [((x * self._cos_theta - y * self._sin_theta),
                               (x * self._sin_theta + y * self._cos_theta))
                              for x, y in [ll, ul, ur, lr]]
        return self._vertices

    @property
    def axis_aligned_width(self):
        return (self._cos_theta * self.width + self._sin_theta * self.height)

    @property
    def axis_aligned_height(self):
        return (self._cos_theta * self.height + self._sin_theta * self.width)

    def equivalent(self, other, offset):
        """Is this the same as the other rect, ignoring the offset?"""

        if not isinstance(other, Rectangle):
            return False

        if self.width != other.width or self.height != other.height or self.rotation != other.rotation or self.hole_diameter != other.hole_diameter:
            return False

        equiv_position = tuple(map(add, other.position, offset))

        return nearly_equal(self.position, equiv_position)

    def __str__(self):
        return "<Rectangle W {} H {} R {}>".format(self.width, self.height, self.rotation * 180/math.pi)

    def __repr__(self):
        return self.__str__()


class Obround(Primitive):
    def __init__(self, position, width, height, hole_diameter=0,
                 hole_width=0,hole_height=0, **kwargs):
        super(Obround, self).__init__(**kwargs)
        validate_coordinates(position)
        self._position = position
        self._width = width
        self._height = height
        self.hole_diameter = hole_diameter
        self.hole_width = hole_width
        self.hole_height = hole_height
        self._to_convert = ['position', 'width', 'height', 'hole_diameter',
                            'hole_width', 'hole_height' ]

    @property
    def flashed(self):
        return True

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._changed()
        self._position = value

    @property
    def width(self):
        return self._width

    @width.setter
    def width(self, value):
        self._changed()
        self._width = value

    @property
    def height(self):
        return self._height

    @height.setter
    def height(self, value):
        self._changed()
        self._height = value

    @property
    def hole_radius(self):
        """The radius of the hole. If there is no hole, returns None"""
        if self.hole_diameter != None:
            return self.hole_diameter / 2.

        return None

    @property
    def orientation(self):
        return 'vertical' if self.height > self.width else 'horizontal'

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            ll = (self.position[0] - (self.axis_aligned_width / 2.),
                  self.position[1] - (self.axis_aligned_height / 2.))
            ur = (self.position[0] + (self.axis_aligned_width / 2.),
                  self.position[1] + (self.axis_aligned_height / 2.))
            self._bounding_box = ((ll[0], ll[1]), (ur[0], ur[1]))
        return self._bounding_box

    @property
    def subshapes(self):
        if self.orientation == 'vertical':
            circle1 = Circle((self.position[0], self.position[1] +
                              (self.height - self.width) / 2.), self.width)
            circle2 = Circle((self.position[0], self.position[1] -
                              (self.height - self.width) / 2.), self.width)
            rect = Rectangle(self.position, self.width,
                             (self.height - self.width))
        else:
            circle1 = Circle((self.position[0]
                              - (self.height - self.width) / 2.,
                              self.position[1]), self.height)
            circle2 = Circle((self.position[0]
                              + (self.height - self.width) / 2.,
                              self.position[1]), self.height)
            rect = Rectangle(self.position, (self.width - self.height),
                             self.height)
        return {'circle1': circle1, 'circle2': circle2, 'rectangle': rect}

    @property
    def axis_aligned_width(self):
        return (self._cos_theta * self.width +
                self._sin_theta * self.height)

    @property
    def axis_aligned_height(self):
        return (self._cos_theta * self.height +
                self._sin_theta * self.width)


class Polygon(Primitive):
    """
    Polygon flash defined by a set number of sides.
    """
    def __init__(self, position, sides, radius, hole_diameter=0,
                 hole_width=0, hole_height=0, **kwargs):
        super(Polygon, self).__init__(**kwargs)
        validate_coordinates(position)
        self._position = position
        self.sides = sides
        self._radius = radius
        self.hole_diameter = hole_diameter
        self.hole_width = hole_width
        self.hole_height = hole_height
        self._to_convert = ['position', 'radius', 'hole_diameter',
                            'hole_width', 'hole_height']

    @property
    def flashed(self):
        return True

    @property
    def diameter(self):
        return self.radius * 2

    @property
    def hole_radius(self):
        if self.hole_diameter != None:
            return self.hole_diameter / 2.
        return None

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._changed()
        self._position = value

    @property
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, value):
        self._changed()
        self._radius = value

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            min_x = self.position[0] - self.radius
            max_x = self.position[0] + self.radius
            min_y = self.position[1] - self.radius
            max_y = self.position[1] + self.radius
            self._bounding_box = ((min_x, min_y), (max_x, max_y))
        return self._bounding_box

    def offset(self, x_offset=0, y_offset=0):
        self.position = tuple(map(add, self.position, (x_offset, y_offset)))

    @property
    def vertices(self):

        offset = self.rotation
        delta_angle = 360.0 / self.sides

        points = []
        for i in range(self.sides):
            points.append(
                rotate_point((self.position[0] + self.radius, self.position[1]), offset + delta_angle * i, self.position))
        return points


    def equivalent(self, other, offset):
        """
        Is this the outline the same as the other, ignoring the position offset?
        """

        # Quick check if it even makes sense to compare them
        if type(self) != type(other) or self.sides != other.sides or self.radius != other.radius:
            return False

        equiv_pos = tuple(map(add, other.position, offset))

        return nearly_equal(self.position, equiv_pos)


class AMGroup(Primitive):
    """
    """
    def __init__(self, amprimitives, stmt = None, **kwargs):
        """

        stmt : The original statment that generated this, since it is really hard to re-generate from primitives
        """
        super(AMGroup, self).__init__(**kwargs)

        self.primitives = []
        for amprim in amprimitives:
            prim = amprim.to_primitive(self.units)
            if isinstance(prim, list):
                for p in prim:
                    self.primitives.append(p)
            elif prim:
                self.primitives.append(prim)
        self._position = None
        self._to_convert = ['_position', 'primitives']
        self.stmt = stmt

    def to_inch(self):
        if self.units == 'metric':
            super(AMGroup, self).to_inch()

            # If we also have a stmt, convert that too
            if self.stmt:
                self.stmt.to_inch()


    def to_metric(self):
        if self.units == 'inch':
            super(AMGroup, self).to_metric()

            # If we also have a stmt, convert that too
            if self.stmt:
                self.stmt.to_metric()

    @property
    def flashed(self):
        return True

    @property
    def bounding_box(self):
        # TODO Make this cached like other items
        xlims, ylims = zip(*[p.bounding_box for p in self.primitives])
        minx, maxx = zip(*xlims)
        miny, maxy = zip(*ylims)
        min_x = min(minx)
        max_x = max(maxx)
        min_y = min(miny)
        max_y = max(maxy)
        return ((min_x, max_x), (min_y, max_y))

    @property
    def position(self):
        return self._position

    def offset(self, x_offset=0, y_offset=0):
        self._position = tuple(map(add, self._position, (x_offset, y_offset)))

        for primitive in self.primitives:
            primitive.offset(x_offset, y_offset)

    @position.setter
    def position(self, new_pos):
        '''
        Sets the position of the AMGroup.
        This offset all of the objects by the specified distance.
        '''

        if self._position:
            dx = new_pos[0] - self._position[0]
            dy = new_pos[1] - self._position[1]
        else:
            dx = new_pos[0]
            dy = new_pos[1]

        for primitive in self.primitives:
            primitive.offset(dx, dy)

        self._position = new_pos

    def equivalent(self, other, offset):
        '''
        Is this the macro group the same as the other, ignoring the position offset?
        '''

        if len(self.primitives) != len(other.primitives):
            return False

        # We know they have the same number of primitives, so now check them all
        for i in range(0, len(self.primitives)):
            if not self.primitives[i].equivalent(other.primitives[i], offset):
                return False

        # If we didn't find any differences, then they are the same
        return True

class Outline(Primitive):
    """
    Outlines only exist as the rendering for a apeture macro outline.
    They don't exist outside of AMGroup objects
    """

    def __init__(self, primitives, **kwargs):
        super(Outline, self).__init__(**kwargs)
        self.primitives = primitives
        self._to_convert = ['primitives']

        if self.primitives[0].start != self.primitives[-1].end:
            raise ValueError('Outline must be closed')

    @property
    def flashed(self):
        return True

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            xlims, ylims = zip(*[p.bounding_box for p in self.primitives])
            minx, maxx = zip(*xlims)
            miny, maxy = zip(*ylims)
            min_x = min(minx)
            max_x = max(maxx)
            min_y = min(miny)
            max_y = max(maxy)
            self._bounding_box = ((min_x, max_x), (min_y, max_y))
        return self._bounding_box

    def offset(self, x_offset=0, y_offset=0):
        self._changed()
        for p in self.primitives:
            p.offset(x_offset, y_offset)

    @property
    def vertices(self):
        if self._vertices is None:
            theta = math.radians(360/self.sides)
            vertices = [(self.position[0] + (math.cos(theta * side) * self.radius),
                         self.position[1] + (math.sin(theta * side) * self.radius))
                        for side in range(self.sides)]
            self._vertices = [(((x * self._cos_theta) - (y * self._sin_theta)),
                               ((x * self._sin_theta) + (y * self._cos_theta)))
                              for x, y in vertices]
        return self._vertices

    @property
    def width(self):
        bounding_box = self.bounding_box()
        return bounding_box[1][0] - bounding_box[0][0]

    def equivalent(self, other, offset):
        '''
        Is this the outline the same as the other, ignoring the position offset?
        '''

        # Quick check if it even makes sense to compare them
        if type(self) != type(other) or len(self.primitives) != len(other.primitives):
            return False

        for i in range(0, len(self.primitives)):
            if not self.primitives[i].equivalent(other.primitives[i], offset):
                return False

        return True

class Region(Primitive):
    """
    """

    def __init__(self, primitives, **kwargs):
        super(Region, self).__init__(**kwargs)
        self.primitives = primitives
        self._to_convert = ['primitives']

    @property
    def flashed(self):
        return False

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            xlims, ylims = zip(*[p.bounding_box for p in self.primitives])
            minx, maxx = zip(*xlims)
            miny, maxy = zip(*ylims)
            min_x = min(minx)
            max_x = max(maxx)
            min_y = min(miny)
            max_y = max(maxy)
            self._bounding_box = ((min_x, min_y), (max_x, max_y))
        return self._bounding_box

    def offset(self, x_offset=0, y_offset=0):
        self._changed()
        for p in self.primitives:
            p.offset(x_offset, y_offset)


class Drill(Primitive):
    """ A drill hole
    """
    def __init__(self, position, diameter, **kwargs):
        super(Drill, self).__init__('dark', **kwargs)
        validate_coordinates(position)
        self._position = position
        self._diameter = diameter
        self._to_convert = ['position', 'diameter']

    @property
    def flashed(self):
        return False

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._changed()
        self._position = value

    @property
    def diameter(self):
        return self._diameter

    @diameter.setter
    def diameter(self, value):
        self._changed()
        self._diameter = value

    @property
    def radius(self):
        return self.diameter / 2.

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            min_x = self.position[0] - self.radius
            max_x = self.position[0] + self.radius
            min_y = self.position[1] - self.radius
            max_y = self.position[1] + self.radius
            self._bounding_box = ((min_x, min_y), (max_x, max_y))
        return self._bounding_box

    def offset(self, x_offset=0, y_offset=0):
        self._changed()
        self.position = tuple(map(add, self.position, (x_offset, y_offset)))

    def __str__(self):
        return '<Drill %f %s (%f, %f)>' % (self.diameter, self.units, self.position[0], self.position[1])


class Slot(Primitive):
    """ A drilled slot
    """
    def __init__(self, start, end, diameter, **kwargs):
        super(Slot, self).__init__('dark', **kwargs)
        validate_coordinates(start)
        validate_coordinates(end)
        self.start = start
        self.end = end
        self.diameter = diameter
        self._to_convert = ['start', 'end', 'diameter']


    @property
    def flashed(self):
        return False

    @property
    def bounding_box(self):
        if self._bounding_box is None:
            radius = self.diameter / 2.
            min_x = min(self.start[0], self.end[0]) - radius
            max_x = max(self.start[0], self.end[0]) + radius
            min_y = min(self.start[1], self.end[1]) - radius
            max_y = max(self.start[1], self.end[1]) + radius
            self._bounding_box = ((min_x, min_y), (max_x, max_y))
        return self._bounding_box

    def offset(self, x_offset=0, y_offset=0):
        self.start = tuple(map(add, self.start, (x_offset, y_offset)))
        self.end = tuple(map(add, self.end, (x_offset, y_offset)))


class TestRecord(Primitive):
    """ Netlist Test record
    """
    __test__ = False # This is not a PyTest unit test.

    def __init__(self, position, net_name, layer, **kwargs):
        super(TestRecord, self).__init__(**kwargs)
        validate_coordinates(position)
        self.position = position
        self.net_name = net_name
        self.layer = layer
        self._to_convert = ['position']

class RegionGroup:
    def __init__(self):
        self.outline = []

    def __bool__(self):
        return bool(self.outline)

    def append(self, primitive):
        self.outline.append(primitive)

