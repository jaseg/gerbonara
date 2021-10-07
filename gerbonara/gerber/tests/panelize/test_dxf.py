#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

import os
import tempfile
from pathlib import Path
from contextlib import contextmanager
import unittest

from ... import panelize
from ...utils import inch, metric


@unittest.skip
class TestExcellon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        here = Path(__file__).parent
        cls.EXPECTSDIR = here / 'expects'

        cls.METRIC_FILE = here / 'data' / 'ref_dxf_metric.dxf'
        cls.INCH_FILE = here / 'data' / 'ref_dxf_inch.dxf'
        cls.COMPLEX_FILE = here / 'data' / 'ref_dxf_complex.dxf'

    @contextmanager
    def _check_result(self, reference_fn):
        with tempfile.NamedTemporaryFile('rb') as tmp_out:
            yield tmp_out.name

            actual = tmp_out.read()
            expected = (self.EXPECTSDIR / reference_fn).read_bytes()
            self.assertEqual(actual, expected)

    def test_save_line(self):
        with self._check_result('dxf_save_line.gtl') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.draw_mode = dxf.DM_LINE
            dxf.width = 0.2
            dxf.write(outfile)

    def test_save_fill(self):
        with self._check_result('dxf_save_fill.gtl') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.draw_mode = dxf.DM_FILL
            dxf.write(outfile)

    def test_save_fill_simple(self):
        with self._check_result('dxf_save_fill_simple.gtl') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.draw_mode = dxf.DM_FILL
            dxf.fill_mode = dxf.FM_SIMPLE
            dxf.write(outfile)

    def test_save_mousebites(self):
        with self._check_result('dxf_save_mousebites.gtl') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.draw_mode = dxf.DM_MOUSE_BITES
            dxf.width = 0.5
            dxf.pitch = 1.4
            dxf.write(outfile)

    def test_save_excellon(self):
        with self._check_result('dxf_save_line.txt') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.draw_mode = dxf.DM_LINE
            dxf.format = (3,3)
            dxf.width = 0.2
            dxf.write(outfile, filetype=dxf.FT_EXCELLON)

    def test_save_excellon_mousebites(self):
        with self._check_result('dxf_save_mousebites.txt') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.draw_mode = dxf.DM_MOUSE_BITES
            dxf.format = (3, 3)
            dxf.width = 0.5
            dxf.pitch = 1.4
            dxf.write(outfile, filetype=dxf.FT_EXCELLON)

    def test_to_inch(self):
        with self._check_result('dxf_to_inch.gtl') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.to_inch()
            dxf.format = (2, 5)
            dxf.write(outfile)

    def _test_to_metric(self):
        with self._check_result('dxf_to_metric.gtl') as outfile:
            dxf = panelize.read(self.INCH_FILE)
            dxf.to_metric()
            dxf.format = (3, 5)
            dxf.write(outfile)

    def test_offset(self):
        with self._check_result('dxf_offset.gtl') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.offset(11, 5)
            dxf.write(outfile)

    def test_rotate(self):
        with self._check_result('dxf_rotate.gtl') as outfile:
            dxf = panelize.read(self.METRIC_FILE)
            dxf.rotate(20, (10, 10))
            dxf.write(outfile)

    def test_rectangle_metric(self):
        with self._check_result('dxf_rectangle_metric.gtl') as outfile:
            dxf = panelize.DxfFile.rectangle(width=10, height=10, units='metric')
            dxf.write(outfile)

    def test_rectangle_inch(self):
        with self._check_result('dxf_rectangle_inch.gtl') as outfile:
            dxf = panelize.DxfFile.rectangle(width=inch(10), height=inch(10), units='inch')
            dxf.write(outfile)

    def test_complex_fill(self):
        with self._check_result('dxf_complex_fill.gtl') as outfile:
            dxf = panelize.read(self.COMPLEX_FILE)
            dxf.draw_mode = dxf.DM_FILL
            dxf.write(outfile)

    def test_complex_fill_flip(self):
        with self._check_result('dxf_complex_fill_flip.gtl') as outfile:
            ctx = panelize.GerberComposition()
            base = panelize.rectangle(width=100, height=100, left=0, bottom=0, units='metric')
            base.draw_mode = base.DM_FILL
            ctx.merge(base)
            dxf = panelize.read(self.COMPLEX_FILE)
            dxf.negate_polarity()
            dxf.draw_mode = dxf.DM_FILL
            ctx.merge(dxf)
            ctx.dump(outfile)

