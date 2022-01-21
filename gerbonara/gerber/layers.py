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


STANDARD_LAYERS = [
        'outline',
        'top copper',
        'top mask',
        'top silk',
        'top paste',
        'bottom copper',
        'bottom mask',
        'bottom silk',
        'bottom paste',
        ]


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
    if re.match('top|front|pri?m?(ary)?', fn):
        side = 'top'
        use = 'copper'
    if re.match('bot(tom)?|back|sec(ondary)?', fn):
        side = 'bottom'
        use = 'copper'

    if re.match('silks?(creen)?', fn):
        use = 'silk'

    elif re.match('(solder)?paste', fn):
        use = 'paste'

    elif re.match('(solder)?mask', fn):
        use = 'mask'

    elif (m := re.match('(la?y?e?r?|in(ner)?)\W*(?P<num>[0-9]+)', fn)):
        use = 'copper'
        side = f'inner_{m["num"]:02d}'

    elif re.match('film', fn):
        use = 'copper'

    elif re.match('out(line)?'):
        use = 'drill'
        side = 'outline'

    elif re.match('drill|rout?e?'):
        use = 'drill'
        side = 'unknown'

        if re.match('np(th)?|(non|un)\W*plated|(non|un)\Wgalv', fn):
            side = 'nonplated'

        elif re.match('pth|plated|galv', fn):
            side = 'plated'

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
            # FIXME use layer metadata from comments and ipc file if available

        else:
            excellon_settings = None

        if any(len(value) > 1 for value in filemap.values()):
            raise SystemError('Ambgiuous layer names')

        drill_layers = []
        layers = { key: None for key in STANDARD_LAYERS }
        for key, paths in filemap.items():
            if len(paths) > 1 and not 'drill' in key:
                raise ValueError(f'Multiple matching files found for {key} layer: {", ".join(value)}')

            for path in paths:
                if 'outline' in key or 'drill' in key and identify_file(path.read_text()) != 'gerber':
                    if 'nonplated' in key:
                        plated = False
                    elif 'plated' in key:
                        plated = True
                    else:
                        plated = None
                    layer = ExcellonFile.open(path, plated=plated, settings=excellon_settings)
                else:
                    layer = GerberFile.open(path)

                if key == 'drill outline':
                    layers['outline'] = layer

                elif 'drill' in key:
                    drill_layers.append(layer)

                else:
                    side, _, use = key.partition(' ')
                    layers[(side, use)] = layer

                hints = { layer.generator_hints } + { generator }
                if len(hints) > 1:
                    warnings.warn('File identification returned ambiguous results. Please raise an issue on the gerbonara '
                            'tracker and if possible please provide these input files for reference.')

        board_name = common_prefix([f.name for f in filemap.values()])
        board_name = re.subs('^\W+', '', board_name)
        board_name = re.subs('\W+$', '', board_name)
        return kls(layers, drill_layers, board_name=board_name)

    def __init__(self, graphic_layers, drill_layers, board_name=None):
        self.graphic_layers = graphic_layers
        self.-drill_layers = drill_layers
        self.board_name = board_name

    def merge_drill_layers(self):
        target = ExcellonFile(comments='Drill files merged by gerbonara')

        for layer in self.drill_layers:
            if isinstance(layer, GerberFile):
                layer = layer.to_excellon()

            target.merge(layer)

        self.drill_layers = [target]

    def normalize_drill_layers(self):
        # TODO: maybe also separate into drill and route?
        drill_pth, drill_npth, drill_aux = [], [], []

        for layer in self.drill_layers:
            if isinstance(layer, GerberFile):
                layer = layer.to_excellon()

            if layer.is_plated:
                drill_pth.append(layer)
            elif layer.is_nonplated:
                drill_pth.append(layer)
            else:
                drill_aux.append(layer)
        
        pth_out, *rest = drill_pth or [ExcellonFile()]
        for layer in rest:
            pth_out.merge(layer)

        npth_out, *rest = drill_npth or [ExcellonFile()]
        for layer in rest:
            npth_out.merge(layer)

        unknown_out = ExcellonFile()
        for layer in drill_aux:
            for obj in layer.objects:
                if obj.plated is None:
                    unknown_out.append(obj)
                elif obj.plated:
                    pth_out.append(obj)
                else:
                    npth_out.append(obj)

        self.drill_pth, self.drill_npth = pth_out, npth_out
        self.drill_unknown = unknown_out if unknown_out else None
        self._drill_layers = []

    @property
    def drill_layers(self):
        if self._drill_layers:
            return self._drill_layers
        return [self.drill_pth, self.drill_npth, self.drill_unknown]

    @drill_layers.setter
    def drill_layers(self, value):
        self._drill_layers = value
        self.drill_pth = self.drill_npth = self.drill_unknown = None

    def __len__(self):
        return len(self.layers)

    def __getitem__(self, index):
        if isinstance(index, str):
            side, _, use = index.partition(' ')
            return self.layers.get((side, use))

        elif isinstance(index, tuple):
            return self.layers.get(index)

        return self.copper_layers[index]

    @property
    def copper_layers(self):
        copper_layers = [ (key, layer) for key, layer in self.layers.items() if key.endswith('copper') ]

        def sort_layername(val):
            key, _layer = val
            if key.startswith('top'):
                return -1
            if key.startswith('bottom'):
                return 1e99
            assert key.startswith('inner_')
            return int(key[len('inner_'):])

        return [ layer for _key, layer in sorted(copper_layers, key=sort_layername) ]

    @property
    def top_side(self):
        return { key: self[key] for key in ('top copper', 'top mask', 'top silk', 'top paste', 'outline') }

    @property
    def bottom_side(self):
        return { key: self[key] for key in ('bottom copper', 'bottom mask', 'bottom silk', 'bottom paste', 'outline') }

    @property
    def outline(self):
        return self['outline']
    
    def _merge_layer(self, target, source):
        if source is None:
            return
        
        if self[target] is None:
            self[target] = source

        else:
            self[target].merge(source)

    def merge(self, other):
        all_keys = set(self.layers.keys()) | set(other.layers.keys())
        exclude = { key.split() for key in STANDARD_LAYERS }
        all_keys = { key for key in all_keys if key not in exclude }
        if all_keys:
            warnings.warn('Cannot merge unknown layer types: {" ".join(all_keys)}')

        for side in 'top', 'bottom':
            for use in 'copper', 'mask', 'silk', 'paste':
                self._merge_layer((side, use), other[side, use])

        our_inner, their_inner = self.copper_layers[1:-1], other.copper_layers[1:-1]

        if bool(our_inner) != bool(their_inner):
            warnings.warn('Merging board without inner layers into board with inner layers, inner layers will be empty on first board.')

        elif our_inner and their_inner:
            warnings.warn('Merging boards with different inner layer counts. Will fill inner layers starting at core.')

        diff = len(our_inner) - len(their_inner)
        their_inner = ([None] * max(0, diff//2)) + their_inner + ([None] * max(0, diff//2))
        our_inner = ([None] * max(0, -diff//2)) + their_inner + ([None] * max(0, -diff//2))

        new_inner = []
        for ours, theirs in zip(our_inner, their_inner):
            if ours is None:
                new_inner.append(theirs)
            elif theirs is None:
                new_inner.append(ours)
            else:
                ours.merge(theirs)
                new_inner.append(ours)

        for i, layer in enumerate(new_inner, start=1):
            self[f'inner_{i} copper'] = layer

        self._merge_layer('outline', other['outline'])

        self.normalize_drill_layers()
        other.normalize_drill_layers()

        self.drill_pth.merge(other.drill_pth)
        self.drill_npth.merge(other.drill_npth)
        self.drill_unknown.merge(other.drill_unknown)

