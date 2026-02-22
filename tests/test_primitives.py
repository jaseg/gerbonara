#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2026 Jan Sebastian Götte <gerbonara@jaseg.de>
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
# Based on https://github.com/tracespace/tracespace
#

import math
from contextlib import contextmanager

from PIL import Image
import pytest

from gerbonara.rs274x import GerberFile
from gerbonara.graphic_objects import Line, Arc, Flash, Region
from gerbonara.apertures import CircleAperture, RectangleAperture, ObroundAperture, PolygonAperture
from gerbonara.cam import FileSettings
from gerbonara.utils import MM, Inch

from .image_support import svg_soup
from .utils import *

@contextmanager
def object_test(tmpfile, img_support, epsilon=1e-4):
    gbr = GerberFile()

    yield gbr

    gbr.offset(25.0, 25.0)

    bounds = (0.0, 0.0), (2.0, 2.0) # bottom left, top right

    # The below code is mostly copy-pasted from test_rs274x.py.

    out_svg = tmpfile('SVG Output', '.svg')
    with open(out_svg, 'w') as f:
        f.write(str(gbr.to_svg(force_bounds=bounds, arg_unit='inch', fg='black', bg='white')))

    out_gbr = tmpfile('GBR Output', '.gbr')
    gbr.save(out_gbr)

    # NOTE: Instead of having gerbv directly export a PNG, we ask gerbv to output SVG which we then rasterize using
    # resvg. We have to do this since gerbv's built-in cairo-based PNG export has severe aliasing issues. In contrast,
    # using resvg for both allows an apples-to-apples comparison of both results.
    ref_svg = tmpfile('Reference export', '.svg')
    ref_png = tmpfile('Reference render', '.png')
    img_support.gerbv_export(out_gbr, ref_svg, origin=bounds[0], size=bounds[1], fg='#000000', bg='#ffffff')
    with svg_soup(ref_svg) as soup:
        img_support.cleanup_gerbv_svg(soup)
    img_support.svg_to_png(ref_svg, ref_png, dpi=300, bg='white')

    out_png = tmpfile('Output render', '.png')
    img_support.svg_to_png(out_svg, out_png, dpi=300, bg='white')

    mean, _max, hist = img_support.image_difference(ref_png, out_png, diff_out=tmpfile('Difference', '.png'))
    assert hist[9] < 1
    assert mean < epsilon
    assert hist[3:].sum() < epsilon*hist.size

@pytest.mark.parametrize('angle_deg', [0, 5, -5, 10, -10, 15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90, 120, -120, 180, 153, 155, 157])
def test_line(angle_deg, tmpfile, img_support):
    with object_test(tmpfile, img_support) as gbr:
        angle = math.radians(angle_deg)
        l = 10
        obj = Line(
            x1=0, y1=0,
            x2=l*math.cos(angle), y2=l*math.sin(angle),
            aperture=CircleAperture(3.0, unit=MM),
            unit=MM
        )

        gbr.objects.append(obj)


def test_zero_length_line(tmpfile, img_support):
    with object_test(tmpfile, img_support) as gbr:
        for x, y in [(0, 0), (0, 10), (10, 15)]:
            obj = Line(
                x1=x, y1=y,
                x2=x, y2=y,
                aperture=CircleAperture(3.0, unit=MM),
                unit=MM
            )
            gbr.objects.append(obj)

