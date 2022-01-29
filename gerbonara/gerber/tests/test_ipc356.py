#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Hamilton Kibbe <ham@hamiltonkib.be>
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

    Netlist.open(reference).save(tmp_1)
    Netlist.open(tmp_1).save(tmp_2)

    assert tmp_1.read_text() == tmp_2.read_text()

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
@pytest.mark.parametrize('reference', REFERENCE_FILES, indirect=True)
@pytest.mark.parametrize('other', REFERENCE_FILES, indirect=True)
def test_merge(reference, other):
    other = reference_path(other)
    a = Netlist.open(reference)
    b = Netlist.open(other)
    a.merge(b, our_prefix='A')
    # FIXME asserts

