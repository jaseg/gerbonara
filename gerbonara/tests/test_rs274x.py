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
# Based on https://github.com/tracespace/tracespace
#

import math

from PIL import Image
import pytest

from ..rs274x import GerberFile
from ..cam import FileSettings

from .image_support import *
from .utils import *

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
    open_outline_altium.gbr
    easyeda/Gerber_TopSolderMaskLayer.GTS
    easyeda/Gerber_TopSilkLayer.GTO
    easyeda/Gerber_BottomSolderMaskLayer.GBS
    easyeda/Gerber_BoardOutline.GKO
    easyeda/Gerber_TopLayer.GTL
    easyeda/Gerber_BottomLayer.GBL
    easyeda/Gerber_TopPasteMaskLayer.GTP
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr2.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr3.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_fab.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr10_GAF.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr7.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_sps.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr6.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr1_GAF.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_assy.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_smc_GAF.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr4.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr5.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_bslk.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_spc.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_tslk_GAF.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr8.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_sms_GAF.art
    allegro-2/MinnowMax_RevA1_GAF_Gerber/MinnowMax_lyr9.art
    eagle-newer/solderpaste_bottom.gbr
    eagle-newer/silkscreen_bottom.gbr
    eagle-newer/profile.gbr
    eagle-newer/copper_bottom.gbr
    eagle-newer/soldermask_top.gbr
    eagle-newer/solderpaste_top.gbr
    eagle-newer/soldermask_bottom.gbr
    eagle-newer/silkscreen_top.gbr
    eagle-newer/copper_top.gbr
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G4
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G9
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GBL
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GTO
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G11
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G1
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GBP
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G2
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GM15
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GTS
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G6
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G7
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G3
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GPB
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GM1
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G12
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GBS
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GTL
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G10
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GM14
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G5
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GTP
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GBO
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.G8
    altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GPT
    geda/driver.topmask.gbr
    geda/controller.top.gbr
    geda/controller.bottom.gbr
    geda/driver.bottommask.gbr
    geda/driver.top.gbr
    geda/driver.bottom.gbr
    geda/controller.topsilk.gbr
    geda/controller.fab.gbr
    geda/driver.topsilk.gbr
    geda/controller.group3.gbr
    geda/controller.topmask.gbr
    geda/driver.group5.gbr
    geda/controller.bottommask.gbr
    geda/driver.fab.gbr
    pcb-rnd/power-art.gko
    pcb-rnd/power-art.ast
    pcb-rnd/power-art.gtl
    pcb-rnd/power-art.gto
    pcb-rnd/power-art.gtp
    pcb-rnd/power-art.asb
    pcb-rnd/power-art.gbp
    pcb-rnd/power-art.gbs
    pcb-rnd/power-art.gbl
    pcb-rnd/power-art.fab
    pcb-rnd/power-art.gbo
    pcb-rnd/power-art.gts
    siemens/80101_0125_F200_L04.gdo
    siemens/80101_0125_F200_L12_Bottom.gdo
    siemens/80101_0125_F200_L11.gdo
    siemens/80101_0125_F200_L10.gdo
    siemens/80101_0125_F200_SolderPasteTop.gdo
    siemens/80101_0125_F200_SoldermaskTop.gdo
    siemens/80101_0125_F200_L06.gdo
    siemens/80101_0125_F200_L02.gdo
    siemens/80101_0125_F200_SilkscreenBottom.gdo
    siemens/80101_0125_F200_SoldermaskBottom.gdo
    siemens/80101_0125_F200_SolderPasteBottom.gdo
    siemens/80101_0125_F200_L03.gdo
    siemens/80101_0125_F200_L01_Top.gdo
    Target3001/IRNASIoTbank1.2.Bot
    Target3001/IRNASIoTbank1.2.Outline
    Target3001/IRNASIoTbank1.2.PasteBot
    Target3001/IRNASIoTbank1.2.PasteTop
    Target3001/IRNASIoTbank1.2.PosiBot
    Target3001/IRNASIoTbank1.2.PosiTop
    Target3001/IRNASIoTbank1.2.StopBot
    Target3001/IRNASIoTbank1.2.StopTop
    Target3001/IRNASIoTbank1.2.Top
    kicad-older/chibi_2024-Edge.Cuts.gbr
    kicad-older/chibi_2024-F.SilkS.gbr
    kicad-older/chibi_2024-B.Paste.gbr
    kicad-older/chibi_2024-B.Cu.gbr
    kicad-older/chibi_2024-F.Mask.gbr
    kicad-older/chibi_2024-B.Mask.gbr
    kicad-older/chibi_2024-F.Paste.gbr
    kicad-older/chibi_2024-B.SilkS.gbr
    kicad-older/chibi_2024-F.Cu.gbr
    fritzing/combined.gbs
    fritzing/combined.gm1
    fritzing/combined.gbl
    fritzing/combined.gbo
    fritzing/combined.GKO
    fritzing/combined.gtl
    fritzing/combined.gts
    fritzing/combined.gto
    siemens-2/Gerber/SoldermaskTop.gdo
    siemens-2/Gerber/EtchLayerTop.gdo
    siemens-2/Gerber/DrillDrawingThrough.gdo
    siemens-2/Gerber/SoldermaskBottom.gdo
    siemens-2/Gerber/SolderPasteBottom.gdo
    siemens-2/Gerber/SolderPasteTop.gdo
    siemens-2/Gerber/EtchLayerBottom.gdo
    siemens-2/Gerber/BoardOutlline.gdo
    upverter/design_export.gko
    upverter/design_export.gtl
    upverter/design_export.gbp
    upverter/design_export.gtp
    upverter/design_export.gbl
    upverter/design_export.gto
    upverter/design_export.gbs
    upverter/design_export.gts
    upverter/design_export.gbo
    eagle_files/solderpaste_bottom.gbr
    eagle_files/silkscreen_bottom.gbr
    eagle_files/profile.gbr
    eagle_files/copper_inner_l2.gbr
    eagle_files/copper_top_l1.gbr
    eagle_files/soldermask_top.gbr
    eagle_files/copper_inner_l3.gbr
    eagle_files/solderpaste_top.gbr
    eagle_files/soldermask_bottom.gbr
    eagle_files/copper_bottom_l4.gbr
    eagle_files/silkscreen_top.gbr
    diptrace/panel_BoardOutline.gbr
    diptrace/keyboard_BottomSilk.gbr
    diptrace/keyboard_Bottom.gbr
    diptrace/mainboard_Top.gbr
    diptrace/mainboard_TopMask.gbr
    diptrace/mainboard_BoardOutline.gbr
    diptrace/mainboard_Bottom.gbr
    diptrace/mainboard_BottomMask.gbr
    diptrace/keyboard_BottomMask.gbr
    diptrace/panel_Bottom.gbr
    diptrace/keyboard_BoardOutline.gbr
    diptrace/panel_BottomSilk.gbr
    diptrace/panel_BottomMask.gbr
    diptrace/mainboard_TopSilk.gbr
    zuken-emulated/Gerber/MetalMask-A.fph
    zuken-emulated/Gerber/MetalMask-B.fph
    zuken-emulated/Gerber/Symbol-A.fph
    zuken-emulated/Gerber/Symbol-B.fph
    zuken-emulated/Gerber/Resist-A.fph
    zuken-emulated/Gerber/Resist-B.fph
    zuken-emulated/Gerber/Conductive-1.fph
    zuken-emulated/Gerber/Conductive-2.fph
    p-cad/ZXINET.GBL
    p-cad/ZXINET.GBO
    p-cad/ZXINET.GBS
    p-cad/ZXINET.GKO
    p-cad/ZXINET.GTL
    p-cad/ZXINET.GTO
    p-cad/ZXINET.GTS
    fab-3000/bl
    fab-3000/bo
    fab-3000/bs
    fab-3000/ko
    fab-3000/tl
    fab-3000/to
    fab-3000/ts
    fab-3000/drl
    kicad-x2-tests/nox2ap/Flashpads-B_Cu.gbr
    kicad-x2-tests/nox2ap/Flashpads-B_Mask.gbr
    kicad-x2-tests/nox2ap/Flashpads-B_Paste.gbr
    kicad-x2-tests/nox2ap/Flashpads-B_Silkscreen.gbr
    kicad-x2-tests/nox2ap/Flashpads-Edge_Cuts.gbr
    kicad-x2-tests/nox2ap/Flashpads-F_Cu.gbr
    kicad-x2-tests/nox2ap/Flashpads-F_Mask.gbr
    kicad-x2-tests/nox2ap/Flashpads-F_Paste.gbr
    kicad-x2-tests/nox2ap/Flashpads-F_Silkscreen.gbr
    kicad-x2-tests/nox2noap/Flashpads-B_Cu.gbr
    kicad-x2-tests/nox2noap/Flashpads-B_Mask.gbr
    kicad-x2-tests/nox2noap/Flashpads-B_Paste.gbr
    kicad-x2-tests/nox2noap/Flashpads-B_Silkscreen.gbr
    kicad-x2-tests/nox2noap/Flashpads-Edge_Cuts.gbr
    kicad-x2-tests/nox2noap/Flashpads-F_Cu.gbr
    kicad-x2-tests/nox2noap/Flashpads-F_Mask.gbr
    kicad-x2-tests/nox2noap/Flashpads-F_Paste.gbr
    kicad-x2-tests/nox2noap/Flashpads-F_Silkscreen.gbr
    kicad-x2-tests/x2ap/Flashpads-B_Cu.gbr
    kicad-x2-tests/x2ap/Flashpads-B_Mask.gbr
    kicad-x2-tests/x2ap/Flashpads-B_Paste.gbr
    kicad-x2-tests/x2ap/Flashpads-B_Silkscreen.gbr
    kicad-x2-tests/x2ap/Flashpads-Edge_Cuts.gbr
    kicad-x2-tests/x2ap/Flashpads-F_Cu.gbr
    kicad-x2-tests/x2ap/Flashpads-F_Mask.gbr
    kicad-x2-tests/x2ap/Flashpads-F_Paste.gbr
    kicad-x2-tests/x2ap/Flashpads-F_Silkscreen.gbr
    kicad-x2-tests/x2noap/Flashpads-B_Cu.gbr
    kicad-x2-tests/x2noap/Flashpads-B_Mask.gbr
    kicad-x2-tests/x2noap/Flashpads-B_Paste.gbr
    kicad-x2-tests/x2noap/Flashpads-B_Silkscreen.gbr
    kicad-x2-tests/x2noap/Flashpads-Edge_Cuts.gbr
    kicad-x2-tests/x2noap/Flashpads-F_Cu.gbr
    kicad-x2-tests/x2noap/Flashpads-F_Mask.gbr
    kicad-x2-tests/x2noap/Flashpads-F_Paste.gbr
    kicad-x2-tests/x2noap/Flashpads-F_Silkscreen.gbr
    gerbv.gbr
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