# NOTE: We explicitly do not test the sweep_angle = 0 deg case here. In this case, we decided to always draw a full circle.
# IIRC this is in line with some Gerber implementations in the wild, and it enables drawing a clean circle using a single Arc.
# gerbv will not do this, and so this would cause a failing test for no particular reason.
# TODO: Check 360 degree sweep angle case
@pytest.mark.parametrize('start_angle_deg', [0, 5, 10, 15, 30, 45, 60, 75, 90, 120, 180, 153, 155, 157, 190, 200, 210, 240, 250, 255, 270, 280, 290, 340, 350, 355, 358])
@pytest.mark.parametrize('sweep_angle_deg', [1, 5, 10, 15, 30, 45, 60, 75, 90, 120, 180, 153, 155, 157, 190, 200, 210, 240, 250, 255, 270, 280, 290, 340, 350, 355, 358])
@pytest.mark.parametrize('clockwise', [True, False])
def test_arc(start_angle_deg, sweep_angle_deg, clockwise, tmpfile, img_support):
    # Use large epsilon since someone approximates arcs with SVG beziers here, and that approximation really shows up.
    with object_test(tmpfile, img_support, epsilon=1e-2) as gbr:
        start_angle = math.radians(start_angle_deg)
        sweep_angle = math.radians(sweep_angle_deg)
        r = 10

        x1, y1 = r*math.cos(start_angle), r*math.sin(start_angle)
        x2, y2 = r*math.cos(start_angle + sweep_angle), r*math.sin(start_angle + sweep_angle)

        obj = Arc(
            x1=x1, y1=y1,
            x2=x2, y2=y2,
            cx=-x1, cy=-y1,
            clockwise=clockwise,
            aperture=CircleAperture(3.0, unit=MM),
            unit=MM
        )

        gbr.objects.append(obj)


@pytest.mark.parametrize('x,y', [(0, 0), (5, 5), (10, 0), (0, 10), (-5, 5)])
@pytest.mark.parametrize('aperture', [
    CircleAperture(3.0, unit=MM),
    CircleAperture(2.5, hole_dia=1.0, unit=MM),
])
def test_flash_circle(x, y, aperture, tmpfile, img_support):
    with object_test(tmpfile, img_support) as gbr:
        obj = Flash(
            x=x, y=y,
            aperture=aperture,
            unit=MM
        )
        gbr.objects.append(obj)


@pytest.mark.parametrize('aperture_type', [
    lambda: CircleAperture(4.0, unit=MM),
    lambda: CircleAperture(4.0, hole_dia=1.5, unit=MM),
    lambda: RectangleAperture(4.0, 3.0, unit=MM),
    lambda: ObroundAperture(4.0, 2.5, unit=MM),
    lambda: PolygonAperture(4.0, 6, unit=MM),
])
def test_flash_aperture_types(aperture_type, tmpfile, img_support):
    """Test Flash with different aperture types."""
    with object_test(tmpfile, img_support, epsilon=1e-3) as gbr:
        aperture = aperture_type()

        # Create a grid of flashes with this aperture type
        positions = [(0, 0), (8, 0), (0, 8), (8, 8), (4, 4)]
        for x, y in positions:
            obj = Flash(
                x=x, y=y,
                aperture=aperture,
                unit=MM
            )
            gbr.objects.append(obj)


@pytest.mark.parametrize('w,h', [(5, 5), (8, 4), (4, 8), (10, 3)])
def test_region_rectangle(w, h, tmpfile, img_support):
    """Test Region objects creating rectangles."""
    with object_test(tmpfile, img_support) as gbr:
        x, y = 5, 5
        obj = Region.from_rectangle(x, y, w, h, unit=MM)
        gbr.objects.append(obj)


@pytest.mark.parametrize('start_angle_deg', [0, 45, 90, 135, 180, 225, 270, 315])
@pytest.mark.parametrize('sweep_angle_deg', [90, 180, 270])
def test_region_arc_segments(start_angle_deg, sweep_angle_deg, tmpfile, img_support):
    """Test Region objects with arc segments."""
    with object_test(tmpfile, img_support, epsilon=1e-2) as gbr:
        start_angle = math.radians(start_angle_deg)
        sweep_angle = math.radians(sweep_angle_deg)
        r = 15

        # Create a region that looks like a pie slice
        region = Region(unit=MM)

        region.outline.append((0, 0))
        region.outline.append((r * math.cos(start_angle), r * math.sin(start_angle)))
        region.outline.append((r * math.cos(start_angle + sweep_angle), r * math.sin(start_angle + sweep_angle)))
        region.outline.append((0, 0))
        region.arc_centers.append(None)
        region.arc_centers.append(None)
        region.arc_centers.append((True, (0, 0)))

        gbr.objects.append(region)
