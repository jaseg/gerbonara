#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2022 Jan Sebastian Götte <code@jaseg.de>
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

"""
Gerbonara
=========

gerbonara provides utilities for working with PCB artwork files in Gerber/RS274-X, XNC/Excellon and IPC-356 formats. It
includes convenience functions to match file names to layer types that match the default settings of a number of common
EDA tools.
"""

from .rs274x import GerberFile
from .excellon import ExcellonFile
from .ipc356 import Netlist
from .layers import LayerStack
from .utils import MM, Inch

__version__ = '1.5.0'
