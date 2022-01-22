#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Author: Jan Götte <code@jaseg.de>
import math

import pytest
from scipy.spatial import KDTree

from ..excellon import ExcellonFile
from ..rs274x import GerberFile
from ..cam import FileSettings
from ..graphic_objects import Flash

from .image_support import *
from .utils import *
from ..utils import Inch, MM

REFERENCE_FILES = {
        'easyeda/Gerber_Drill_NPTH.DRL': (None, None),
        'easyeda/Gerber_Drill_PTH.DRL': (None, 'easyeda/Gerber_TopLayer.GTL'),
    # Altium uses an excellon format specification format that gerbv doesn't understand, so we have to fix that.
        'altium-composite-drill/NC Drill/LimeSDR-QPCIe_1v2-SlotHoles.TXT': (('mm', 'leading', 4), None),
        'altium-composite-drill/NC Drill/LimeSDR-QPCIe_1v2-RoundHoles.TXT': (('mm', 'leading', 4), 'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GTL'),
        'pcb-rnd/power-art.xln': (None, 'pcb-rnd/power-art.gtl'),
        'siemens/80101_0125_F200_ThruHoleNonPlated.ncd': (None, None),
        'siemens/80101_0125_F200_ThruHolePlated.ncd': (None, 'siemens/80101_0125_F200_L01_Top.gdo'),
        'siemens/80101_0125_F200_ContourPlated.ncd': (None, None),
        'Target3001/IRNASIoTbank1.2.Drill': (None, 'Target3001/IRNASIoTbank1.2.Top'),
        'altium-old-composite-drill.txt': (None, None),
        'fritzing/combined.txt': (None, 'fritzing/combined.gtl'),
        'ncdrill.DRD': (None, None),
        'upverter/design_export.drl': (None, 'upverter/design_export.gtl'),
        'diptrace/mainboard.drl': (None, 'diptrace/mainboard_Top.gbr'),
        'diptrace/panel.drl': (None, None),
        'diptrace/keyboard.drl': (None, 'diptrace/keyboard_Bottom.gbr'),
        }

@filter_syntax_warnings
@pytest.mark.parametrize('reference', list(REFERENCE_FILES.items()), indirect=True)
def test_round_trip(reference, tmpfile):
    reference, (unit_spec, _) = reference
    tmp = tmpfile('Output excellon', '.drl')

    ExcellonFile.open(reference).save(tmp)

    mean, _max, hist = gerber_difference(reference, tmp, diff_out=tmpfile('Difference', '.png'), ref_unit_spec=unit_spec)
    assert mean < 5e-5
    assert hist[9] == 0
    assert hist[3:].sum() < 5e-5*hist.size

@filter_syntax_warnings
@pytest.mark.parametrize('reference', list(REFERENCE_FILES.items()), indirect=True)
def test_gerber_alignment(reference, tmpfile, print_on_error):
    reference, (unit_spec, gerber) = reference
    tmp = tmpfile('Output excellon', '.drl')

    if gerber is None:
        pytest.skip()

    excf = ExcellonFile.open(reference)
    gerf_path = reference_path(gerber)
    print_on_error('Reference gerber file:', gerf_path)
    gerf = GerberFile.open(gerf_path)
    print('bounds excellon:', excf.bounding_box(MM))
    print('bounds gerber:', gerf.bounding_box(MM))
    excf.save('/tmp/test.xnc')

    flash_coords = []
    for obj in gerf.objects:
        if isinstance(obj, Flash):
            x, y = obj.unit.convert_to(MM, obj.x), obj.unit.convert_to(MM, obj.y)
            if abs(x - 121.525) < 2 and abs(y - 64) < 2:
                print(obj)
            flash_coords.append((x, y))

    tree = KDTree(flash_coords, copy_data=True)

    tolerance = 0.05 # mm
    matches, total = 0, 0
    for obj in excf.objects:
        if isinstance(obj, Flash):
            if obj.plated in (True, None):
                total += 1
                x, y = obj.unit.convert_to(MM, obj.x), obj.unit.convert_to(MM, obj.y)
                print((x, y), end=' ')
                if abs(x - 121.525) < 2 and abs(y - 64) < 2:
                    print(obj)
                    print('   ', tree.query_ball_point((x, y), r=tolerance))
                if tree.query_ball_point((x, y), r=tolerance):
                    matches += 1

    # Some PCB tools, notably easyeda, are dumb and export certain pads as regions, not apertures. Thus, we have to
    # tolerate some non-matches.
    assert matches > 10
    assert matches/total > 0.5


