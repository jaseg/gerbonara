#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Garret Fick <garret@ficksworkshop.com>
import os
import shutil
import io
import tempfile
import uuid
from pathlib import Path

import pytest
from PIL import Image
import numpy as np

from ..render.cairo_backend import GerberCairoContext
from ..rs274x import read

class Tempdir:
    def __init__(self):
        self.path = tempfile.mkdtemp(prefix='gerbonara-test-')
        self.delete = True

    def cleanup(self):
        if self.delete:
            shutil.rmtree(self.path)

    def create(self, prefix='fail-', suffix=''):
        return Path(self.path) / f'{prefix}{uuid.uuid4()}{suffix}'

    def keep(self):
        self.delete = False

output_dir = Tempdir()
@pytest.fixture(scope='session', autouse=True)
def cleanup(request):
    global output_dir
    request.addfinalizer(output_dir.cleanup)

def test_render_two_boxes():
    """Umaco exapmle of two boxes"""
    _test_render(
        "resources/example_two_square_boxes.gbr", "golden/example_two_square_boxes.png"
    )


def _DISABLED_test_render_single_quadrant():
    """Umaco exapmle of a single quadrant arc"""
    _test_render(
        "resources/example_single_quadrant.gbr", "golden/example_single_quadrant.png"
    )


def test_render_simple_contour():
    """Umaco exapmle of a simple arrow-shaped contour"""
    gerber = _test_render(
        "resources/example_simple_contour.gbr", "golden/example_simple_contour.png"
    )

    # Check the resulting dimensions
    assert ((2.0, 11.0), (1.0, 9.0)) == gerber.bounding_box


def test_render_single_contour_1():
    """Umaco example of a single contour

    The resulting image for this test is used by other tests because they must generate the same output."""
    _test_render(
        "resources/example_single_contour_1.gbr", "golden/example_single_contour.png",
        0.001 # TODO: It looks like we have some aliasing artifacts here. Make sure this is not caused by an actual error.
    )


def test_render_single_contour_2():
    """Umaco exapmle of a single contour, alternate contour end order

    The resulting image for this test is used by other tests because they must generate the same output."""
    _test_render(
        "resources/example_single_contour_2.gbr", "golden/example_single_contour.png",
        0.001 # TODO: It looks like we have some aliasing artifacts here. Make sure this is not caused by an actual error.
    )


def test_render_single_contour_3():
    """Umaco exapmle of a single contour with extra line"""
    _test_render(
        "resources/example_single_contour_3.gbr", "golden/example_single_contour_3.png",
        0.001 # TODO: It looks like we have some aliasing artifacts here. Make sure this is not caused by an actual error.
    )


def test_render_not_overlapping_contour():
    """Umaco example of D02 staring a second contour"""
    _test_render(
        "resources/example_not_overlapping_contour.gbr",
        "golden/example_not_overlapping_contour.png",
    )


def test_render_not_overlapping_touching():
    """Umaco example of D02 staring a second contour"""
    _test_render(
        "resources/example_not_overlapping_touching.gbr",
        "golden/example_not_overlapping_touching.png",
    )


def test_render_overlapping_touching():
    """Umaco example of D02 staring a second contour"""
    _test_render(
        "resources/example_overlapping_touching.gbr",
        "golden/example_overlapping_touching.png",
    )


def test_render_overlapping_contour():
    """Umaco example of D02 staring a second contour"""
    _test_render(
        "resources/example_overlapping_contour.gbr",
        "golden/example_overlapping_contour.png",
    )


def _DISABLED_test_render_level_holes():
    """Umaco example of using multiple levels to create multiple holes"""

    # TODO This is clearly rendering wrong. I'm temporarily checking this in because there are more
    # rendering fixes in the related repository that may resolve these.
    _test_render(
        "resources/example_level_holes.gbr", "golden/example_overlapping_contour.png"
    )


def _DISABLED_test_render_cutin():
    """Umaco example of using a cutin"""

    # TODO This is clearly rendering wrong.
    _test_render(
        "resources/example_cutin.gbr",
        "golden/example_cutin.png",
        "/Users/ham/Desktop/cutin.png",
    )


def test_render_fully_coincident():
    """Umaco example of coincident lines rendering two contours"""

    _test_render(
        "resources/example_fully_coincident.gbr", "golden/example_fully_coincident.png"
    )


