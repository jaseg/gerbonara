#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Hamilton Kibbe <ham@hamiltonkib.be>

import pytest
from operator import add
from ..primitives import *


def test_primitive_smoketest():
    p = Primitive()
    try:
        p.bounding_box
        assert not True, "should have thrown the exception"
    except NotImplementedError:
        pass
    # pytest.raises(NotImplementedError, p.bounding_box)

    p.to_metric()
    p.to_inch()
    # try:
    #    p.offset(1, 1)
    #    assert_false(True, 'should have thrown the exception')
    # except NotImplementedError:
    #    pass


def test_line_angle():
    """ Test Line primitive angle calculation
    """
    cases = [
        ((0, 0), (1, 0), math.radians(0)),
        ((0, 0), (1, 1), math.radians(45)),
        ((0, 0), (0, 1), math.radians(90)),
        ((0, 0), (-1, 1), math.radians(135)),
        ((0, 0), (-1, 0), math.radians(180)),
        ((0, 0), (-1, -1), math.radians(225)),
        ((0, 0), (0, -1), math.radians(270)),
        ((0, 0), (1, -1), math.radians(315)),
    ]
    for start, end, expected in cases:
        l = Line(start, end, 0)
        line_angle = (l.angle + 2 * math.pi) % (2 * math.pi)
        pytest.approx(line_angle, expected)


def test_line_bounds():
    """ Test Line primitive bounding box calculation
    """
    cases = [
        ((0, 0), (1, 1), ((-1, 2), (-1, 2))),
        ((-1, -1), (1, 1), ((-2, 2), (-2, 2))),
        ((1, 1), (-1, -1), ((-2, 2), (-2, 2))),
        ((-1, 1), (1, -1), ((-2, 2), (-2, 2))),
    ]

    c = Circle((0, 0), 2)
    r = Rectangle((0, 0), 2, 2)
    for shape in (c, r):
        for start, end, expected in cases:
            l = Line(start, end, shape)
            assert l.bounding_box == expected
    # Test a non-square rectangle
    r = Rectangle((0, 0), 3, 2)
    cases = [
        ((0, 0), (1, 1), ((-1.5, 2.5), (-1, 2))),
        ((-1, -1), (1, 1), ((-2.5, 2.5), (-2, 2))),
        ((1, 1), (-1, -1), ((-2.5, 2.5), (-2, 2))),
        ((-1, 1), (1, -1), ((-2.5, 2.5), (-2, 2))),
    ]
    for start, end, expected in cases:
        l = Line(start, end, r)
        assert l.bounding_box == expected


def test_line_vertices():
    c = Circle((0, 0), 2)
    l = Line((0, 0), (1, 1), c)
    assert l.vertices == None

    # All 4 compass points, all 4 quadrants and the case where start == end
    test_cases = [
        ((0, 0), (1, 0), ((-1, -1), (-1, 1), (2, 1), (2, -1))),
        ((0, 0), (1, 1), ((-1, -1), (-1, 1), (0, 2), (2, 2), (2, 0), (1, -1))),
        ((0, 0), (0, 1), ((-1, -1), (-1, 2), (1, 2), (1, -1))),
        ((0, 0), (-1, 1), ((-1, -1), (-2, 0), (-2, 2), (0, 2), (1, 1), (1, -1))),
        ((0, 0), (-1, 0), ((-2, -1), (-2, 1), (1, 1), (1, -1))),
        ((0, 0), (-1, -1), ((-2, -2), (1, -1), (1, 1), (-1, 1), (-2, 0), (0, -2))),
        ((0, 0), (0, -1), ((-1, -2), (-1, 1), (1, 1), (1, -2))),
        ((0, 0), (1, -1), ((-1, -1), (0, -2), (2, -2), (2, 0), (1, 1), (-1, 1))),
        ((0, 0), (0, 0), ((-1, -1), (-1, 1), (1, 1), (1, -1))),
    ]
    r = Rectangle((0, 0), 2, 2)

    for start, end, vertices in test_cases:
        l = Line(start, end, r)
        assert set(vertices) == set(l.vertices)


def test_line_conversion():
    c = Circle((0, 0), 25.4, units="metric")
    l = Line((2.54, 25.4), (254.0, 2540.0), c, units="metric")

    # No effect
    l.to_metric()
    assert l.start == (2.54, 25.4)
    assert l.end == (254.0, 2540.0)
    assert l.aperture.diameter == 25.4

    l.to_inch()
    assert l.start == (0.1, 1.0)
    assert l.end == (10.0, 100.0)
    assert l.aperture.diameter == 1.0

    # No effect
    l.to_inch()
    assert l.start == (0.1, 1.0)
    assert l.end == (10.0, 100.0)
    assert l.aperture.diameter == 1.0

    c = Circle((0, 0), 1.0, units="inch")
    l = Line((0.1, 1.0), (10.0, 100.0), c, units="inch")

    # No effect
    l.to_inch()
    assert l.start == (0.1, 1.0)
    assert l.end == (10.0, 100.0)
    assert l.aperture.diameter == 1.0

    l.to_metric()
    assert l.start == (2.54, 25.4)
    assert l.end == (254.0, 2540.0)
    assert l.aperture.diameter == 25.4

    # No effect
    l.to_metric()
    assert l.start == (2.54, 25.4)
    assert l.end == (254.0, 2540.0)
    assert l.aperture.diameter == 25.4

    r = Rectangle((0, 0), 25.4, 254.0, units="metric")
    l = Line((2.54, 25.4), (254.0, 2540.0), r, units="metric")
    l.to_inch()
    assert l.start == (0.1, 1.0)
    assert l.end == (10.0, 100.0)
    assert l.aperture.width == 1.0
    assert l.aperture.height == 10.0

    r = Rectangle((0, 0), 1.0, 10.0, units="inch")
    l = Line((0.1, 1.0), (10.0, 100.0), r, units="inch")
    l.to_metric()
    assert l.start == (2.54, 25.4)
    assert l.end == (254.0, 2540.0)
    assert l.aperture.width == 25.4
    assert l.aperture.height == 254.0


