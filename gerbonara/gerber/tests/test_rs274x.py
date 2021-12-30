#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Hamilton Kibbe <ham@hamiltonkib.be>
import os
import re
import math
import functools
import tempfile
import shutil
from argparse import Namespace
from itertools import chain
from pathlib import Path

import pytest

from ..rs274x import GerberFile
from ..cam import FileSettings

from .image_support import gerber_difference


deg_to_rad = lambda a: a/180 * math.pi

fail_dir = Path('gerbonara_test_failures')
reference_path = lambda reference: Path(__file__).parent / 'resources' / reference

@pytest.fixture
def temp_files(request):
    with tempfile.NamedTemporaryFile(suffix='.gbr') as tmp_out_gbr,\
         tempfile.NamedTemporaryFile(suffix='.png') as tmp_out_png:

        yield Path(tmp_out_gbr.name), Path(tmp_out_png.name)

        if request.node.rep_call.failed:
            module, _, test_name = request.node.nodeid.rpartition('::')
            _test, _, test_name = test_name.partition('_')
            test_name, _, _ext = test_name.partition('.')
            test_name = re.sub(r'[^\w\d]', '_', test_name)
            fail_dir.mkdir(exist_ok=True)
            perm_path_gbr = fail_dir / f'failure_{test_name}.gbr'
            perm_path_png = fail_dir / f'failure_{test_name}.png'
            shutil.copy(tmp_out_gbr.name, perm_path_gbr)
            shutil.copy(tmp_out_png.name, perm_path_png)
            print(f'Failing output saved to {perm_path_gbr}')
            print(f'Reference file is {reference_path(request.node.funcargs["reference"])}')
            print(f'Difference image saved to {perm_path_png}')
            print(f'gerbv command line:')
            print(f'gerbv {perm_path_gbr} {reference_path(request.node.funcargs["reference"])}')

to_gerbv_svg_units = lambda val, unit='mm': val*72 if unit == 'inch' else val/25.4*72

REFERENCE_FILES = [ l.strip() for l in '''
    board_outline.GKO
    example_outline_with_arcs.gbr
    example_two_square_boxes.gbr
    example_coincident_hole.gbr
    example_cutin.gbr
    example_cutin_multiple.gbr
    example_flash_circle.gbr
    example_flash_obround.gbr
    example_flash_polygon.gbr
    example_flash_rectangle.gbr
    example_fully_coincident.gbr
    example_guess_by_content.g0
    example_holes_dont_clear.gbr
    example_level_holes.gbr
    example_not_overlapping_contour.gbr
    example_not_overlapping_touching.gbr
    example_overlapping_contour.gbr
    example_overlapping_touching.gbr
    example_simple_contour.gbr
    example_single_contour_1.gbr
    example_single_contour_2.gbr
    example_single_contour_3.gbr
    example_am_exposure_modifier.gbr
    bottom_copper.GBL
    bottom_mask.GBS
    bottom_silk.GBO
    eagle_files/copper_bottom_l4.gbr
    eagle_files/copper_inner_l2.gbr
    eagle_files/copper_inner_l3.gbr
    eagle_files/copper_top_l1.gbr
    eagle_files/profile.gbr
    eagle_files/silkscreen_bottom.gbr
    eagle_files/silkscreen_top.gbr
    eagle_files/soldermask_bottom.gbr
    eagle_files/soldermask_top.gbr
    eagle_files/solderpaste_bottom.gbr
    eagle_files/solderpaste_top.gbr
    multiline_read.ger
    test_fine_lines_x.gbr
    test_fine_lines_y.gbr
    top_copper.GTL
    top_mask.GTS
    top_silk.GTO
'''.splitlines() if l ]

MIN_REFERENCE_FILES = [
    'example_two_square_boxes.gbr',
    'example_outline_with_arcs.gbr',
    'example_flash_circle.gbr',
    'example_flash_polygon.gbr',
    'example_flash_rectangle.gbr',
    'example_simple_contour.gbr',
    'example_am_exposure_modifier.gbr',
    'bottom_copper.GBL',
    'bottom_silk.GBO',
    'eagle_files/copper_bottom_l4.gbr'
    ]

@pytest.mark.filterwarnings('ignore:Deprecated.*statement found.*:DeprecationWarning')
@pytest.mark.filterwarnings('ignore::SyntaxWarning')
@pytest.mark.parametrize('reference', REFERENCE_FILES)
def test_round_trip(temp_files, reference):
    tmp_gbr, tmp_png = temp_files
    ref = reference_path(reference)

    GerberFile.open(ref).save(tmp_gbr)

    mean, _max, hist = gerber_difference(ref, tmp_gbr, diff_out=tmp_png)
    assert mean < 5e-5
    assert hist[9] == 0
    assert hist[3:].sum() < 5e-5*hist.size

TEST_ANGLES = [90, 180, 270, 30, 1.5, 10, 360, 1024, -30, -90]
TEST_OFFSETS = [(0, 0), (100, 0), (0, 100), (2, 0), (10, 100)]

