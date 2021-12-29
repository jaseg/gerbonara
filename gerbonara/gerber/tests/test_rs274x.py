#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Hamilton Kibbe <ham@hamiltonkib.be>
import os
import pytest
import functools
import tempfile
import shutil
from argparse import Namespace
from pathlib import Path

from ..rs274x import GerberFile

from .image_support import gerber_difference


fail_dir = Path('gerbonara_test_failures')
@pytest.fixture(scope='session', autouse=True)
def clear_failure_dir(request):
    if fail_dir.is_dir():
        shutil.rmtree(fail_dir)

@pytest.fixture
def tmp_gbr(request):
    with tempfile.NamedTemporaryFile(suffix='.gbr') as tmp_out_gbr:

        yield Path(tmp_out_gbr.name)

        if request.node.rep_call.failed:
            module, _, test_name = request.node.nodeid.rpartition('::')
            _test, _, test_name = test_name.partition('_')
            test_name = test_name.replace('[', '_').replace(']', '_')
            fail_dir.mkdir(exist_ok=True)
            perm_path = fail_dir / f'failure_{test_name}.gbr'
            shutil.copy(tmp_out_gbr.name, perm_path)
            print('Failing output saved to {perm_path}')

@pytest.mark.parametrize('reference', [ l.strip() for l in '''
board_outline.GKO
example_outline_with_arcs.gbr
'''
#example_two_square_boxes.gbr
#example_coincident_hole.gbr
#example_cutin.gbr
#example_cutin_multiple.gbr
#example_flash_circle.gbr
#example_flash_obround.gbr
#example_flash_polygon.gbr
#example_flash_rectangle.gbr
#example_fully_coincident.gbr
#example_guess_by_content.g0
#example_holes_dont_clear.gbr
#example_level_holes.gbr
#example_not_overlapping_contour.gbr
#example_not_overlapping_touching.gbr
#example_overlapping_contour.gbr
#example_overlapping_touching.gbr
#example_simple_contour.gbr
#example_single_contour_1.gbr
#example_single_contour_2.gbr
#example_single_contour_3.gbr
#example_am_exposure_modifier.gbr
#bottom_copper.GBL
#bottom_mask.GBS
#bottom_silk.GBO
#eagle_files/copper_bottom_l4.gbr
#eagle_files/copper_inner_l2.gbr
#eagle_files/copper_inner_l3.gbr
#eagle_files/copper_top_l1.gbr
#eagle_files/profile.gbr
#eagle_files/silkscreen_bottom.gbr
#eagle_files/silkscreen_top.gbr
#eagle_files/soldermask_bottom.gbr
#eagle_files/soldermask_top.gbr
#eagle_files/solderpaste_bottom.gbr
#eagle_files/solderpaste_top.gbr
#multiline_read.ger
#test_fine_lines_x.gbr
#test_fine_lines_y.gbr
#top_copper.GTL
#top_mask.GTS
#top_silk.GTO
'''
'''.splitlines() if l ])
def test_round_trip(tmp_gbr, reference):
    ref = Path(__file__).parent / 'resources' / reference
    GerberFile.open(ref).save(tmp_gbr)
    assert gerber_difference(ref, tmp_gbr) < 0.02