def test_line_offset():
    c = Circle((0, 0), 1)
    l = Line((0, 0), (1, 1), c)
    l.offset(1, 0)
    assert l.start == (1.0, 0.0)
    assert l.end == (2.0, 1.0)
    l.offset(0, 1)
    assert l.start == (1.0, 1.0)
    assert l.end == (2.0, 2.0)


def test_arc_radius():
    """ Test Arc primitive radius calculation
    """
    cases = [((-3, 4), (5, 0), (0, 0), 5), ((0, 1), (1, 0), (0, 0), 1)]

    for start, end, center, radius in cases:
        a = Arc(start, end, center, "clockwise", 0, "single-quadrant")
        assert a.radius == radius


def test_arc_sweep_angle():
    """ Test Arc primitive sweep angle calculation
    """
    cases = [
        ((1, 0), (0, 1), (0, 0), "counterclockwise", math.radians(90)),
        ((1, 0), (0, 1), (0, 0), "clockwise", math.radians(270)),
        ((1, 0), (-1, 0), (0, 0), "clockwise", math.radians(180)),
        ((1, 0), (-1, 0), (0, 0), "counterclockwise", math.radians(180)),
    ]

    for start, end, center, direction, sweep in cases:
        c = Circle((0, 0), 1)
        a = Arc(start, end, center, direction, c, "single-quadrant")
        assert a.sweep_angle == sweep


def test_arc_bounds():
    """ Test Arc primitive bounding box calculation
    """
    cases = [
        ((1, 0), (0, 1), (0, 0), "clockwise", ((-1.5, 1.5), (-1.5, 1.5))),
        ((1, 0), (0, 1), (0, 0), "counterclockwise", ((-0.5, 1.5), (-0.5, 1.5))),
        ((0, 1), (-1, 0), (0, 0), "clockwise", ((-1.5, 1.5), (-1.5, 1.5))),
        ((0, 1), (-1, 0), (0, 0), "counterclockwise", ((-1.5, 0.5), (-0.5, 1.5))),
        ((-1, 0), (0, -1), (0, 0), "clockwise", ((-1.5, 1.5), (-1.5, 1.5))),
        ((-1, 0), (0, -1), (0, 0), "counterclockwise", ((-1.5, 0.5), (-1.5, 0.5))),
        ((0, -1), (1, 0), (0, 0), "clockwise", ((-1.5, 1.5), (-1.5, 1.5))),
        ((0, -1), (1, 0), (0, 0), "counterclockwise", ((-0.5, 1.5), (-1.5, 0.5))),
        # Arcs with the same start and end point render a full circle
        ((1, 0), (1, 0), (0, 0), "clockwise", ((-1.5, 1.5), (-1.5, 1.5))),
        ((1, 0), (1, 0), (0, 0), "counterclockwise", ((-1.5, 1.5), (-1.5, 1.5))),
    ]
    for start, end, center, direction, bounds in cases:
        c = Circle((0, 0), 1)
        a = Arc(start, end, center, direction, c, "multi-quadrant")
        assert a.bounding_box == bounds


def test_arc_bounds_no_aperture():
    """ Test Arc primitive bounding box calculation ignoring aperture
    """
    cases = [
        ((1, 0), (0, 1), (0, 0), "clockwise", ((-1.0, 1.0), (-1.0, 1.0))),
        ((1, 0), (0, 1), (0, 0), "counterclockwise", ((0.0, 1.0), (0.0, 1.0))),
        ((0, 1), (-1, 0), (0, 0), "clockwise", ((-1.0, 1.0), (-1.0, 1.0))),
        ((0, 1), (-1, 0), (0, 0), "counterclockwise", ((-1.0, 0.0), (0.0, 1.0))),
        ((-1, 0), (0, -1), (0, 0), "clockwise", ((-1.0, 1.0), (-1.0, 1.0))),
        ((-1, 0), (0, -1), (0, 0), "counterclockwise", ((-1.0, 0.0), (-1.0, 0.0))),
        ((0, -1), (1, 0), (0, 0), "clockwise", ((-1.0, 1.0), (-1.0, 1.0))),
        ((0, -1), (1, 0), (0, 0), "counterclockwise", ((-0.0, 1.0), (-1.0, 0.0))),
        # Arcs with the same start and end point render a full circle
        ((1, 0), (1, 0), (0, 0), "clockwise", ((-1.0, 1.0), (-1.0, 1.0))),
        ((1, 0), (1, 0), (0, 0), "counterclockwise", ((-1.0, 1.0), (-1.0, 1.0))),
    ]
    for start, end, center, direction, bounds in cases:
        c = Circle((0, 0), 1)
        a = Arc(start, end, center, direction, c, "multi-quadrant")
        assert a.bounding_box_no_aperture == bounds