@pytest.mark.filterwarnings('ignore:Deprecated.*statement found.*:DeprecationWarning')
@pytest.mark.filterwarnings('ignore::SyntaxWarning')
@pytest.mark.parametrize('reference', MIN_REFERENCE_FILES)
@pytest.mark.parametrize('angle', TEST_ANGLES)
def test_rotation(temp_files, reference, angle):
    if 'flash_rectangle' in reference and angle == 1024:
        # gerbv's rendering of this is broken, the hole is missing.
        return

    tmp_gbr, tmp_png = temp_files
    ref = reference_path(reference)

    f = GerberFile.open(ref)
    f.rotate(deg_to_rad(angle))
    f.save(tmp_gbr)

    cx, cy = 0, to_gerbv_svg_units(10, unit='inch')
    mean, _max, hist = gerber_difference(ref, tmp_gbr, diff_out=tmp_png, svg_transform=f'rotate({angle} {cx} {cy})')
    assert mean < 1e-3 # relax mean criterion compared to above.
    assert hist[9] == 0

@pytest.mark.filterwarnings('ignore:Deprecated.*statement found.*:DeprecationWarning')
@pytest.mark.filterwarnings('ignore::SyntaxWarning')
@pytest.mark.parametrize('reference', MIN_REFERENCE_FILES)
@pytest.mark.parametrize('angle', TEST_ANGLES)
@pytest.mark.parametrize('center', [(0, 0), (-10, -10), (10, 10), (10, 0), (0, -10), (-10, 10), (10, 20)])
def test_rotation_center(temp_files, reference, angle, center):
    if 'flash_rectangle' in reference and angle in (30, 1024):
        # gerbv's rendering of this is broken, the hole is missing.
        return
    tmp_gbr, tmp_png = temp_files
    ref = reference_path(reference)

    f = GerberFile.open(ref)
    f.rotate(deg_to_rad(angle), center=center)
    f.save(tmp_gbr)

    # calculate circle center in SVG coordinates 
    size = (10, 10) # inches
    cx, cy = to_gerbv_svg_units(center[0]), to_gerbv_svg_units(10, 'inch')-to_gerbv_svg_units(center[1], 'mm')
    mean, _max, hist = gerber_difference(ref, tmp_gbr, diff_out=tmp_png,
            svg_transform=f'rotate({angle} {cx} {cy})',
            size=size)
    assert mean < 1e-3
    assert hist[9] < 50
    assert hist[3:].sum() < 1e-3*hist.size

@pytest.mark.filterwarnings('ignore:Deprecated.*statement found.*:DeprecationWarning')
@pytest.mark.filterwarnings('ignore::SyntaxWarning')
@pytest.mark.parametrize('reference', MIN_REFERENCE_FILES)
@pytest.mark.parametrize('offset', TEST_OFFSETS)
def test_offset(temp_files, reference, offset):
    tmp_gbr, tmp_png = temp_files
    ref = reference_path(reference)

    f = GerberFile.open(ref)
    f.offset(*offset)
    f.save(tmp_gbr, settings=FileSettings(unit=f.unit, number_format=(4,7)))

    # flip y offset since svg's y axis is flipped compared to that of gerber
    dx, dy = to_gerbv_svg_units(offset[0]), -to_gerbv_svg_units(offset[1])
    mean, _max, hist = gerber_difference(ref, tmp_gbr, diff_out=tmp_png, svg_transform=f'translate({dx} {dy})')
    assert mean < 1e-4
    assert hist[9] == 0

@pytest.mark.filterwarnings('ignore:Deprecated.*statement found.*:DeprecationWarning')
@pytest.mark.filterwarnings('ignore::SyntaxWarning')
@pytest.mark.parametrize('reference', MIN_REFERENCE_FILES)
@pytest.mark.parametrize('angle', TEST_ANGLES)
@pytest.mark.parametrize('center', [(0, 0), (10, 0), (0, -10), (10, 20)])
@pytest.mark.parametrize('offset', [(0, 0), (100, 0), (0, 100), (100, 100), (100, 10)])
def test_combined(temp_files, reference, angle, center, offset):
    if 'flash_rectangle' in reference and angle in (30, 1024):
        # gerbv's rendering of this is broken, the hole is missing.
        return
    tmp_gbr, tmp_png = temp_files
    ref = reference_path(reference)

    f = GerberFile.open(ref)
    f.rotate(deg_to_rad(angle), center=center)
    f.offset(*offset)
    f.save(tmp_gbr, settings=FileSettings(unit=f.unit, number_format=(4,7)))

    size = (10, 10) # inches
    cx, cy = to_gerbv_svg_units(center[0]), to_gerbv_svg_units(10, 'inch')-to_gerbv_svg_units(center[1], 'mm')
    dx, dy = to_gerbv_svg_units(offset[0]), -to_gerbv_svg_units(offset[1])
    mean, _max, hist = gerber_difference(ref, tmp_gbr, diff_out=tmp_png,
            svg_transform=f'translate({dx} {dy}) rotate({angle} {cx} {cy})',
            size=size)
    assert mean < 1e-3
    assert hist[9] < 100
    assert hist[3:].sum() < 1e-3*hist.size