HAS_ZERO_SIZE_APERTURES = [
    'bottom_copper.GBL',
    'bottom_silk.GBO',
    'top_copper.GTL',
    'top_silk.GTO',
    'board_outline.GKO',
    'silkscreen_top.gbr',
    'combined.GKO',
    'combined.gto',
    'EtchLayerTop.gdo',
    'EtchLayerBottom.gdo',
    'BoardOutlline.gdo',
    ]


@filter_syntax_warnings
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
def test_round_trip(reference, tmpfile):
    tmp_gbr = tmpfile('Output gerber', '.gbr')

    GerberFile.open(reference).save(tmp_gbr)

    mean, _max, hist = gerber_difference(reference, tmp_gbr, diff_out=tmpfile('Difference', '.png'))
    assert mean < 5e-5
    assert hist[9] == 0
    assert hist[3:].sum() < 5e-5*hist.size

@filter_syntax_warnings
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
def test_idempotence(reference, tmpfile):
    tmp_gbr_1 = tmpfile('First generation output', '.gbr')
    tmp_gbr_2 = tmpfile('Second generation output', '.gbr')

    GerberFile.open(reference).save(tmp_gbr_1)
    GerberFile.open(tmp_gbr_1).save(tmp_gbr_2)
    for left, right in zip(tmp_gbr_1.read_text().splitlines(), tmp_gbr_2.read_text().splitlines()):
        # Substituted aperture macros have automatically generated names that are not stable between the first two
        # generations, and the parametrization will be absent in the second generation.
        ignored = [
                '0 Fully substituted instance of',
                '0 Original parameters:']
        if any(left.startswith(s) and right.startswith(s) for s in ignored):
            continue

        assert left == right