def test_arc_conversion():
    c = Circle((0, 0), 25.4, units="metric")
    a = Arc(
        (2.54, 25.4),
        (254.0, 2540.0),
        (25400.0, 254000.0),
        "clockwise",
        c,
        "single-quadrant",
        units="metric",
    )

    # No effect
    a.to_metric()
    assert a.start == (2.54, 25.4)
    assert a.end == (254.0, 2540.0)
    assert a.center == (25400.0, 254000.0)
    assert a.aperture.diameter == 25.4

    a.to_inch()
    assert a.start == (0.1, 1.0)
    assert a.end == (10.0, 100.0)
    assert a.center == (1000.0, 10000.0)
    assert a.aperture.diameter == 1.0

    # no effect
    a.to_inch()
    assert a.start == (0.1, 1.0)
    assert a.end == (10.0, 100.0)
    assert a.center == (1000.0, 10000.0)
    assert a.aperture.diameter == 1.0

    c = Circle((0, 0), 1.0, units="inch")
    a = Arc(
        (0.1, 1.0),
        (10.0, 100.0),
        (1000.0, 10000.0),
        "clockwise",
        c,
        "single-quadrant",
        units="inch",
    )
    a.to_metric()
    assert a.start == (2.54, 25.4)
    assert a.end == (254.0, 2540.0)
    assert a.center == (25400.0, 254000.0)
    assert a.aperture.diameter == 25.4


def test_arc_offset():
    c = Circle((0, 0), 1)
    a = Arc((0, 0), (1, 1), (2, 2), "clockwise", c, "single-quadrant")
    a.offset(1, 0)
    assert a.start == (1.0, 0.0)
    assert a.end == (2.0, 1.0)
    assert a.center == (3.0, 2.0)
    a.offset(0, 1)
    assert a.start == (1.0, 1.0)
    assert a.end == (2.0, 2.0)
    assert a.center == (3.0, 3.0)


def test_circle_radius():
    """ Test Circle primitive radius calculation
    """
    c = Circle((1, 1), 2)
    assert c.radius == 1


def test_circle_hole_radius():
    """ Test Circle primitive hole radius calculation
    """
    c = Circle((1, 1), 4, 2)
    assert c.hole_radius == 1


def test_circle_bounds():
    """ Test Circle bounding box calculation
    """
    c = Circle((1, 1), 2)
    assert c.bounding_box == ((0, 2), (0, 2))


def test_circle_conversion():
    """Circle conversion of units"""
    # Circle initially metric, no hole
    c = Circle((2.54, 25.4), 254.0, units="metric")

    c.to_metric()  # shouldn't do antyhing
    assert c.position == (2.54, 25.4)
    assert c.diameter == 254.0
    assert c.hole_diameter == None

    c.to_inch()
    assert c.position == (0.1, 1.0)
    assert c.diameter == 10.0
    assert c.hole_diameter == None

    # no effect
    c.to_inch()
    assert c.position == (0.1, 1.0)
    assert c.diameter == 10.0
    assert c.hole_diameter == None

    # Circle initially metric, with hole
    c = Circle((2.54, 25.4), 254.0, 127.0, units="metric")

    c.to_metric()  # shouldn't do antyhing
    assert c.position == (2.54, 25.4)
    assert c.diameter == 254.0
    assert c.hole_diameter == 127.0

    c.to_inch()
    assert c.position == (0.1, 1.0)
    assert c.diameter == 10.0
    assert c.hole_diameter == 5.0

    # no effect
    c.to_inch()
    assert c.position == (0.1, 1.0)
    assert c.diameter == 10.0
    assert c.hole_diameter == 5.0

    # Circle initially inch, no hole
    c = Circle((0.1, 1.0), 10.0, units="inch")
    # No effect
    c.to_inch()
    assert c.position == (0.1, 1.0)
    assert c.diameter == 10.0
    assert c.hole_diameter == None

    c.to_metric()
    assert c.position == (2.54, 25.4)
    assert c.diameter == 254.0
    assert c.hole_diameter == None

    # no effect
    c.to_metric()
    assert c.position == (2.54, 25.4)
    assert c.diameter == 254.0
    assert c.hole_diameter == None

    c = Circle((0.1, 1.0), 10.0, 5.0, units="inch")
    # No effect
    c.to_inch()
    assert c.position == (0.1, 1.0)
    assert c.diameter == 10.0
    assert c.hole_diameter == 5.0

    c.to_metric()
    assert c.position == (2.54, 25.4)
    assert c.diameter == 254.0
    assert c.hole_diameter == 127.0

    # no effect
    c.to_metric()
    assert c.position == (2.54, 25.4)
    assert c.diameter == 254.0
    assert c.hole_diameter == 127.0


def test_circle_offset():
    c = Circle((0, 0), 1)
    c.offset(1, 0)
    assert c.position == (1.0, 0.0)
    c.offset(0, 1)
    assert c.position == (1.0, 1.0)


def test_ellipse_ctor():
    """ Test ellipse creation
    """
    e = Ellipse((2, 2), 3, 2)
    assert e.position == (2, 2)
    assert e.width == 3
    assert e.height == 2


def test_ellipse_bounds():
    """ Test ellipse bounding box calculation
    """
    e = Ellipse((2, 2), 4, 2)
    assert e.bounding_box == ((0, 4), (1, 3))
    e = Ellipse((2, 2), 4, 2, rotation=90)
    assert e.bounding_box == ((1, 3), (0, 4))
    e = Ellipse((2, 2), 4, 2, rotation=180)
    assert e.bounding_box == ((0, 4), (1, 3))
    e = Ellipse((2, 2), 4, 2, rotation=270)
    assert e.bounding_box == ((1, 3), (0, 4))


