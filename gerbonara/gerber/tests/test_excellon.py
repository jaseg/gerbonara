#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Author: Jan Götte <code@jaseg.de>
import math

import pytest

from ..excellon import ExcellonFile
from ..cam import FileSettings

from .image_support import *
from .utils import *

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

    ExcellonFile.open(reference).save(tmp)

    mean, _max, hist = gerber_difference(reference, tmp, diff_out=tmpfile('Difference', '.png'))
    assert mean < 5e-5
    assert hist[9] == 0
    assert hist[3:].sum() < 5e-5*hist.size


