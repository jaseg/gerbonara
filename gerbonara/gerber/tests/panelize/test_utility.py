#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

import unittest

from ...panelize.utility import *
from math import sqrt

class TestUtility(unittest.TestCase):
    def test_is_equal_value(self):
        a = 10.0001
        b = 10.01

        self.assertTrue(is_equal_value(a, b, 0.1))
        self.assertTrue(is_equal_value(a, b, 0.01))
        self.assertFalse(is_equal_value(a, b, 0.001))
        self.assertFalse(is_equal_value(a, b))

        self.assertTrue(is_equal_value(b, a, 0.1))
        self.assertTrue(is_equal_value(b, a, 0.01))
        self.assertFalse(is_equal_value(b, a, 0.001))
        self.assertFalse(is_equal_value(b, a))

    def test_is_equal_point(self):
        p0 = (10.01, 5.001)
        p1 = (10.0001, 5)
        self.assertTrue(is_equal_point(p0, p1, 0.1))
        self.assertTrue(is_equal_point(p0, p1, 0.01))
        self.assertFalse(is_equal_point(p0, p1, 0.001))
        self.assertFalse(is_equal_point(p0, p1))
        self.assertTrue(is_equal_point(p1, p0, 0.1))
        self.assertTrue(is_equal_point(p1, p0, 0.01))
        self.assertFalse(is_equal_point(p1, p0, 0.001))
        self.assertFalse(is_equal_point(p1, p0))

        p0 = (5.001, 10.01)
        p1 = (5, 10.0001)
        self.assertTrue(is_equal_point(p0, p1, 0.1))
        self.assertTrue(is_equal_point(p0, p1, 0.01))
        self.assertFalse(is_equal_point(p0, p1, 0.001))
        self.assertFalse(is_equal_point(p0, p1))
        self.assertTrue(is_equal_point(p1, p0, 0.1))
        self.assertTrue(is_equal_point(p1, p0, 0.01))
        self.assertFalse(is_equal_point(p1, p0, 0.001))
        self.assertFalse(is_equal_point(p1, p0))