def test_ellipse_conversion():
    e = Ellipse((2.54, 25.4), 254.0, 2540.0, units="metric")

    # No effect
    e.to_metric()
    assert e.position == (2.54, 25.4)
    assert e.width == 254.0
    assert e.height == 2540.0

    e.to_inch()
    assert e.position == (0.1, 1.0)
    assert e.width == 10.0
    assert e.height == 100.0

    # No effect
    e.to_inch()
    assert e.position == (0.1, 1.0)
    assert e.width == 10.0
    assert e.height == 100.0

    e = Ellipse((0.1, 1.0), 10.0, 100.0, units="inch")

    # no effect
    e.to_inch()
    assert e.position == (0.1, 1.0)
    assert e.width == 10.0
    assert e.height == 100.0

    e.to_metric()
    assert e.position == (2.54, 25.4)
    assert e.width == 254.0
    assert e.height == 2540.0

    # No effect
    e.to_metric()
    assert e.position == (2.54, 25.4)
    assert e.width == 254.0
    assert e.height == 2540.0


def test_ellipse_offset():
    e = Ellipse((0, 0), 1, 2)
    e.offset(1, 0)
    assert e.position == (1.0, 0.0)
    e.offset(0, 1)
    assert e.position == (1.0, 1.0)


def test_rectangle_ctor():
    """ Test rectangle creation
    """
    test_cases = (((0, 0), 1, 1), ((0, 0), 1, 2), ((1, 1), 1, 2))
    for pos, width, height in test_cases:
        r = Rectangle(pos, width, height)
        assert r.position == pos
        assert r.width == width
        assert r.height == height


def test_rectangle_hole_radius():
    """ Test rectangle hole diameter calculation
    """
    r = Rectangle((0, 0), 2, 2)
    assert 0 == r.hole_radius

    r = Rectangle((0, 0), 2, 2, 1)
    assert 0.5 == r.hole_radius


def test_rectangle_bounds():
    """ Test rectangle bounding box calculation
    """
    r = Rectangle((0, 0), 2, 2)
    xbounds, ybounds = r.bounding_box
    pytest.approx(xbounds, (-1, 1))
    pytest.approx(ybounds, (-1, 1))
    r = Rectangle((0, 0), 2, 2, rotation=45)
    xbounds, ybounds = r.bounding_box
    pytest.approx(xbounds, (-math.sqrt(2), math.sqrt(2)))
    pytest.approx(ybounds, (-math.sqrt(2), math.sqrt(2)))


def test_rectangle_vertices():
    sqrt2 = math.sqrt(2.0)
    TEST_VECTORS = [
        ((0, 0), 2.0, 2.0, 0.0, ((-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0))),
        ((0, 0), 2.0, 3.0, 0.0, ((-1.0, -1.5), (-1.0, 1.5), (1.0, 1.5), (1.0, -1.5))),
        ((0, 0), 2.0, 2.0, 90.0, ((-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0))),
        ((0, 0), 3.0, 2.0, 90.0, ((-1.0, -1.5), (-1.0, 1.5), (1.0, 1.5), (1.0, -1.5))),
        (
            (0, 0),
            2.0,
            2.0,
            45.0,
            ((-sqrt2, 0.0), (0.0, sqrt2), (sqrt2, 0), (0, -sqrt2)),
        ),
    ]
    for pos, width, height, rotation, expected in TEST_VECTORS:
        r = Rectangle(pos, width, height, rotation=rotation)
        for test, expect in zip(sorted(r.vertices), sorted(expected)):
            pytest.approx(test, expect)

    r = Rectangle((0, 0), 2.0, 2.0, rotation=0.0)
    r.rotation = 45.0
    for test, expect in zip(
        sorted(r.vertices),
        sorted(((-sqrt2, 0.0), (0.0, sqrt2), (sqrt2, 0), (0, -sqrt2))),
    ):
        pytest.approx(test, expect)


def test_rectangle_segments():

    r = Rectangle((0, 0), 2.0, 2.0)
    expected = [vtx for segment in r.segments for vtx in segment]
    for vertex in r.vertices:
        assert vertex in expected


def test_rectangle_conversion():
    """Test converting rectangles between units"""

    # Initially metric no hole
    r = Rectangle((2.54, 25.4), 254.0, 2540.0, units="metric")

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0

    # Initially metric with hole
    r = Rectangle((2.54, 25.4), 254.0, 2540.0, 127.0, units="metric")

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.hole_diameter == 127.0

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.hole_diameter == 5.0

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.hole_diameter == 5.0

    # Initially inch, no hole
    r = Rectangle((0.1, 1.0), 10.0, 100.0, units="inch")
    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0

    # Initially inch with hole
    r = Rectangle((0.1, 1.0), 10.0, 100.0, 5.0, units="inch")
    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.hole_diameter == 5.0

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.hole_diameter == 127.0

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.hole_diameter == 127.0


def test_rectangle_offset():
    r = Rectangle((0, 0), 1, 2)
    r.offset(1, 0)
    assert r.position == (1.0, 0.0)
    r.offset(0, 1)
    assert r.position == (1.0, 1.0)


def test_diamond_ctor():
    """ Test diamond creation
    """
    test_cases = (((0, 0), 1, 1), ((0, 0), 1, 2), ((1, 1), 1, 2))
    for pos, width, height in test_cases:
        d = Diamond(pos, width, height)
        assert d.position == pos
        assert d.width == width
        assert d.height == height