TEST_ANGLES = [90, 180, 270, 1.5, 30, 360, 1024, -30]
TEST_OFFSETS = [(0, 0), (100, 0), (0, 100), (2, 0), (10, 100)]

@filter_syntax_warnings
@pytest.mark.parametrize('reference', MIN_REFERENCE_FILES, indirect=True)
@pytest.mark.parametrize('angle', TEST_ANGLES)
def test_rotation(reference, angle, tmpfile):
    if 'flash_rectangle' in str(reference) and angle == 1024:
        # gerbv's rendering of this is broken, the hole is missing.
        pytest.skip()

    tmp_gbr = tmpfile('Output gerber', '.gbr')

    f = GerberFile.open(reference)
    f.rotate(math.radians(angle))
    f.save(tmp_gbr)

    cx, cy = 0, to_gerbv_svg_units(10, unit='inch')
    mean, _max, hist = gerber_difference(reference, tmp_gbr, diff_out=tmpfile('Difference', '.png'),
            svg_transform=f'rotate({angle} {cx} {cy})')
    assert mean < 1e-3 # relax mean criterion compared to above.
    assert hist[9] == 0

@filter_syntax_warnings
@pytest.mark.parametrize('reference', MIN_REFERENCE_FILES, indirect=True)
@pytest.mark.parametrize('angle', TEST_ANGLES)
@pytest.mark.parametrize('center', [(0, 0), (10, 0), (0, -10), (10, 20)])
def test_rotation_center(reference, angle, center, tmpfile):
    if 'flash_rectangle' in str(reference) and angle in (30, 1024):
        # gerbv's rendering of this is broken, the hole is missing.
        pytest.skip()

    tmp_gbr = tmpfile('Output gerber', '.gbr')

    f = GerberFile.open(reference)
    f.rotate(math.radians(angle), *center)
    f.save(tmp_gbr)

    # calculate circle center in SVG coordinates 
    size = (10, 10) # inches
    cx, cy = to_gerbv_svg_units(center[0]), to_gerbv_svg_units(size[1], 'inch')-to_gerbv_svg_units(center[1], 'mm')
    mean, _max, hist = gerber_difference(reference, tmp_gbr, diff_out=tmpfile('Difference', '.png'),
            svg_transform=f'rotate({angle} {cx} {cy})',
            size=size)
    assert mean < 1e-3
    assert hist[9] < 50
    assert hist[3:].sum() < 1e-3*hist.size

