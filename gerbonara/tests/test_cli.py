#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2023 Jan Sebastian Götte <gerbonara@jaseg.de>
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
from pathlib import Path
import re
import tempfile
import json

import pytest
from click.testing import CliRunner
from bs4 import BeautifulSoup

from .utils import *
from ..cli import render, rewrite, transform, merge, bounding_box, layers, meta

class TestRender:
    def invoke(self, *args):
        runner = CliRunner()
        res = runner.invoke(render, list(map(str, args)))
        assert res.exit_code == 0
        return res.output

    def test_basic(self):
        assert self.invoke('--version').startswith('Version ')

    @pytest.mark.parametrize('reference', ['example_flash_obround.gbr'], indirect=True)
    def test_warnings(self, reference):
        with pytest.warns(UserWarning):
            self.invoke(reference, '--warnings=once')

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_side(self, reference):
        without = self.invoke(reference, '--warnings=ignore')
        top = self.invoke(reference, '--top', '--warnings=ignore')
        bottom = self.invoke(reference, '--bottom', '--warnings=ignore')
        assert top.strip().startswith('<?xml')
        assert bottom.strip().startswith('<?xml')
        assert '<path' in top
        assert '<path' in bottom
        assert top == without
        assert top != bottom

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_margin(self, reference):
        no_margin = BeautifulSoup(self.invoke(reference, '--top', '--warnings=ignore'), features='xml')
        with_margin = BeautifulSoup(self.invoke(reference, '--top', '--warnings=ignore', '--margin=25'), features='xml')

        s = no_margin.find('svg')
        w_no = float(s['width'].rstrip('m'))
        h_no = float(s['height'].rstrip('m'))

        s = with_margin.find('svg')
        w_with = float(s['width'].rstrip('m'))
        h_with = float(s['height'].rstrip('m'))

        assert math.isclose(w_with, w_no+2*25, abs_tol=1e-6)
        assert math.isclose(h_with, h_no+2*25, abs_tol=1e-6)

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_force_bounds(self, reference):
        out = self.invoke(reference, '--top', '--warnings=ignore', '--force-bounds=10,10,50,50')
        s = BeautifulSoup(out, features='xml').find('svg')
        w = float(s['width'].rstrip('m'))
        h = float(s['height'].rstrip('m'))

        assert math.isclose(w, 40, abs_tol=1e-6)
        assert math.isclose(h, 40, abs_tol=1e-6)

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_inkscape(self, reference):
        out_with = self.invoke(reference, '--top', '--warnings=ignore', '--inkscape')
        out_without = self.invoke(reference, '--top', '--warnings=ignore', '--standard-svg')
        assert 'sodipodi' in out_with
        assert 'sodipodi' not in out_without

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_colorscheme(self, reference):
        out_without = self.invoke(reference, '--top', '--warnings=ignore')
        find_colors = lambda s: { m.group(0) for m in re.finditer(r'#[0-9a-fA-F]{6,}', s) }
        colors_without = find_colors(out_without)

        test_colorscheme = {
                'copper': '#012345',
                'mask': '#67890abc',
                'paste': '#def012',
                'silk': '#345678',
                'drill': '#90abcd',
                'outline': '#ff0123',
            }

        with tempfile.NamedTemporaryFile('w', suffix='.json') as f:
            json.dump(test_colorscheme, f)
            f.flush()

            out_with = self.invoke(reference, '--top', '--warnings=ignore', f'--colorscheme={f.name}')
            for color in colors_without:
                colors_with = find_colors(out_with)
                assert not colors_without & colors_with
                assert len(colors_without) == len(colors_with)
                assert colors_with - {'#67890a'} == set(test_colorscheme.values()) - {'#67890abc'}

