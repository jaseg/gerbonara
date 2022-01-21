#! /usr/bin/env python
# -*- coding: utf-8 -*-

# copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
import warnings
from collections import namedtuple

from .excellon import ExcellonFile
from .ipc356 import IPCNetlist

def match_files(filenames):
    matches = {}
    for generator, rules in MATCH_RULES.items():
        gen = {}
        matches[generator] = gen
        for layer, regex in rules.items():
            for fn in filenames:
                if (m := re.fullmatch(regex, fn.name.lower())):
                    if layer == 'inner copper':
                        layer = 'inner_' + ''.join(m.groups()) + ' copper'
                    gen[layer] = gen.get(layer, []) + [fn]
    return matches

def best_match(filenames):
    matches = match_files(filenames)
    matches = sorted(matches.items(), key=lambda pair: len(pair[1]))
    generator, files = matches[-1]
    return generator, files

def identify_file(data):
    if 'M48' in data or 'G90' in data:
        return 'excellon'
    if 'FSLAX' in data or 'FSTAX' in data:
        return 'gerber'
    return None

def common_prefix(l):
    out = []
    for cand in l:
        score = lambda n: sum(elem.startswith(cand[:n]) for elem in l)
        baseline = score(1)
        if len(l) - baseline > 5:
            continue
        for n in range(2, len(cand)):
            if len(l) - score(n) > 5:
                break
        out.append(cand[:n-1])
 
    if not out:
        return ''
 
    return sorted(out, key=len)[-1]

def autoguess(filenames):
    prefix = common_prefix([f.name for f in filenames])

    matches = { layername_autoguesser(f.name[len(prefix):] if f.name.startswith(prefix) else f.name): f
            for f in filenames }

    inner_layers = [ m for m in matches if 'inner' in m ]
    if len(inner_layers) >= 4 and not 'copper top' in matches and not 'copper bottom' in matches:
        matches['copper top'] = matches.pop('copper inner1')
        last_inner = sorted(inner_layers, key=lambda name: int(name.partition(' ')[0].partition('_')[2]))[-1]
        matches['copper bottom'] = matches.pop(last_inner)

    return matches

def layername_autoguesser(fn):
    fn, _, _ext = fn.lower().rpartition('.')

    side, use = 'unknown', 'unknown'
    hint = ''
    if re.match('top|front|pri?m?(ary)?', fn):
        side = 'top'
        use = 'copper'
    if re.match('bot|bottom|back|sec(ondary)?', fn):
        side = 'bottom'
        use = 'copper'

    if re.match('silks?(creen)?', fn):
        use = 'silk'
    elif re.match('(solder)?paste', fn):
        use = 'paste'
    elif re.match('(solder)?mask', fn):
        use = 'mask'
    elif (m := re.match('([tbcps])sm([tbcps])', fn)):
        use = 'mask'
        hint = m[1] + m[2]
    elif (m := re.match('([tbcps])sp([tbcps])', fn)):
        use = 'paste'
        hint = m[1] + m[2]
    elif (m := re.match('([tbcps])sl?k([tbcps])', fn)):
        use = 'silk'
        hint = m[1] + m[2]
    elif (m := re.match('(la?y?e?r?|inn?e?r?)\W*([0-9]+)', fn)):
        use = 'copper'
        side = f'inner_{m[1]}'
    elif re.match('film', fn):
        use = 'copper'
    elif re.match('drill|rout?e?|outline'):
        use = 'drill'
        side = 'unknown'

        if re.match('np(th)?|(non|un)\W*plated|(non|un)\Wgalv', fn):
            side = 'nonplated'
        elif re.match('pth|plated|galv', fn):
            side = 'plated'

    if side is None and hint:
        hint = set(hint)
        if len(hint) == 1:
            and hint[0] in 'tpc':
                side = 'top'
            else
                side = 'bottom'

    return f'{use} {side}'

class LayerStack:
    @classmethod
    def from_directory(kls, directory, board_name=None, verbose=False):

        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f'{directory} is not a directory')

        files = [ path for path in directory.glob('**/*') if path.is_file() ]
        generator, filemap = best_match(files)

        if len(filemap) < 6:
            generator = None
            filemap = autoguess(files)
            if len(filemap < 6):
                raise ValueError('Cannot figure out gerber file mapping')

        elif generator == 'geda':
            # geda is written by geniuses who waste no bytes of unnecessary output so it doesn't actually include the
            # number format in files that use imperial units. Unfortunately it also doesn't include any hints that the
            # file was generated by geda, so we have to guess by context whether this is just geda being geda or
            # potential user error.
            excellon_settings = FileSettings(number_format=(2, 4))

        elif generator == 'allegro':
            # Allegro puts information that is absolutely vital for parsing its excellon files... into another file,
            # next to the actual excellon file. Despite pretty much everyone else having figured out a way to put that
            # info into the excellon file itself, even if only as a comment.
            if 'excellon params' in filemap:
                excellon_settings = parse_allegro_ncparam(filemap['excellon params'][0].read_text())
                del filemap['excellon params']
            # Ignore if we can't find the param file -- maybe the user has convinced Allegro to actually put this
            # information into a comment, or maybe they have made Allegro just use decimal points like XNC does.

            filemap = autoguess([ f for files in filemap for f in files ])
            if len(filemap < 6):
                raise SystemError('Cannot figure out gerber file mapping')

        else:
            excellon_settings = None

        if any(len(value) > 1 for value in filemap.values()):
            raise SystemError('Ambgiuous layer names')

        filemap = { key: values[0] for key, value in filemap.items() }

        layers = {}
        for key, path in filemap.items():
            if 'outline' in key or 'drill' in key and identify_file(path.read_text()) != 'gerber':
                if 'nonplated' in key:
                    plated = False
                elif 'plated' in key:
                    plated = True
                else:
                    plated = None
                layers[key] = ExcellonFile.open(path, plated=plated, settings=excellon_settings)
            else:
                layers[key] = GerberFile.open(path)

            hints = { layers[key].generator_hints } + { generator }
            if len(hints) > 1:
                warnings.warn('File identification returned ambiguous results. Please raise an issue on the gerbonara '
                        'tracker and if possible please provide these input files for reference.')

        board_name = common_prefix([f.name for f in filemap.values()])
        board_name = re.subs('^\W+', '', board_name)
        board_name = re.subs('\W+$', '', board_name)
        return kls(layers, board_name=board_name)

    def __init__(self, layers, board_name=None):
        self.layers = layers
        self.board_name = board_name

    def __len__(self):
        return len(self.layers)