@filter_syntax_warnings
@pytest.mark.parametrize('reference', MIN_REFERENCE_FILES, indirect=True)
@pytest.mark.parametrize('offset', TEST_OFFSETS)
def test_offset(reference, offset, tmpfile):
    tmp_gbr = tmpfile('Output gerber', '.gbr')

    f = GerberFile.open(reference)
    f.offset(*offset)
    f.save(tmp_gbr, settings=FileSettings(unit=f.unit, number_format=(4,7)))

    # flip y offset since svg's y axis is flipped compared to that of gerber
    dx, dy = to_gerbv_svg_units(offset[0]), -to_gerbv_svg_units(offset[1])
    mean, _max, hist = gerber_difference(reference, tmp_gbr, diff_out=tmpfile('Difference', '.png'),
            svg_transform=f'translate({dx} {dy})')
    assert mean < 1e-4
    assert hist[9] == 0

@filter_syntax_warnings
@pytest.mark.parametrize('reference', MIN_REFERENCE_FILES, indirect=True)
@pytest.mark.parametrize('angle', TEST_ANGLES)
@pytest.mark.parametrize('center', [(0, 0), (10, 0), (0, -10), (10, 20)])
@pytest.mark.parametrize('offset', [(0, 0), (100, 0), (0, 100), (100, 10)])
def test_combined(reference, angle, center, offset, tmpfile):
    if 'flash_rectangle' in str(reference) and angle in (30, 1024):
        # gerbv's rendering of this is broken, the hole is missing.
        pytest.skip()

    tmp_gbr = tmpfile('Output gerber', '.gbr')

    f = GerberFile.open(reference)
    f.rotate(math.radians(angle), *center)
    f.offset(*offset)
    f.save(tmp_gbr, settings=FileSettings(unit=f.unit, number_format=(4,7)))

    size = (10, 10) # inches
    cx, cy = to_gerbv_svg_units(center[0]), to_gerbv_svg_units(size[1], 'inch')-to_gerbv_svg_units(center[1], 'mm')
    dx, dy = to_gerbv_svg_units(offset[0]), -to_gerbv_svg_units(offset[1])
    mean, _max, hist = gerber_difference(reference, tmp_gbr, diff_out=tmpfile('Difference', '.png'),
            svg_transform=f'translate({dx} {dy}) rotate({angle} {cx} {cy})',
            size=size)
    assert mean < 1e-3
    assert hist[9] < 100
    assert hist[3:].sum() < 1e-3*hist.size

