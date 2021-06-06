#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

import os
import unittest
import gerberex
from gerber.utils import inch, metric


class TestExcellon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.INDIR = 'data'
        cls.OUTDIR = 'outputs'
        cls.EXPECTSDIR = 'expects'
        cls.OUTPREFIX = 'dxf_'
        cls.METRIC_FILE = os.path.join(cls.INDIR, 'ref_dxf_metric.dxf')
        cls.INCH_FILE = os.path.join(cls.INDIR, 'ref_dxf_inch.dxf')
        cls.COMPLEX_FILE = os.path.join(cls.INDIR, 'ref_dxf_complex.dxf')
        try:
            os.mkdir(cls.OUTDIR)
        except FileExistsError:
            pass

    def _checkResult(self, file):
        with open(file, 'r') as f:
            data = f.read()
        with open(os.path.join(self.EXPECTSDIR, os.path.basename(file)), 'r') as f:
            expect = f.read()
        self.assertEqual(data, expect)

    def test_save_line(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'save_line.gtl')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.draw_mode = dxf.DM_LINE
        dxf.width = 0.2
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_save_fill(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'save_fill.gtl')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.draw_mode = dxf.DM_FILL
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_save_fill_simple(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'save_fill_simple.gtl')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.draw_mode = dxf.DM_FILL
        dxf.fill_mode = dxf.FM_SIMPLE
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_save_mousebites(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'save_mousebites.gtl')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.draw_mode = dxf.DM_MOUSE_BITES
        dxf.width = 0.5
        dxf.pitch = 1.4
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_save_excellon(self):
        outfile = os.path.join(
            self.OUTDIR, self.OUTPREFIX + 'save_line.txt')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.draw_mode = dxf.DM_LINE
        dxf.format = (3,3)
        dxf.width = 0.2
        dxf.write(outfile, filetype=dxf.FT_EXCELLON)
        self._checkResult(outfile)

    def test_save_excellon_mousebites(self):
        outfile = os.path.join(
            self.OUTDIR, self.OUTPREFIX + 'save_mousebites.txt')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.draw_mode = dxf.DM_MOUSE_BITES
        dxf.format = (3, 3)
        dxf.width = 0.5
        dxf.pitch = 1.4
        dxf.write(outfile, filetype=dxf.FT_EXCELLON)
        self._checkResult(outfile)

    def test_to_inch(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'to_inch.gtl')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.to_inch()
        dxf.format = (2, 5)
        dxf.write(outfile)
        self._checkResult(outfile)

    def _test_to_metric(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'to_metric.gtl')
        dxf = gerberex.read(self.INCH_FILE)
        dxf.to_metric()
        dxf.format = (3, 5)
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_offset(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'offset.gtl')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.offset(11, 5)
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_rotate(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'rotate.gtl')
        dxf = gerberex.read(self.METRIC_FILE)
        dxf.rotate(20, (10, 10))
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_rectangle_metric(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'rectangle_metric.gtl')
        dxf = gerberex.DxfFile.rectangle(width=10, height=10, units='metric')
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_rectangle_inch(self):
        outfile = os.path.join(
            self.OUTDIR, self.OUTPREFIX + 'rectangle_inch.gtl')
        dxf = gerberex.DxfFile.rectangle(width=inch(10), height=inch(10), units='inch')
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_complex_fill(self):
        outfile = os.path.join(self.OUTDIR, self.OUTPREFIX + 'complex_fill.gtl')
        dxf = gerberex.read(self.COMPLEX_FILE)
        dxf.draw_mode = dxf.DM_FILL
        dxf.write(outfile)
        self._checkResult(outfile)

    def test_complex_fill_flip(self):
        outfile = os.path.join(
            self.OUTDIR, self.OUTPREFIX + 'complex_fill_flip.gtl')
        ctx = gerberex.GerberComposition()
        base = gerberex.rectangle(width=100, height=100, left=0, bottom=0, units='metric')
        base.draw_mode = base.DM_FILL
        ctx.merge(base)
        dxf = gerberex.read(self.COMPLEX_FILE)
        dxf.negate_polarity()
        dxf.draw_mode = dxf.DM_FILL
        ctx.merge(dxf)
        ctx.dump(outfile)
        self._checkResult(outfile)

if __name__ == '__main__':
    unittest.main()
