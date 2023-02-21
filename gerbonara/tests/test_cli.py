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

from pathlib import Path

import pytest
from click.testing import CliRunner

from .utils import *
from ..cli import render, rewrite, transform, merge, bounding_box, layers, meta

class TestRender:
    def invoke(self, *args):
        runner = CliRunner()
        res = runner.invoke(render, list(map(str, args)))
        print(res.output)
        assert res.exit_code == 0
        return res.output

    def test_basic(self):
        assert self.invoke('--version').startswith('Version ')

    @pytest.mark.parametrize('reference', ['example_flash_obround.gbr'], indirect=True)
    def test_warnings(self, reference):
        with pytest.warns(UserWarning):
            self.invoke(reference, '--warnings=once')