@filter_syntax_warnings
@pytest.mark.parametrize('file_a', MIN_REFERENCE_FILES)
@pytest.mark.parametrize('file_b', [
    'example_two_square_boxes.gbr',
    'example_outline_with_arcs.gbr',
    'example_am_exposure_modifier.gbr',
    'bottom_silk.GBO',
    'eagle_files/copper_bottom_l4.gbr', ])
@pytest.mark.parametrize('angle', [0, 10, 90])
@pytest.mark.parametrize('offset', [(0, 0, 0, 0), (100, 0, 0, 0), (0, 0, 0, 100), (100, 0, 0, 100)])
def test_compositing(file_a, file_b, angle, offset, tmpfile, print_on_error):

    # TODO bottom_silk.GBO renders incorrectly with gerbv: the outline does not exist in svg. In GUI, the logo only
    # renders at very high magnification. Skip, and once we have our own SVG export maybe use that instead. Or just use
    # KiCAD's gerbview.
    # TODO check if this and the issue with aperture holes not rendering in test_combined actually are bugs in gerbv
    # and fix/report upstream.
    if file_a == 'bottom_silk.GBO' or file_b == 'bottom_silk.GBO':
        pytest.skip()

    ref_a = reference_path(file_a)
    print_on_error('Reference file a:', ref_a)
    ref_b = reference_path(file_b)
    print_on_error('Reference file b:', ref_b)

    ax, ay, bx, by = offset
    grb_a = GerberFile.open(ref_a)
    grb_a.rotate(math.radians(angle))
    grb_a.offset(ax, ay)

    grb_b = GerberFile.open(ref_b)
    grb_b.offset(bx, by)

    grb_a.merge(grb_b)
    tmp_gbr = tmpfile('Output gerber', '.gbr')
    grb_a.save(tmp_gbr, settings=FileSettings(unit=grb_a.unit, number_format=(4,7)))

    size = (10, 10) # inches
    ax, ay = to_gerbv_svg_units(ax), -to_gerbv_svg_units(ay)
    bx, by = to_gerbv_svg_units(bx), -to_gerbv_svg_units(by)
    # note that we have to specify cx, cy even if we rotate around the origin since gerber's origin lies at (x=0
    # y=+document size) in SVG's coordinate space because svg's y axis is flipped compared to gerber's.
    cx, cy = 0, to_gerbv_svg_units(size[1], 'inch')
    mean, _max, hist = gerber_difference_merge(ref_a, ref_b, tmp_gbr,
            composite_out=tmpfile('Composite', '.svg'), diff_out=tmpfile('Difference', '.png'),
            svg_transform1=f'translate({ax} {ay}) rotate({angle} {cx} {cy})',
            svg_transform2=f'translate({bx} {by})',
            size=size)
    assert mean < 1e-3
    assert hist[9] < 100
    assert hist[3:].sum() < 1e-3*hist.size

