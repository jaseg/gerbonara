#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2019 Hiroshi Murayama <opiopan@gmail.com>

import os
from ..common import loads as loads_org
from ..exceptions import ParseError
from ..utils import detect_file_format
from .. import rs274x
from .. import ipc356

from . import rs274x as ex_rs274x
from . import excellon
from . import dxf

def read(filename, format=None):
    with open(filename, 'rU') as f:
        data = f.read()
    return loads(data, filename, format=format)


def loads(data, filename=None, format=None):
    if os.path.splitext(filename if filename else '')[1].lower() == '.dxf':
        return dxf.loads(data, filename)

    fmt = detect_file_format(data)
    if fmt == 'rs274x':
        file = ex_rs274x.loads(data, filename=filename)
        return ex_rs274x.GerberFile.from_gerber_file(file)
    elif fmt == 'excellon':
        return excellon.loads(data, filename=filename, format=format)
    elif fmt == 'ipc_d_356':
        return ipc356.loads(data, filename=filename)
    else:
        raise ParseError('Unable to detect file format')


def rectangle(width, height, left=0, bottom=0, units='metric', draw_mode=None, filename=None):
    return dxf.DxfFile.rectangle(
        width, height, left, bottom, units, draw_mode, filename)
