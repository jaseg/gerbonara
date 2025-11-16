#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2022 Jan Sebastian Götte <gerbonara@jaseg.de>
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

import pytest
import functools
import tempfile
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from PIL import Image
import pytest

fail_dir = Path('gerbonara_test_failures')
reference_path = lambda reference: Path(__file__).parent / 'resources' / str(reference)
to_gerbv_svg_units = lambda val, unit='mm': val*72 if unit == 'inch' else val/25.4*72

def path_test_name(request):
    """ Create a slug suitable for use in file names from the test's nodeid """
    module, _, test_name = request.node.nodeid.rpartition('::')
    _test, _, test_name = test_name.partition('_')
    test_name, _, _ext = test_name.partition('.')
    return re.sub(r'[^\w\d]', '_', test_name)

@pytest.fixture
def print_on_error(request):
    messages = []

    def register_print(*args, sep=' ', end='\n'):
        nonlocal messages
        messages.append(sep.join(str(arg) for arg in args) + end)

    yield register_print

    if request.node.rep_call.failed:
        for msg in messages:
            print(msg, end='')

@pytest.fixture
def tmpfile(request):
    registered = []

    def register_tempfile(name, suffix):
        nonlocal registered
        f = tempfile.NamedTemporaryFile(suffix=suffix)
        registered.append((name, suffix, f))
        return Path(f.name)

    yield register_tempfile

    if request.node.rep_call.failed:
        fail_dir.mkdir(exist_ok=True)
        test_name = path_test_name(request)
        for name, suffix, tmp in registered:
            slug = re.sub(r'[^\w\d]+', '_', name.lower())
            perm_path = fail_dir / f'failure_{test_name}_{slug}{suffix}'
            shutil.copy(tmp.name, perm_path)
            print(f'{name} saved to {perm_path}')

    for _name, _suffix, tmp in registered:
        tmp.close()

@pytest.fixture
def reference(request, print_on_error):
    ref = request.param
    if isinstance(ref, tuple):
        ref, args = ref
        ref = reference_path(ref)
        yield ref, args

    else:
        ref = reference_path(request.param)
        yield ref

    print_on_error(f'Reference file: {ref}')

def filter_syntax_warnings(fun):
    a = pytest.mark.filterwarnings('ignore:.*Deprecated.*statement found.*:DeprecationWarning')
    b = pytest.mark.filterwarnings('ignore::SyntaxWarning')
    return a(b(fun))