@filter_syntax_warnings
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
def test_svg_export_gerber(reference, tmpfile):
    if reference.name in ('silkscreen_bottom.gbr', 'silkscreen_top.gbr', 'top_silk.GTO'):
        # Some weird svg rendering artifact. Might be caused by mismatching svg units between gerbv and us. Result looks
        # fine though.
        pytest.skip()

    if reference.name == 'MinnowMax_assy.art':
        # This leads to worst-case performance in resvg, this testcase takes over 1h to finish. So skip.
        pytest.skip()

    grb = GerberFile.open(reference)

    bounds = (0.0, 0.0), (6.0, 6.0) # bottom left, top right

    out_svg = tmpfile('Output', '.svg')
    with open(out_svg, 'w') as f:
        f.write(str(grb.to_svg(force_bounds=bounds, arg_unit='inch', fg='black', bg='white')))

    # NOTE: Instead of having gerbv directly export a PNG, we ask gerbv to output SVG which we then rasterize using
    # resvg. We have to do this since gerbv's built-in cairo-based PNG export has severe aliasing issues. In contrast,
    # using resvg for both allows an apples-to-apples comparison of both results.
    ref_svg = tmpfile('Reference export', '.svg')
    ref_png = tmpfile('Reference render', '.png')
    gerbv_export(reference, ref_svg, origin=bounds[0], size=bounds[1], fg='#000000', bg='#ffffff')
    with svg_soup(ref_svg) as soup:
        cleanup_gerbv_svg(soup)
    svg_to_png(ref_svg, ref_png, dpi=300, bg='white')

    out_png = tmpfile('Output render', '.png')
    svg_to_png(out_svg, out_png, dpi=300, bg='white')

    if reference.name in HAS_ZERO_SIZE_APERTURES:
        # gerbv does not render these correctly.
        return

    mean, _max, hist = image_difference(ref_png, out_png, diff_out=tmpfile('Difference', '.png'))
    assert hist[9] < 1
    if 'Minnow' in reference.name or 'LimeSDR' in reference.name or '80101_0125_F200' in reference.name:
        # This is a dense design with lots of traces, leading to lots of aliasing artifacts.
        assert mean < 10e-3
        assert hist[4:].sum() < 1e-2*hist.size
    else:
        assert mean < 1.2e-3
        assert hist[3:].sum() < 1e-3*hist.size

@filter_syntax_warnings
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
def test_bounding_box(reference, tmpfile):
    if reference.name == 'MinnowMax_assy.art':
        # This leads to worst-case performance in resvg, this testcase takes over 1h to finish. So skip.
        pytest.skip()
    # skip this check on files that contain lines with a zero-size aperture at the board edge
    if any(reference.match(f'*/{f}') for f in HAS_ZERO_SIZE_APERTURES):
        pytest.skip()

    margin = 1.0 # inch
    dpi = 200
    margin_px = int(dpi*margin) # intentionally round down to avoid aliasing artifacts

    grb = GerberFile.open(reference)

    if reference.match(f'fab-3000/*'):
        # These files have the board outline plotted in clear polarity. Change them to dark to not confuse our matching
        # code below.
        for prim in grb.objects:
            prim.polarity_dark = True

    if grb.is_empty:
        pytest.skip()

    out_svg = tmpfile('Output', '.svg')
    with open(out_svg, 'w') as f:
        f.write(str(grb.to_svg(margin=margin, arg_unit='inch', fg='white', bg='black')))

    out_png = tmpfile('Render', '.png')
    svg_to_png(out_svg, out_png, dpi=dpi)

    img = np.array(Image.open(out_png))
    img = img[:, :, :3].mean(axis=2) # drop alpha and convert to grayscale
    img = np.round(img).astype(int) # convert to int
    assert (img > 0).any() # there must be some content, none of the test gerbers are completely empty.
    cols = img.sum(axis=1)
    rows = img.sum(axis=0)
    col_prefix, col_suffix = np.argmax(cols > 0), np.argmax(cols[::-1] > 0)
    row_prefix, row_suffix = np.argmax(rows > 0), np.argmax(rows[::-1] > 0)
    print('cols:', col_prefix, col_suffix)
    print('rows:', row_prefix, row_suffix)

    # Check that all margins are completely black and that the content touches the margins. Allow for some tolerance to
    # allow for antialiasing artifacts and for things like very thin features.
    assert margin_px-3 <= col_prefix <= margin_px+3
    assert margin_px-3 <= col_suffix <= margin_px+3
    assert margin_px-3 <= row_prefix <= margin_px+3
    assert margin_px-3 <= row_suffix <= margin_px+3

@filter_syntax_warnings
def test_syntax_error():
    ref = reference_path('test_syntax_error.gbr')
    with pytest.raises(SyntaxError) as exc_info:
        GerberFile.open(ref)

    assert 'test_syntax_error.gbr' in exc_info.value.msg
    assert '7' in exc_info.value.msg # lineno