def test_render_coincident_hole():
    """Umaco example of coincident lines rendering a hole in the contour"""

    _test_render(
        "resources/example_coincident_hole.gbr", "golden/example_coincident_hole.png"
    )


def test_render_cutin_multiple():
    """Umaco example of a region with multiple cutins"""

    _test_render(
        "resources/example_cutin_multiple.gbr", "golden/example_cutin_multiple.png"
    )


def test_flash_circle():
    """Umaco example a simple circular flash with and without a hole"""

    _test_render(
        "resources/example_flash_circle.gbr",
        "golden/example_flash_circle.png",
    )


def test_flash_rectangle():
    """Umaco example a simple rectangular flash with and without a hole"""

    _test_render(
        "resources/example_flash_rectangle.gbr", "golden/example_flash_rectangle.png"
    )


def test_flash_obround():
    """Umaco example a simple obround flash with and without a hole"""

    _test_render(
        "resources/example_flash_obround.gbr", "golden/example_flash_obround.png"
    )


def test_flash_polygon():
    """Umaco example a simple polygon flash with and without a hole"""

    _test_render(
        "resources/example_flash_polygon.gbr", "golden/example_flash_polygon.png"
    )


def test_holes_dont_clear():
    """Umaco example that an aperture with a hole does not clear the area"""

    _test_render(
        "resources/example_holes_dont_clear.gbr", "golden/example_holes_dont_clear.png"
    )


def _DISABLED_test_render_am_exposure_modifier():
    """Umaco example that an aperture macro with a hole does not clear the area"""

    _test_render(
        "resources/example_am_exposure_modifier.gbr",
        "golden/example_am_exposure_modifier.png",
    )


def test_render_svg_simple_contour():
    """Example of rendering to an SVG file"""
    _test_simple_render_svg("resources/example_simple_contour.gbr")


def _resolve_path(path):
    return os.path.join(os.path.dirname(__file__), path)

def images_match(reference, output, max_delta):
    ref, out = Image.open(reference), Image.open(output)
    ref, out = np.array(ref), np.array(out)
    # convert to grayscale
    ref, out = ref.astype(float).mean(axis=2), out.astype(float).mean(axis=2)

    delta = np.abs(out - ref).astype(float) / 255
    
    if delta.mean() > max_delta:
        print(f'Renderings mismatch: {delta.mean()=}, {max_delta=}')
        print(f'Reference image: {Path(reference).absolute()}')
        print(f'Actual output: {output}')
        def print_stats(name, ref):
            print(name, 'stats:', ref.min(), ref.mean(), ref.max(), 'std:', ref.std())
        print_stats('reference', ref)
        print_stats('actual', out)

        global output_dir
        output_dir.keep()

        return False

    return True


def _test_render(gerber_path, png_expected_path, max_delta=1e-6):
    """Render the gerber file and compare to the expected PNG output.

    Parameters
    ----------
    gerber_path : string
        Path to Gerber file to open
    png_expected_path : string
        Path to the PNG file to compare to
    create_output : string|None
        If not None, write the generated PNG to the specified path.
        This is primarily to help with
    """

    gerber_path = _resolve_path(gerber_path)
    png_expected_path = _resolve_path(png_expected_path)

    gerber = read(gerber_path)

    # Create PNG image to the memory stream
    ctx = GerberCairoContext()
    gerber.render(ctx)

    global output_dir
    with output_dir.create(suffix='.png') as outfile:
        actual_bytes = ctx.dump(outfile)

        assert images_match(png_expected_path, outfile, max_delta)

    return gerber


def _test_simple_render_svg(gerber_path):
    """Render the gerber file as SVG

    Note: verifies only the header, not the full content.

    Parameters
    ----------
    gerber_path : string
        Path to Gerber file to open
    """

    gerber_path = _resolve_path(gerber_path)
    gerber = read(gerber_path)

    # Create SVG image to the memory stream
    ctx = GerberCairoContext()
    gerber.render(ctx)

    temp_dir = tempfile.mkdtemp()
    svg_temp_path = os.path.join(temp_dir, "output.svg")

    assert not os.path.exists(svg_temp_path)
    ctx.dump(svg_temp_path)
    assert os.path.exists(svg_temp_path)

    with open(svg_temp_path, "r") as expected_file:
        expected_bytes = expected_file.read()
    assert expected_bytes[:38] == '<?xml version="1.0" encoding="UTF-8"?>'

    shutil.rmtree(temp_dir)

