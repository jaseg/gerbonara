#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Author: Jan Götte <code@jaseg.de>
import math

import pytest

from ..excellon import ExcellonFile
from ..cam import FileSettings

from .image_support import *
from .utils import *
from ..utils import Inch, MM

REFERENCE_FILES = [
        'easyeda/Gerber_Drill_NPTH.DRL',
        'easyeda/Gerber_Drill_PTH.DRL',
        'altium-composite-drill/NC Drill/LimeSDR-QPCIe_1v2-SlotHoles.TXT',
        'altium-composite-drill/NC Drill/LimeSDR-QPCIe_1v2-RoundHoles.TXT',
        'pcb-rnd/power-art.xln',
        'siemens/80101_0125_F200_ThruHoleNonPlated.ncd',
        'siemens/80101_0125_F200_ThruHolePlated.ncd',
        'siemens/80101_0125_F200_ContourPlated.ncd',
        'Target3001/IRNASIoTbank1.2.Drill',
        'altium-old-composite-drill.txt',
        'fritzing/combined.txt',
        'ncdrill.DRD',
        'upverter/design_export.drl',
        'diptrace/mainboard.drl',
        'diptrace/panel.drl',
        'diptrace/keyboard.drl',
        ]

@filter_syntax_warnings
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
def test_round_trip(reference, tmpfile):
    tmp = tmpfile('Output excellon', '.drl')
    # Altium uses an excellon format specification format that gerbv doesn't understand, so we have to fix that.
    unit_spec = ('mm', 'leading', 4) if 'altium-composite-drill' in str(reference) else None 
    # pcb-rnd does not include any unit specification at all
    if 'pcb-rnd' in str(reference):
        settings = FileSettings(unit=Inch, zeros='leading', number_format=(2,4))
    else:
        settings = None

    ExcellonFile.open(reference, settings=settings).save(tmp)

    mean, _max, hist = gerber_difference(reference, tmp, diff_out=tmpfile('Difference', '.png'), ref_unit_spec=unit_spec)
    assert mean < 5e-5
    assert hist[9] == 0
    assert hist[3:].sum() < 5e-5*hist.size


