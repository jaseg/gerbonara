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
        'easyeda/Gerber_Drill_NPTH.DRL': (('inch', 'leading', 4), None),
        'easyeda/Gerber_Drill_PTH.DRL': (('inch', 'leading', 4), 'easyeda/Gerber_TopLayer.GTL'),
        # Altium uses an excellon format specification format that gerbv doesn't understand, so we have to fix that.
        'altium-composite-drill/NC Drill/LimeSDR-QPCIe_1v2-SlotHoles.TXT': (('mm', 'trailing', 4), None),
        'altium-composite-drill/NC Drill/LimeSDR-QPCIe_1v2-RoundHoles.TXT': (('mm', 'trailing', 4), 'altium-composite-drill/Gerber/LimeSDR-QPCIe_1v2.GTL'),
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
        'zuken-emulated/Drill/8seg_Driver__routed_Drill_thru_plt.fdr/8seg_Driver__routed_Drill_thru_plt.fdr': (('inch', 'trailing', 4), 'zuken-emulated/Gerber/Conductive-1.fph'),
        'zuken-emulated/Drill/8seg_Driver__routed_Drill_thru_nplt.fdr': (('inch', 'trailing', 4), None),
        'p-cad/ZXINET.DRL': (None, None),
        'kicad-x2-tests/nox2ap/Flashpads-NPTH.drl': (None, None),
        'kicad-x2-tests/nox2ap/Flashpads-PTH.drl': (None, None),
        'kicad-x2-tests/nox2noap/Flashpads-NPTH.drl': (None, None),
        'kicad-x2-tests/nox2noap/Flashpads-PTH.drl': (None, None),
        'kicad-x2-tests/x2ap/Flashpads-NPTH.drl': (None, None),
        'kicad-x2-tests/x2ap/Flashpads-PTH.drl': (None, None),
        'kicad-x2-tests/x2noap/Flashpads-NPTH.drl': (None, None),
        'kicad-x2-tests/x2noap/Flashpads-PTH.drl': (None, None),
        }

@filter_syntax_warnings
@pytest.mark.parametrize('reference', list(REFERENCE_FILES.items()), indirect=True)
def test_round_trip(reference, tmpfile):
    reference, (unit_spec, _) = reference
    tmp = tmpfile('Output excellon', '.drl')

    f = ExcellonFile.open(reference)
    f.save(tmp)

    if reference.name == '80101_0125_F200_ContourPlated.ncd':
        # gerbv does not support routed slots in excellon files at all and renders garbage for the reference file here
        # due to its use of bare coordinates for routed slots. Thus, we skip this test (for now).
        return

    mean, _max, hist = gerber_difference(reference, tmp, diff_out=tmpfile('Difference', '.png'), ref_unit_spec=unit_spec)
    assert mean < 5e-5
    assert hist[9] == 0
    assert hist[3:].sum() < 5e-5*hist.size

@filter_syntax_warnings
@pytest.mark.parametrize('reference', list(REFERENCE_FILES.items()), indirect=True)
def test_first_level_idempotence_svg(reference, tmpfile):
    reference, (unit_spec, _) = reference
    tmp = tmpfile('Output excellon', '.drl')
    ref_svg = tmpfile('Reference SVG render', '.svg')
    out_svg = tmpfile('Output SVG render', '.svg')

    a = ExcellonFile.open(reference)
    a.save(tmp)
    b = ExcellonFile.open(tmp)

    ref_svg.write_text(str(a.to_svg(fg='black', bg='white')))
    out_svg.write_text(str(b.to_svg(fg='black', bg='white')))

    mean, _max, hist = svg_difference(ref_svg, out_svg, diff_out=tmpfile('Difference', '.png'), background='white')
    assert mean < 5e-5
    assert hist[9] == 0
    assert hist[3:].sum() < 5e-5*hist.size

@filter_syntax_warnings
@pytest.mark.parametrize('reference', list(REFERENCE_FILES.items()), indirect=True)
def test_idempotence(reference, tmpfile):
    reference, (unit_spec, _) = reference

    if reference.name == '80101_0125_F200_ContourPlated.ncd':
        # this file contains a duplicate tool definition that we optimize out on our second pass.
        # TODO see whether we can change things so we optimize this out on the first pass already. I'm not sure what
        # went wrong there.
        pytest.skip()

    tmp_1 = tmpfile('First generation output', '.drl')
    tmp_2 = tmpfile('Second generation output', '.drl')

    f1 = ExcellonFile.open(reference)
    f1.save(tmp_1)
    print(f'{f1.import_settings=}')
    f2 = ExcellonFile.open(tmp_1)
    f2.save(tmp_2)
    print(f'{f2.import_settings=}')

    assert tmp_1.read_text() == tmp_2.read_text()

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
    excf.save(tmp)

    flash_coords = []
    for obj in gerf.objects:
        if isinstance(obj, Flash):
            x, y = obj.unit.convert_to(MM, obj.x), obj.unit.convert_to(MM, obj.y)
            flash_coords.append((x, y))

    tree = KDTree(flash_coords, copy_data=True)

    tolerance = 0.05 # mm
    matches, total = 0, 0
    for obj in excf.objects:
        if isinstance(obj, Flash):
            if obj.plated in (True, None):
                total += 1
                x, y = obj.unit.convert_to(MM, obj.x), obj.unit.convert_to(MM, obj.y)
                if tree.query_ball_point((x, y), r=tolerance):
                    matches += 1

    # Some PCB tools, notably easyeda, are dumb and export certain pads as regions, not apertures. Thus, we have to
    # tolerate some non-matches.
    assert matches > 10
    assert matches/total > 0.5

@filter_syntax_warnings
def test_syntax_error():
    ref = reference_path('test_syntax_error.exc')
    with pytest.raises(SyntaxError) as exc_info:
        ExcellonFile.open(ref)

    assert 'test_syntax_error.exc' in exc_info.value.msg
    assert '12' in exc_info.value.msg # lineno

