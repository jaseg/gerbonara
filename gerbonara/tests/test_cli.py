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
from unittest import mock

import pytest
from click.testing import CliRunner
from bs4 import BeautifulSoup

from .utils import *
from .. import cli
from ..utils import MM


@pytest.fixture()
def file_mock():
    old = cli.GerberFile
    c_obj = cli.GerberFile = mock.Mock()
    i_obj = c_obj.open.return_value = mock.Mock()
    i_obj.bounding_box.return_value = (0, 0), (50, 100)
    yield i_obj
    cli.GerberFile = old


class TestRender:
    def invoke(self, outfile, *args):
        runner = CliRunner()
        res = runner.invoke(cli.render, list(map(str, args)))
        outfile.write_text(str(res.output))
        if res.exception:
            raise res.exception
        assert res.exit_code == 0
        return res.output

    def test_basic(self, tmpfile):
        assert self.invoke(tmpfile('Standard output', '.svg'), '--version').startswith('Version ')

    @pytest.mark.parametrize('reference', ['example_flash_obround.gbr'], indirect=True)
    def test_warnings(self, reference, tmpfile):
        with pytest.warns(UserWarning):
            self.invoke(tmpfile('Standard output', '.svg'), reference, '--warnings=once')

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_side(self, reference, tmpfile):
        without = self.invoke(tmpfile('Standard output, without args', '.svg'), reference, '--warnings=ignore')
        top = self.invoke(tmpfile('Standard output, --top', '.svg'), reference, '--top', '--warnings=ignore')
        bottom = self.invoke(tmpfile('Standard output, --bottom', '.svg'), reference, '--bottom', '--warnings=ignore')
        assert top.strip().startswith('<?xml')
        assert bottom.strip().startswith('<?xml')
        assert '<path' in top
        assert '<path' in bottom
        assert top == without
        assert top != bottom

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_margin(self, reference, tmpfile):
        no_margin = BeautifulSoup(self.invoke(tmpfile('Without margin', '.svg'), reference, '--top', '--warnings=ignore'), features='xml')
        with_margin = BeautifulSoup(self.invoke(tmpfile('With margin', '.svg'), reference, '--top', '--warnings=ignore', '--margin=25'), features='xml')

        s = no_margin.find('svg')
        w_no = float(s['width'].rstrip('m'))
        h_no = float(s['height'].rstrip('m'))

        s = with_margin.find('svg')
        w_with = float(s['width'].rstrip('m'))
        h_with = float(s['height'].rstrip('m'))

        assert math.isclose(w_with, w_no+2*25, abs_tol=1e-6)
        assert math.isclose(h_with, h_no+2*25, abs_tol=1e-6)

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_force_bounds(self, reference, tmpfile):
        out = self.invoke(tmpfile('Standard output', '.svg'), reference, '--top', '--warnings=ignore', '--force-bounds=10,10,50,50')
        s = BeautifulSoup(out, features='xml').find('svg')
        w = float(s['width'].rstrip('m'))
        h = float(s['height'].rstrip('m'))

        assert math.isclose(w, 40, abs_tol=1e-6)
        assert math.isclose(h, 40, abs_tol=1e-6)

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_inkscape(self, reference, tmpfile):
        out_with = self.invoke(tmpfile('Inkscape SVG', '.svg'), reference, '--top', '--warnings=ignore', '--inkscape')
        out_without = self.invoke(tmpfile('Standard SVG', '.svg'), reference, '--top', '--warnings=ignore', '--standard-svg')
        assert 'sodipodi' in out_with
        assert 'sodipodi' not in out_without

    @pytest.mark.parametrize('reference', ['kicad-older'], indirect=True)
    def test_colorscheme(self, reference, tmpfile):
        out_without = self.invoke(tmpfile('Standard output', '.svg'), reference, '--top', '--warnings=ignore')
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

            out_with = self.invoke(tmpfile('Output with colorscheme', '.svg'), reference, '--top', '--warnings=ignore', f'--colorscheme={f.name}')
            for color in colors_without:
                colors_with = find_colors(out_with)
                assert not colors_without & colors_with
                assert len(colors_without) == len(colors_with)
                assert colors_with - {'#67890a'} == set(test_colorscheme.values()) - {'#67890abc'}


class TestRewrite:
    def invoke(self, outfile, *args):
        runner = CliRunner()
        res = runner.invoke(cli.rewrite, list(map(str, args)))
        outfile.write_text(res.output)
        if res.exception:
            raise res.exception
        assert res.exit_code == 0
        return res.output

    def test_basic(self, tmpfile):
        assert self.invoke(tmpfile('Standard output', '.svg'), '--version').startswith('Version ')

    @pytest.mark.parametrize('reference', ['example_flash_obround.gbr'], indirect=True)
    def test_transforms(self, reference, file_mock, tmpfile):
        with tempfile.NamedTemporaryFile() as tmpout:
            self.invoke(tmpfile('Standard output', '.svg'), reference, tmpout.name, '--transform', 'rotate(90); translate(10, 10); rotate(-45.5); scale(2)')
            file_mock.rotate.assert_has_calls([
                mock.call(math.radians(90), 0, 0, MM),
                mock.call(math.radians(-45.5), 0, 0, MM)])
            file_mock.offset.assert_called_with(10, 10, MM)
            file_mock.scale.assert_called_with(2)
            assert file_mock.save.called
            assert file_mock.save.call_args[0][0] == tmpout.name

    @pytest.mark.parametrize('reference', ['example_flash_obround.gbr'], indirect=True)
    def test_real_invocation(self, reference, tmpfile):
        with tempfile.NamedTemporaryFile() as tmpout:
            self.invoke(tmpfile('Standard output', '.svg'), reference, tmpout.name, '--transform', 'rotate(45); translate(10, 0)')
            assert tmpout.read()


class TestMerge:
    def invoke(self, *args):
        runner = CliRunner()
        res = runner.invoke(cli.merge, list(map(str, args)))
        if res.exception:
            raise res.exception
        assert res.exit_code == 0
        return res.output

    def test_basic(self):
        assert self.invoke('--version').startswith('Version ')

    @pytest.mark.parametrize('file_a', ['kicad-older'])
    @pytest.mark.parametrize('file_b', ['eagle-newer'])
    def test_real_invocation(self, file_a, file_b):
        with tempfile.TemporaryDirectory() as outdir:
            self.invoke(reference_path(file_a), '--rotation', '90', '--offset', '0,0',
                        reference_path(file_b), '--offset', '100,100', '--rotation', '0',
                        outdir, '--output-naming-scheme', 'kicad', '--output-board-name', 'foobar',
                        '--warnings', 'ignore')
            assert (Path(outdir) / 'foobar-F.Cu.gbr').exists()


class TestMeta:
    def invoke(self, outfile, *args):
        runner = CliRunner()
        res = runner.invoke(cli.meta, list(map(str, args)))
        outfile.write_text(str(res.output))
        if res.exception:
            raise res.exception
        assert res.exit_code == 0
        return res.output

    def test_basic(self, tmpfile):
        assert self.invoke(tmpfile('Standard output', '.svg'), '--version').startswith('Version ')

    @pytest.mark.parametrize('reference', ['example_flash_obround.gbr'], indirect=True)
    def test_real_invocation(self, reference, tmpfile):
        j = json.loads(self.invoke(tmpfile('Standard output', '.svg'), reference, '--warnings', 'ignore'))

