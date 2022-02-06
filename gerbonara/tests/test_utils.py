#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2015 Hamilton Kibbe <ham@hamiltonkib.be>
# Copyright 2022 Jan Götte <code@jaseg.de>
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
from ..cam import FileSettings


def test_zero_suppression():
    # Default format
    settings = FileSettings(number_format=(2,5), zeros='leading')
    test_cases = [
        ("1", 0.00001),
        ("10", 0.0001),
        ("100", 0.001),
        ("1000", 0.01),
        ("10000", 0.1),
        ("100000", 1.0),
        ("1000000", 10.0),
        ("0", 0.0),
    ]

    assert settings.write_gerber_value(0.000000001) == "0"

    for string, value in test_cases:
        assert value == settings.parse_gerber_value(string)
        assert string == settings.write_gerber_value(value)

    settings = FileSettings(number_format=(2,5), zeros='trailing')
    test_cases = [
        ("1", 10.0),
        ("01", 1.0),
        ("001", 0.1),
        ("0001", 0.01),
        ("00001", 0.001),
        ("000001", 0.0001),
        ("0000001", 0.00001),
        ("0", 0.0),
    ]

    assert settings.write_gerber_value(0.000000001) == "0"

    for string, value in test_cases:
        assert value == settings.parse_gerber_value(string)
        assert string == settings.write_gerber_value(value)


def test_format():
    test_cases = [
        ((2, 7), "1", 0.0000001),
        ((2, 6), "1", 0.000001),
        ((2, 5), "1", 0.00001),
        ((2, 4), "1", 0.0001),
        ((2, 3), "1", 0.001),
        ((2, 2), "1", 0.01),
        ((2, 1), "1", 0.1),
        ((2, 6), "0", 0),
    ]
    for fmt, string, value in test_cases:
        settings = FileSettings(number_format=fmt, zeros='leading')
        assert value == settings.parse_gerber_value(string)
        assert string == settings.write_gerber_value(value)

    test_cases = [
        ((6, 5), "1", 100000.0),
        ((5, 5), "1", 10000.0),
        ((4, 5), "1", 1000.0),
        ((3, 5), "1", 100.0),
        ((2, 5), "1", 10.0),
        ((1, 5), "1", 1.0),
        ((2, 5), "0", 0),
    ]
    for fmt, string, value in test_cases:
        settings = FileSettings(number_format=fmt, zeros='trailing')
        assert value == settings.parse_gerber_value(string)
        assert string == settings.write_gerber_value(value)

def test_parse_format_validation():
    for fmt in (7,5), (5,8), (13,1):
        with pytest.raises(ValueError):
            settings = FileSettings(number_format=fmt)
            settings.parse_gerber_value('00001111')


def test_write_format_validation():
    for fmt in (7,5), (5,8), (13,1):
        with pytest.raises(ValueError):
            settings = FileSettings(number_format=fmt)
            settings.write_gerber_value(69.0)