def test_diamond_bounds():
    """ Test diamond bounding box calculation
    """
    d = Diamond((0, 0), 2, 2)
    xbounds, ybounds = d.bounding_box
    pytest.approx(xbounds, (-1, 1))
    pytest.approx(ybounds, (-1, 1))
    d = Diamond((0, 0), math.sqrt(2), math.sqrt(2), rotation=45)
    xbounds, ybounds = d.bounding_box
    pytest.approx(xbounds, (-1, 1))
    pytest.approx(ybounds, (-1, 1))


def test_diamond_conversion():
    d = Diamond((2.54, 25.4), 254.0, 2540.0, units="metric")

    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.width == 254.0
    assert d.height == 2540.0

    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.width == 10.0
    assert d.height == 100.0

    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.width == 10.0
    assert d.height == 100.0

    d = Diamond((0.1, 1.0), 10.0, 100.0, units="inch")

    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.width == 10.0
    assert d.height == 100.0

    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.width == 254.0
    assert d.height == 2540.0

    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.width == 254.0
    assert d.height == 2540.0


def test_diamond_offset():
    d = Diamond((0, 0), 1, 2)
    d.offset(1, 0)
    assert d.position == (1.0, 0.0)
    d.offset(0, 1)
    assert d.position == (1.0, 1.0)


def test_chamfer_rectangle_ctor():
    """ Test chamfer rectangle creation
    """
    test_cases = (
        ((0, 0), 1, 1, 0.2, (True, True, False, False)),
        ((0, 0), 1, 2, 0.3, (True, True, True, True)),
        ((1, 1), 1, 2, 0.4, (False, False, False, False)),
    )
    for pos, width, height, chamfer, corners in test_cases:
        r = ChamferRectangle(pos, width, height, chamfer, corners)
        assert r.position == pos
        assert r.width == width
        assert r.height == height
        assert r.chamfer == chamfer
        pytest.approx(r.corners, corners)


def test_chamfer_rectangle_bounds():
    """ Test chamfer rectangle bounding box calculation
    """
    r = ChamferRectangle((0, 0), 2, 2, 0.2, (True, True, False, False))
    xbounds, ybounds = r.bounding_box
    pytest.approx(xbounds, (-1, 1))
    pytest.approx(ybounds, (-1, 1))
    r = ChamferRectangle((0, 0), 2, 2, 0.2, (True, True, False, False), rotation=45)
    xbounds, ybounds = r.bounding_box
    pytest.approx(xbounds, (-math.sqrt(2), math.sqrt(2)))
    pytest.approx(ybounds, (-math.sqrt(2), math.sqrt(2)))


def test_chamfer_rectangle_conversion():
    r = ChamferRectangle(
        (2.54, 25.4), 254.0, 2540.0, 0.254, (True, True, False, False), units="metric"
    )

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.chamfer == 0.254

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.chamfer == 0.01

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.chamfer == 0.01

    r = ChamferRectangle(
        (0.1, 1.0), 10.0, 100.0, 0.01, (True, True, False, False), units="inch"
    )
    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.chamfer == 0.01

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.chamfer == 0.254

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.chamfer == 0.254


def test_chamfer_rectangle_offset():
    r = ChamferRectangle((0, 0), 1, 2, 0.01, (True, True, False, False))
    r.offset(1, 0)
    assert r.position == (1.0, 0.0)
    r.offset(0, 1)
    assert r.position == (1.0, 1.0)


def test_chamfer_rectangle_vertices():
    TEST_VECTORS = [
        (
            1.0,
            (True, True, True, True),
            (
                (-2.5, -1.5),
                (-2.5, 1.5),
                (-1.5, 2.5),
                (1.5, 2.5),
                (2.5, 1.5),
                (2.5, -1.5),
                (1.5, -2.5),
                (-1.5, -2.5),
            ),
        ),
        (
            1.0,
            (True, False, False, False),
            ((-2.5, -2.5), (-2.5, 2.5), (1.5, 2.5), (2.5, 1.5), (2.5, -2.5)),
        ),
        (
            1.0,
            (False, True, False, False),
            ((-2.5, -2.5), (-2.5, 1.5), (-1.5, 2.5), (2.5, 2.5), (2.5, -2.5)),
        ),
        (
            1.0,
            (False, False, True, False),
            ((-2.5, -1.5), (-2.5, 2.5), (2.5, 2.5), (2.5, -2.5), (-1.5, -2.5)),
        ),
        (
            1.0,
            (False, False, False, True),
            ((-2.5, -2.5), (-2.5, 2.5), (2.5, 2.5), (2.5, -1.5), (1.5, -2.5)),
        ),
    ]
    for chamfer, corners, expected in TEST_VECTORS:
        r = ChamferRectangle((0, 0), 5, 5, chamfer, corners)
        assert set(r.vertices) == set(expected)


def test_round_rectangle_ctor():
    """ Test round rectangle creation
    """
    test_cases = (
        ((0, 0), 1, 1, 0.2, (True, True, False, False)),
        ((0, 0), 1, 2, 0.3, (True, True, True, True)),
        ((1, 1), 1, 2, 0.4, (False, False, False, False)),
    )
    for pos, width, height, radius, corners in test_cases:
        r = RoundRectangle(pos, width, height, radius, corners)
        assert r.position == pos
        assert r.width == width
        assert r.height == height
        assert r.radius == radius
        pytest.approx(r.corners, corners)


