#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

import os
import tempfile
from pathlib import Path
from contextlib import contextmanager
import unittest
from ... import panelize

class TestExcellon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        here = Path(__file__).parent
        cls.EXPECTSDIR = here / 'expects'
        cls.METRIC_FILE = here / 'data' / 'ref_drill_metric.txt'
        cls.INCH_FILE = here / 'data' / 'ref_drill_inch.txt'

    @contextmanager
    def _check_result(self, reference_fn):
        with tempfile.NamedTemporaryFile('rb') as tmp_out:
            yield tmp_out.name

            actual = tmp_out.read()
            expected = (self.EXPECTSDIR / reference_fn).read_bytes()
            self.assertEqual(actual, expected)

    def test_save(self):
        with self._check_result('excellon_save.txt') as outfile:
            drill = panelize.read(self.METRIC_FILE)
            drill.write(outfile)

    def test_to_inch(self):
        with self._check_result('excellon_to_inch.txt') as outfile:
            drill = panelize.read(self.METRIC_FILE)
            drill.to_inch()
            drill.format = (2, 4)
            drill.write(outfile)

    def test_to_metric(self):
        with self._check_result('excellon_to_metric.txt') as outfile:
            drill = panelize.read(self.INCH_FILE)
            drill.to_metric()
            drill.format = (3, 3)
            drill.write(outfile)

    def test_offset(self):
        with self._check_result('excellon_offset.txt') as outfile:
            drill = panelize.read(self.METRIC_FILE)
            drill.offset(11, 5)
            drill.write(outfile)

    def test_rotate(self):
        with self._check_result('excellon_rotate.txt') as outfile:
            drill = panelize.read(self.METRIC_FILE)
            drill.rotate(20, (10, 10))
            drill.write(outfile)

