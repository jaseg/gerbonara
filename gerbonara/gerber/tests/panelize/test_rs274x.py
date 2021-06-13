#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

import os
import tempfile
from pathlib import Path
from contextlib import contextmanager
import unittest
from ... import panelize

class TestRs274x(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        here = Path(__file__).parent
        cls.EXPECTSDIR = here / 'expects'
        cls.METRIC_FILE = here / 'data' / 'ref_gerber_metric.gtl'
        cls.INCH_FILE = here / 'data' / 'ref_gerber_inch.gtl'
        cls.SQ_FILE = here / 'data' / 'ref_gerber_single_quadrant.gtl'

    @contextmanager
    def _check_result(self, reference_fn):
        with tempfile.NamedTemporaryFile('rb') as tmp_out:
            yield tmp_out.name

            actual = tmp_out.read()
            expected = (self.EXPECTSDIR / reference_fn).read_bytes()
            self.assertEqual(actual, expected)

    def test_save(self):
        with self._check_result('RS2724x_save.gtl') as outfile:
            gerber = panelize.read(self.METRIC_FILE)
            gerber.write(outfile)

    def test_to_inch(self):
        with self._check_result('RS2724x_to_inch.gtl') as outfile:
            gerber = panelize.read(self.METRIC_FILE)
            gerber.to_inch()
            gerber.format = (2,5)
            gerber.write(outfile)

    def test_to_metric(self):
        with self._check_result('RS2724x_to_metric.gtl') as outfile:
            gerber = panelize.read(self.INCH_FILE)
            gerber.to_metric()
            gerber.format = (3, 4)
            gerber.write(outfile)

    def test_offset(self):
        with self._check_result('RS2724x_offset.gtl') as outfile:
            gerber = panelize.read(self.METRIC_FILE)
            gerber.offset(11, 5)
            gerber.write(outfile)

    def test_rotate(self):
        with self._check_result('RS2724x_rotate.gtl') as outfile:
            gerber = panelize.read(self.METRIC_FILE)
            gerber.rotate(20, (10,10))
            gerber.write(outfile)

    def test_single_quadrant(self):
        with self._check_result('RS2724x_single_quadrant.gtl') as outfile:
            gerber = panelize.read(self.SQ_FILE)
            gerber.write(outfile)