def test_round_rectangle_bounds():
    """ Test round rectangle bounding box calculation
    """
    r = RoundRectangle((0, 0), 2, 2, 0.2, (True, True, False, False))
    xbounds, ybounds = r.bounding_box
    pytest.approx(xbounds, (-1, 1))
    pytest.approx(ybounds, (-1, 1))
    r = RoundRectangle((0, 0), 2, 2, 0.2, (True, True, False, False), rotation=45)
    xbounds, ybounds = r.bounding_box
    pytest.approx(xbounds, (-math.sqrt(2), math.sqrt(2)))
    pytest.approx(ybounds, (-math.sqrt(2), math.sqrt(2)))


def test_round_rectangle_conversion():
    r = RoundRectangle(
        (2.54, 25.4), 254.0, 2540.0, 0.254, (True, True, False, False), units="metric"
    )

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.radius == 0.254

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.radius == 0.01

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.radius == 0.01

    r = RoundRectangle(
        (0.1, 1.0), 10.0, 100.0, 0.01, (True, True, False, False), units="inch"
    )

    r.to_inch()
    assert r.position == (0.1, 1.0)
    assert r.width == 10.0
    assert r.height == 100.0
    assert r.radius == 0.01

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.radius == 0.254

    r.to_metric()
    assert r.position == (2.54, 25.4)
    assert r.width == 254.0
    assert r.height == 2540.0
    assert r.radius == 0.254


def test_round_rectangle_offset():
    r = RoundRectangle((0, 0), 1, 2, 0.01, (True, True, False, False))
    r.offset(1, 0)
    assert r.position == (1.0, 0.0)
    r.offset(0, 1)
    assert r.position == (1.0, 1.0)


def test_obround_ctor():
    """ Test obround creation
    """
    test_cases = (((0, 0), 1, 1), ((0, 0), 1, 2), ((1, 1), 1, 2))
    for pos, width, height in test_cases:
        o = Obround(pos, width, height)
        assert o.position == pos
        assert o.width == width
        assert o.height == height


def test_obround_bounds():
    """ Test obround bounding box calculation
    """
    o = Obround((2, 2), 2, 4)
    xbounds, ybounds = o.bounding_box
    pytest.approx(xbounds, (1, 3))
    pytest.approx(ybounds, (0, 4))
    o = Obround((2, 2), 4, 2)
    xbounds, ybounds = o.bounding_box
    pytest.approx(xbounds, (0, 4))
    pytest.approx(ybounds, (1, 3))


def test_obround_orientation():
    o = Obround((0, 0), 2, 1)
    assert o.orientation == "horizontal"
    o = Obround((0, 0), 1, 2)
    assert o.orientation == "vertical"


def test_obround_subshapes():
    o = Obround((0, 0), 1, 4)
    ss = o.subshapes
    pytest.approx(ss["rectangle"].position, (0, 0))
    pytest.approx(ss["circle1"].position, (0, 1.5))
    pytest.approx(ss["circle2"].position, (0, -1.5))
    o = Obround((0, 0), 4, 1)
    ss = o.subshapes
    pytest.approx(ss["rectangle"].position, (0, 0))
    pytest.approx(ss["circle1"].position, (1.5, 0))
    pytest.approx(ss["circle2"].position, (-1.5, 0))


def test_obround_conversion():
    o = Obround((2.54, 25.4), 254.0, 2540.0, units="metric")

    # No effect
    o.to_metric()
    assert o.position == (2.54, 25.4)
    assert o.width == 254.0
    assert o.height == 2540.0

    o.to_inch()
    assert o.position == (0.1, 1.0)
    assert o.width == 10.0
    assert o.height == 100.0

    # No effect
    o.to_inch()
    assert o.position == (0.1, 1.0)
    assert o.width == 10.0
    assert o.height == 100.0

    o = Obround((0.1, 1.0), 10.0, 100.0, units="inch")

    # No effect
    o.to_inch()
    assert o.position == (0.1, 1.0)
    assert o.width == 10.0
    assert o.height == 100.0

    o.to_metric()
    assert o.position == (2.54, 25.4)
    assert o.width == 254.0
    assert o.height == 2540.0

    # No effect
    o.to_metric()
    assert o.position == (2.54, 25.4)
    assert o.width == 254.0
    assert o.height == 2540.0


def test_obround_offset():
    o = Obround((0, 0), 1, 2)
    o.offset(1, 0)
    assert o.position == (1.0, 0.0)
    o.offset(0, 1)
    assert o.position == (1.0, 1.0)


def test_polygon_ctor():
    """ Test polygon creation
    """
    test_cases = (((0, 0), 3, 5, 0), ((0, 0), 5, 6, 0), ((1, 1), 7, 7, 45))
    for pos, sides, radius, hole_diameter in test_cases:
        p = Polygon(pos, sides, radius, hole_diameter)
        assert p.position == pos
        assert p.sides == sides
        assert p.radius == radius
        assert p.hole_diameter == hole_diameter


def test_polygon_bounds():
    """ Test polygon bounding box calculation
    """
    p = Polygon((2, 2), 3, 2, 0)
    xbounds, ybounds = p.bounding_box
    pytest.approx(xbounds, (0, 4))
    pytest.approx(ybounds, (0, 4))
    p = Polygon((2, 2), 3, 4, 0)
    xbounds, ybounds = p.bounding_box
    pytest.approx(xbounds, (-2, 6))
    pytest.approx(ybounds, (-2, 6))


