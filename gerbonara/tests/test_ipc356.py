#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2015 Hamilton Kibbe <ham@hamiltonkib.be>
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

import pytest

from ..ipc356 import *
from ..cam import FileSettings

from .utils import *
from ..utils import Inch, MM


REFERENCE_FILES = [
        # TODO add more test files from github
        'allegro-2/MinnowMax_RevA1_IPC356A.ipc',
        'allegro/08_057494d-ipc356.ipc',
        'ipc-d-356.ipc',
        ]


@filter_syntax_warnings
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
def test_read(reference):
    netlist = Netlist.open(reference)
    assert netlist
    assert netlist.test_records

@filter_syntax_warnings
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
def test_idempotence(reference, tmpfile):
    tmp_1 = tmpfile('First generation output', '.ipc')
    tmp_2 = tmpfile('Second generation output', '.ipc')

    a = Netlist.open(reference)
    a.save(tmp_1)
    b = Netlist.open(tmp_1)
    b.save(tmp_2)

    print(f'{a.outlines=}')
    print(f'{b.outlines=}')

    res = tmp_1.read_text() == tmp_2.read_text()
    # Confuse pytest so it doesn't try to print out a diff. pytest's potato diff algorithm is wayyyy to slow and would
    # hang for several minutes.
    assert res

@filter_syntax_warnings
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
def test_bells_and_whistles(reference):
    netlist = Netlist.open(reference)
    netlist.net_names()
    netlist.vias()
    netlist.reference_designators()
    netlist.records_by_reference('C1')
    netlist.records_by_net_name('n001')
    netlist.conductors_by_net_name('n001')
    netlist.conductors_by_layer(0)

@filter_syntax_warnings
@pytest.mark.parametrize('a', REFERENCE_FILES)
@pytest.mark.parametrize('b', REFERENCE_FILES)
def test_merge(a, b):
    a, b = reference_path(a), reference_path(b)
    print('File A:', a)
    print('File B:', a)

    a = Netlist.open(a)
    b = Netlist.open(b)
    a.merge(b, our_prefix='A')
    # FIXME asserts

def test_record_semantics():
    settings = FileSettings()
    r = TestRecord.parse('327m0002            CPU1  -AY30       A01X+020114Y+014930X0120Y    R090 S1      ', settings)
    assert r.pad_type == PadType.SMD_PAD
    assert r.net_name == 'm0002'
    assert r.is_connected
    assert r.ref_des == 'CPU1'
    assert not r.is_via
    assert r.pin == 'AY30'
    assert not r.is_middle
    assert r.hole_dia is None
    assert r.is_plated is None
    assert r.access_layer == 1
    assert math.isclose(r.x, 20114/1000) and math.isclose(r.y, 14930/1000)
    assert math.isclose(r.w, 120/1000) and r.h is None
    assert math.isclose(r.rotation, math.pi/2)
    assert r.solder_mask == SoldermaskInfo.PRIMARY
    assert r.unit == settings.unit

    r = TestRecord.parse('327m0002            U15   -D3         A01X+011545Y+003447X0090Y    R090 S1      ', settings)
    assert r.pad_type == PadType.SMD_PAD
    assert r.net_name == 'm0002'
    assert r.is_connected
    assert r.ref_des == 'U15'
    assert r.pin == 'D3'
    assert not r.is_middle
    assert r.hole_dia is None
    assert r.is_plated is None
    assert r.access_layer == 1
    assert math.isclose(r.w, 90/1000) and r.h is None

    r = TestRecord.parse('327VSUMPG           C39   -2   M      A01X+013050Y+020050X0350Y0320R270 S1      ', settings)
    assert r.pad_type == PadType.SMD_PAD
    assert r.net_name == 'VSUMPG'
    assert r.is_connected
    assert r.ref_des == 'C39'
    assert r.pin == '2'
    assert r.is_middle
    assert r.hole_dia is None
    assert r.is_plated is None
    assert r.access_layer == 1
    assert math.isclose(r.w, 350/1000) and math.isclose(r.h, 320/1000)
    assert math.isclose(r.rotation, math.pi*3/2)

    r = TestRecord.parse('327N/C              CPU1  -AD2        A01X+023191Y+020393X0110Y    R090 S1      ', settings)
    assert r.pad_type == PadType.SMD_PAD
    assert r.net_name == None
    assert not r.is_connected
    assert r.ref_des == 'CPU1'
    assert r.pin == 'AD2'
    assert r.hole_dia is None
    assert r.is_plated is None
    assert r.access_layer == 1
    assert math.isclose(r.w, 110/1000) and r.h is None

    r = TestRecord.parse('317m0002            VIA   -    MD0080PA00X+011900Y+004000X0160Y         S3      ', settings)
    assert r.pad_type == PadType.THROUGH_HOLE
    assert r.net_name == 'm0002'
    assert r.is_connected
    assert r.ref_des is None
    assert r.is_via
    assert r.pin is None
    assert r.is_middle
    assert r.hole_dia == 80/1000
    assert r.is_plated
    assert r.access_layer == 0
    assert math.isclose(r.w, 160/1000) and r.h is None
    assert r.rotation == 0
    assert r.solder_mask == SoldermaskInfo.BOTH

    r = TestRecord.parse('317GND              VIA   -    MD0080PA00X+023800Y+010100X0160Y         S0      ', settings)
    assert r.pad_type == PadType.THROUGH_HOLE
    assert r.net_name == 'GND'
    assert r.is_connected
    assert r.is_via
    assert r.pin is None
    assert r.hole_dia == 80/1000
    assert r.is_plated
    assert r.access_layer == 0
    assert r.solder_mask == SoldermaskInfo.NONE

def test_record_idempotence():
    records = [
            '327m0002            CPU1  -AY30       A01X+020114Y+014930X0120Y    R090 S1      ',
            '327m0002            U15   -D3         A01X+011545Y+003447X0090Y    R090 S1      ',
            '327VSUMPG           C39   -2   M      A01X+013050Y+020050X0350Y0320R270 S1      ',
            '317m0002            VIA   -    MD0080PA00X+011900Y+004000X0160Y         S3      ',
            '317GND              VIA   -    MD0080PA00X+023800Y+010100X0160Y         S0      ',]

    for unit in MM, Inch:
        settings = FileSettings(unit=unit)
        for record in records:
            ra = TestRecord.parse(record, settings)
            a = list(ra.format(settings))[0]
            rb = TestRecord.parse(a, settings)
            b = list(rb.format(settings))[0]
            print('ra', ra)
            print('rb', rb)
            print('0', record)
            print('a', a)
            print('b', b)
            assert a == b