def test_polygon_conversion():
    p = Polygon((2.54, 25.4), 3, 254.0, 0, units="metric")

    # No effect
    p.to_metric()
    assert p.position == (2.54, 25.4)
    assert p.radius == 254.0

    p.to_inch()
    assert p.position == (0.1, 1.0)
    assert p.radius == 10.0

    # No effect
    p.to_inch()
    assert p.position == (0.1, 1.0)
    assert p.radius == 10.0

    p = Polygon((0.1, 1.0), 3, 10.0, 0, units="inch")

    # No effect
    p.to_inch()
    assert p.position == (0.1, 1.0)
    assert p.radius == 10.0

    p.to_metric()
    assert p.position == (2.54, 25.4)
    assert p.radius == 254.0

    # No effect
    p.to_metric()
    assert p.position == (2.54, 25.4)
    assert p.radius == 254.0


def test_polygon_offset():
    p = Polygon((0, 0), 5, 10, 0)
    p.offset(1, 0)
    assert p.position == (1.0, 0.0)
    p.offset(0, 1)
    assert p.position == (1.0, 1.0)


def test_region_ctor():
    """ Test Region creation
    """
    apt = Circle((0, 0), 0)
    lines = (
        Line((0, 0), (1, 0), apt),
        Line((1, 0), (1, 1), apt),
        Line((1, 1), (0, 1), apt),
        Line((0, 1), (0, 0), apt),
    )
    points = ((0, 0), (1, 0), (1, 1), (0, 1))
    r = Region(lines)
    for i, p in enumerate(lines):
        assert r.primitives[i] == p


def test_region_bounds():
    """ Test region bounding box calculation
    """
    apt = Circle((0, 0), 0)
    lines = (
        Line((0, 0), (1, 0), apt),
        Line((1, 0), (1, 1), apt),
        Line((1, 1), (0, 1), apt),
        Line((0, 1), (0, 0), apt),
    )
    r = Region(lines)
    xbounds, ybounds = r.bounding_box
    pytest.approx(xbounds, (0, 1))
    pytest.approx(ybounds, (0, 1))


def test_region_offset():
    apt = Circle((0, 0), 0)
    lines = (
        Line((0, 0), (1, 0), apt),
        Line((1, 0), (1, 1), apt),
        Line((1, 1), (0, 1), apt),
        Line((0, 1), (0, 0), apt),
    )
    r = Region(lines)
    xlim, ylim = r.bounding_box
    r.offset(0, 1)
    new_xlim, new_ylim = r.bounding_box
    pytest.approx(new_xlim, xlim)
    pytest.approx(new_ylim, tuple([y + 1 for y in ylim]))


def test_round_butterfly_ctor():
    """ Test round butterfly creation
    """
    test_cases = (((0, 0), 3), ((0, 0), 5), ((1, 1), 7))
    for pos, diameter in test_cases:
        b = RoundButterfly(pos, diameter)
        assert b.position == pos
        assert b.diameter == diameter
        assert b.radius == diameter / 2.0


def test_round_butterfly_ctor_validation():
    """ Test RoundButterfly argument validation
    """
    pytest.raises(TypeError, RoundButterfly, 3, 5)
    pytest.raises(TypeError, RoundButterfly, (3, 4, 5), 5)


def test_round_butterfly_conversion():
    b = RoundButterfly((2.54, 25.4), 254.0, units="metric")

    # No Effect
    b.to_metric()
    assert b.position == (2.54, 25.4)
    assert b.diameter == (254.0)

    b.to_inch()
    assert b.position == (0.1, 1.0)
    assert b.diameter == 10.0

    # No effect
    b.to_inch()
    assert b.position == (0.1, 1.0)
    assert b.diameter == 10.0

    b = RoundButterfly((0.1, 1.0), 10.0, units="inch")

    # No effect
    b.to_inch()
    assert b.position == (0.1, 1.0)
    assert b.diameter == 10.0

    b.to_metric()
    assert b.position == (2.54, 25.4)
    assert b.diameter == (254.0)

    # No Effect
    b.to_metric()
    assert b.position == (2.54, 25.4)
    assert b.diameter == (254.0)


def test_round_butterfly_offset():
    b = RoundButterfly((0, 0), 1)
    b.offset(1, 0)
    assert b.position == (1.0, 0.0)
    b.offset(0, 1)
    assert b.position == (1.0, 1.0)


def test_round_butterfly_bounds():
    """ Test RoundButterfly bounding box calculation
    """
    b = RoundButterfly((0, 0), 2)
    xbounds, ybounds = b.bounding_box
    pytest.approx(xbounds, (-1, 1))
    pytest.approx(ybounds, (-1, 1))


def test_square_butterfly_ctor():
    """ Test SquareButterfly creation
    """
    test_cases = (((0, 0), 3), ((0, 0), 5), ((1, 1), 7))
    for pos, side in test_cases:
        b = SquareButterfly(pos, side)
        assert b.position == pos
        assert b.side == side


def test_square_butterfly_ctor_validation():
    """ Test SquareButterfly argument validation
    """
    pytest.raises(TypeError, SquareButterfly, 3, 5)
    pytest.raises(TypeError, SquareButterfly, (3, 4, 5), 5)


def test_square_butterfly_bounds():
    """ Test SquareButterfly bounding box calculation
    """
    b = SquareButterfly((0, 0), 2)
    xbounds, ybounds = b.bounding_box
    pytest.approx(xbounds, (-1, 1))
    pytest.approx(ybounds, (-1, 1))


def test_squarebutterfly_conversion():
    b = SquareButterfly((2.54, 25.4), 254.0, units="metric")

    # No effect
    b.to_metric()
    assert b.position == (2.54, 25.4)
    assert b.side == (254.0)

    b.to_inch()
    assert b.position == (0.1, 1.0)
    assert b.side == 10.0

    # No effect
    b.to_inch()
    assert b.position == (0.1, 1.0)
    assert b.side == 10.0

    b = SquareButterfly((0.1, 1.0), 10.0, units="inch")

    # No effect
    b.to_inch()
    assert b.position == (0.1, 1.0)
    assert b.side == 10.0

    b.to_metric()
    assert b.position == (2.54, 25.4)
    assert b.side == (254.0)

    # No effect
    b.to_metric()
    assert b.position == (2.54, 25.4)
    assert b.side == (254.0)


def test_square_butterfly_offset():
    b = SquareButterfly((0, 0), 1)
    b.offset(1, 0)
    assert b.position == (1.0, 0.0)
    b.offset(0, 1)
    assert b.position == (1.0, 1.0)


def test_donut_ctor():
    """ Test Donut primitive creation
    """
    test_cases = (
        ((0, 0), "round", 3, 5),
        ((0, 0), "square", 5, 7),
        ((1, 1), "hexagon", 7, 9),
        ((2, 2), "octagon", 9, 11),
    )
    for pos, shape, in_d, out_d in test_cases:
        d = Donut(pos, shape, in_d, out_d)
        assert d.position == pos
        assert d.shape == shape
        assert d.inner_diameter == in_d
        assert d.outer_diameter == out_d


def test_donut_ctor_validation():
    pytest.raises(TypeError, Donut, 3, "round", 5, 7)
    pytest.raises(TypeError, Donut, (3, 4, 5), "round", 5, 7)
    pytest.raises(ValueError, Donut, (0, 0), "triangle", 3, 5)
    pytest.raises(ValueError, Donut, (0, 0), "round", 5, 3)


def test_donut_bounds():
    d = Donut((0, 0), "round", 0.0, 2.0)
    xbounds, ybounds = d.bounding_box
    assert xbounds == (-1.0, 1.0)
    assert ybounds == (-1.0, 1.0)


def test_donut_conversion():
    d = Donut((2.54, 25.4), "round", 254.0, 2540.0, units="metric")

    # No effect
    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.inner_diameter == 254.0
    assert d.outer_diameter == 2540.0

    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.inner_diameter == 10.0
    assert d.outer_diameter == 100.0

    # No effect
    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.inner_diameter == 10.0
    assert d.outer_diameter == 100.0

    d = Donut((0.1, 1.0), "round", 10.0, 100.0, units="inch")

    # No effect
    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.inner_diameter == 10.0
    assert d.outer_diameter == 100.0

    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.inner_diameter == 254.0
    assert d.outer_diameter == 2540.0

    # No effect
    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.inner_diameter == 254.0
    assert d.outer_diameter == 2540.0


def test_donut_offset():
    d = Donut((0, 0), "round", 1, 10)
    d.offset(1, 0)
    assert d.position == (1.0, 0.0)
    d.offset(0, 1)
    assert d.position == (1.0, 1.0)


def test_drill_ctor():
    """ Test drill primitive creation
    """
    test_cases = (((0, 0), 2), ((1, 1), 3), ((2, 2), 5))
    for position, diameter in test_cases:
        d = Drill(position, diameter)
        assert d.position == position
        assert d.diameter == diameter
        assert d.radius == diameter / 2.0


def test_drill_ctor_validation():
    """ Test drill argument validation
    """
    pytest.raises(TypeError, Drill, 3, 5)
    pytest.raises(TypeError, Drill, (3, 4, 5), 5)


def test_drill_bounds():
    d = Drill((0, 0), 2)
    xbounds, ybounds = d.bounding_box
    pytest.approx(xbounds, (-1, 1))
    pytest.approx(ybounds, (-1, 1))
    d = Drill((1, 2), 2)
    xbounds, ybounds = d.bounding_box
    pytest.approx(xbounds, (0, 2))
    pytest.approx(ybounds, (1, 3))


def test_drill_conversion():
    d = Drill((2.54, 25.4), 254.0, units="metric")

    # No effect
    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.diameter == 254.0

    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.diameter == 10.0

    # No effect
    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.diameter == 10.0

    d = Drill((0.1, 1.0), 10.0, units="inch")

    # No effect
    d.to_inch()
    assert d.position == (0.1, 1.0)
    assert d.diameter == 10.0

    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.diameter == 254.0

    # No effect
    d.to_metric()
    assert d.position == (2.54, 25.4)
    assert d.diameter == 254.0


def test_drill_offset():
    d = Drill((0, 0), 1.0)
    d.offset(1, 0)
    assert d.position == (1.0, 0.0)
    d.offset(0, 1)
    assert d.position == (1.0, 1.0)


def test_drill_equality():
    d = Drill((2.54, 25.4), 254.0)
    d1 = Drill((2.54, 25.4), 254.0)
    assert d == d1
    d1 = Drill((2.54, 25.4), 254.2)
    assert d != d1


def test_slot_bounds():
    """ Test Slot primitive bounding box calculation
    """
    cases = [
        ((0, 0), (1, 1), ((-1, 2), (-1, 2))),
        ((-1, -1), (1, 1), ((-2, 2), (-2, 2))),
        ((1, 1), (-1, -1), ((-2, 2), (-2, 2))),
        ((-1, 1), (1, -1), ((-2, 2), (-2, 2))),
    ]

    for start, end, expected in cases:
        s = Slot(start, end, 2.0)
        assert s.bounding_box == expected
