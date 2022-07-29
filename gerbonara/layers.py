#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2014 Hamilton Kibbe <ham@hamiltonkib.be>
# Copyright 2022 Jan Götte <code@jaseg.de>
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

import os
import io
import sys
import re
import warnings
import copy
import bisect
import textwrap
import itertools
from collections import namedtuple
from pathlib import Path
from zipfile import ZipFile, is_zipfile
import tempfile

from .excellon import ExcellonFile, parse_allegro_ncparam, parse_allegro_logfile
from .rs274x import GerberFile
from .ipc356 import Netlist
from .cam import FileSettings, LazyCamFile
from .layer_rules import MATCH_RULES
from .utils import sum_bounds, setup_svg, MM, Tag
from . import graphic_objects as go
from . import graphic_primitives as gp


STANDARD_LAYERS = [
        'mechanical outline',
        'top copper',
        'top mask',
        'top silk',
        'top paste',
        'bottom copper',
        'bottom mask',
        'bottom silk',
        'bottom paste',
        ]

DEFAULT_COLORS = {
        'copper': '#cccccc',
        'mask': '#004200bf',
        'paste': '#999999',
        'silk': '#e0e0e0',
        'drill': '#303030',
        'outline': '#F0C000',
    }

class NamingScheme:
    kicad = {
    'top copper':           '{board_name}-F.Cu.gbr',
    'top mask':             '{board_name}-F.Mask.gbr',
    'top silk':             '{board_name}-F.SilkS.gbr',
    'top paste':            '{board_name}-F.Paste.gbr',
    'bottom copper':        '{board_name}-B.Cu.gbr',
    'bottom mask':          '{board_name}-B.Mask.gbr',
    'bottom silk':          '{board_name}-B.SilkS.gbr',
    'bottom paste':         '{board_name}-B.Paste.gbr',
    'inner copper':         '{board_name}-In{layer_number}.Cu.gbr',
    'mechanical outline':   '{board_name}-Edge.Cuts.gbr',
    'unknown drill':        '{board_name}.drl',
    'plated drill':         '{board_name}.plated.drl',
    'nonplated drill':      '{board_name}.nonplated.drl',
    'other netlist':        '{board_name}.d356',
    }

    altium = {
    'top copper':           '{board_name}.gtl',
    'top mask':             '{board_name}.gts',
    'top silk':             '{board_name}.gto',
    'top paste':            '{board_name}.gtp',
    'bottom copper':        '{board_name}.gbl',
    'bottom mask':          '{board_name}.gbs',
    'bottom silk':          '{board_name}.gbo',
    'bottom paste':         '{board_name}.gbp',
    'inner copper':         '{board_name}.gp{layer_number}',
    'mechanical outline':   '{board_name}.gko',
    'unknown drill':        '{board_name}.drl',
    'plated drill':         '{board_name}.plated.drl',
    'nonplated drill':      '{board_name}.nonplated.drl',
    }



def match_files(filenames):
    matches = {}
    for generator, rules in MATCH_RULES.items():
        gen = {}
        matches[generator] = gen
        for layer, regex in rules.items():
            for fn in filenames:
                if (m := re.fullmatch(regex, fn.name, re.IGNORECASE)):
                    if layer == 'inner copper':
                        target = 'inner_' + ''.join(e or '' for e in m.groups()) + ' copper'
                    else:
                        target = layer
                    gen[target] = gen.get(target, []) + [fn]
    return matches


def best_match(filenames):
    matches = match_files(filenames)
    matches = sorted(matches.items(), key=lambda pair: len(pair[1]))
    generator, files = matches[-1]
    return generator, files


def identify_file(data):
    if 'M48' in data:
        return 'excellon'

    if 'G90' in data and ';LEADER:' in data: # yet another allegro special case
        return 'excellon'

    if 'FSLAX' in data or 'FSTAX' in data:
        return 'gerber'

    if 'UNITS CUST' in data:
        return 'ipc356'

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

    matches = {}
    for f in filenames:
        name = layername_autoguesser(f.name[len(prefix):] if f.name.startswith(prefix) else f.name)
        if name != 'unknown unknown':
            matches[name] = matches.get(name, []) + [f]

    inner_layers = [ m for m in matches if 'inner' in m ]
    if len(inner_layers) >= 2 and 'copper top' not in matches and 'copper bottom' not in matches:
        if 'inner_01 copper' in matches:
            warnings.warn('Could not find copper layer. Re-assigning outermost inner layers to top/bottom copper.')
            matches['top copper'] = matches.pop('inner_01 copper')
            last_inner = sorted(inner_layers, key=lambda name: int(name.partition(' ')[0].partition('_')[2]))[-1]
            matches['bottom copper'] = matches.pop(last_inner)

    return matches


def layername_autoguesser(fn):
    fn, _, ext = fn.lower().rpartition('.')
    
    if ext in ('log', 'err', 'fdl', 'py', 'sh', 'md', 'rst', 'zip', 'pdf', 'svg', 'ps', 'png', 'jpg', 'bmp'):
        return 'unknown unknown'

    side, use = 'unknown', 'unknown'
    if re.search('top|front|pri?m?(ary)?', fn):
        side = 'top'
        use = 'copper'

    if re.search('bot(tom)?|back|sec(ondary)?', fn):
        side = 'bottom'
        use = 'copper'

    if re.search('silks?(creen)?|symbol', fn):
        use = 'silk'

    elif re.search('(solder)?paste|metalmask', fn):
        use = 'paste'

    elif re.search('(solder)?(mask|resist)', fn):
        use = 'mask'

    elif re.search('drill|rout?e?', fn):
        use = 'drill'
        side = 'unknown'

        if re.search(r'np(th|lt)?|(non|un)\W*plated|(non|un)\Wgalv', fn):
            side = 'nonplated'

        elif re.search('pth|plated|galv|plt', fn):
            side = 'plated'

    elif (m := re.search(r'(la?y?e?r?|in(ner)?|conduct(or|ive)?)\W*(?P<num>[0-9]+)', fn)):
        use = 'copper'
        side = f'inner_{int(m["num"]):02d}'

    elif re.search('film', fn):
        use = 'copper'

    elif re.search('out(line)?', fn):
        use = 'outline'
        side = 'mechanical'

    elif 'ipc' in fn and '356' in fn:
        use = 'netlist'
        side = 'other'

    elif 'netlist' in fn:
        use = 'netlist'
        side = 'other'

    if side == 'unknown':
        if re.search(r'[^a-z0-9]a', fn):
            side = 'top'
        elif re.search(r'[^a-z0-9]b', fn):
            side = 'bottom'

    return f'{side} {use}'


class LayerStack:

    def __init__(self, graphic_layers, drill_layers, netlist=None, board_name=None, original_path=None, was_zipped=False):
        self.graphic_layers = graphic_layers
        self.drill_layers = drill_layers
        self.board_name = board_name
        self.netlist = netlist
        self.original_path = original_path
        self.was_zipped = was_zipped

    @classmethod
    def open(kls, path, board_name=None, lazy=False):
        if str(path) == '-':
            data_io = io.BytesIO(sys.stdin.buffer.read())
            return kls.from_zip_data(data_io, original_path='<stdin>', board_name=board_name, lazy=lazy)

        path = Path(path)
        if path.is_dir():
            return kls.open_dir(path, board_name=board_name, lazy=lazy)
        elif path.suffix.lower() == '.zip' or is_zipfile(path):
            return kls.open_zip(path, board_name=board_name, lazy=lazy)
        else:
            return kls.from_files([path], board_name=board_name, lazy=lazy)

    @classmethod
    def open_zip(kls, file, original_path=None, board_name=None, lazy=False):
        tmpdir = tempfile.TemporaryDirectory()
        tmp_indir = Path(tmpdir.name) / 'input'
        tmp_indir.mkdir()

        with ZipFile(file) as f:
            f.extractall(path=tmp_indir)

        inst = kls.open_dir(tmp_indir, board_name=board_name, lazy=lazy)
        inst.tmpdir = tmpdir
        inst.original_path = Path(original_path or file)
        inst.was_zipped = True
        return inst

    @classmethod
    def open_dir(kls, directory, board_name=None, lazy=False):

        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError(f'{directory} is not a directory')

        files = [ path for path in directory.glob('**/*') if path.is_file() ]
        return kls.from_files(files, board_name=board_name, lazy=lazy, original_path=directory)
        inst.original_path = directory
        return inst

    @classmethod
    def from_files(kls, files, board_name=None, lazy=False, original_path=None, was_zipped=False):
        generator, filemap = best_match(files)

        if sum(len(files) for files in filemap.values()) < 6:
            warnings.warn('Ambiguous gerber filenames. Trying last-resort autoguesser.')
            generator = None
            filemap = autoguess(files)
            if len(filemap) < 6:
                raise ValueError('Cannot figure out gerber file mapping. Partial map is: ', filemap)

        excellon_settings, external_tools = None, None
        if generator == 'geda':
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
                for file in filemap['excellon params']:
                    if (external_tools := parse_allegro_logfile(file.read_text())):
                        break
                del filemap['excellon params']
            # Ignore if we can't find the param file -- maybe the user has convinced Allegro to actually put this
            # information into a comment, or maybe they have made Allegro just use decimal points like XNC does.

            filemap = autoguess([ f for files in filemap.values() for f in files ])
            if len(filemap) < 6:
                raise SystemError('Cannot figure out gerber file mapping')
            # FIXME use layer metadata from comments and ipc file if available

        elif generator == 'zuken':
            filemap = autoguess([ f for files in filemap.values() for f in files ])
            if len(filemap) < 6:
                raise SystemError('Cannot figure out gerber file mapping')
            # FIXME use layer metadata from comments and ipc file if available

        elif generator == 'altium':
            if 'mechanical outline' in filemap:
                # Use lowest-numbered mechanical layer as outline, ignore others.
                mechs = {}
                for layer in filemap['mechanical outline']:
                    if layer.name.lower().endswith('gko'):
                        filemap['mechanical outline'] = [layer]
                        break

                    if (m := re.match(r'.*\.gm([0-9]+)', layer.name, re.IGNORECASE)):
                        mechs[int(m[1])] = layer
                    else:
                        break
                else:
                    filemap['mechanical outline'] = [sorted(mechs.items(), key=lambda x: x[0])[0][1]]

        else:
            excellon_settings = None

        ambiguous = [ f'{key} ({", ".join(x.name for x in value)})' for key, value in filemap.items() if len(value) > 1 and not 'drill' in key ]
        if ambiguous:
            raise SystemError(f'Ambiguous layer names: {", ".join(ambiguous)}')

        drill_layers = []
        netlist = None
        layers = {} # { tuple(key.split()): None for key in STANDARD_LAYERS }
        for key, paths in filemap.items():
            if len(paths) > 1 and not 'drill' in key:
                raise ValueError(f'Multiple matching files found for {key} layer: {", ".join(value)}')

            for path in paths:
                id_result = identify_file(path.read_text())

                if 'netlist' in key:
                    layer = LazyCamFile(Netlist, path)

                elif ('outline' in key or 'drill' in key) and id_result != 'gerber':
                    if id_result is None:
                        # Since e.g. altium uses ".txt" as the extension for its drill files, we have to assume the
                        # current file might not be a drill file after all.
                        continue

                    if 'nonplated' in key:
                        plated = False
                    elif 'plated' in key:
                        plated = True
                    else:
                        plated = None
                    layer = LazyCamFile(ExcellonFile, path, plated=plated, settings=excellon_settings, external_tools=external_tools)
                else:

                    layer = LazyCamFile(GerberFile, path)

                if not lazy:
                    layer = layer.instance

                if key == 'mechanical outline':
                    layers['mechanical', 'outline'] = layer

                elif 'drill' in key:
                    drill_layers.append(layer)

                elif 'netlist' in key:
                    if netlist:
                        warnings.warn(f'Found multiple netlist files, using only first one. Have: {netlist.original_path.name}, got {path.name}')
                    else:
                        netlist = layer

                else:
                    side, _, use = key.partition(' ')
                    layers[(side, use)] = layer

                if not lazy:
                    hints = set(layer.generator_hints) | { generator }
                    if len(hints) > 1:
                        warnings.warn('File identification returned ambiguous results. Please raise an issue on the '
                                'gerbonara tracker and if possible please provide these input files for reference.')

        if not board_name:
            board_name = common_prefix([l.original_path.name for l in layers.values() if l is not None])
            board_name = re.sub(r'^\W+', '', board_name)
            board_name = re.sub(r'\W+$', '', board_name)

        return kls(layers, drill_layers, netlist, board_name=board_name,
                original_path=original_path, was_zipped=was_zipped)

    def save_to_zipfile(self, path, naming_scheme={}, overwrite_existing=True, prefix=''):
        if path.is_file():
            if overwrite_existing:
                path.unlink()
            else:
                raise ValueError('output zip file already exists and overwrite_existing is False')

        with ZipFile(path, 'w') as le_zip:
            for path, layer in self._save_files_iter(naming_scheme=naming_scheme):
                with le_zip.open(prefix + str(path), 'w') as out:
                    out.write(layer.instance.write_to_bytes())

    def save_to_directory(self, path, naming_scheme={}, overwrite_existing=True):
        outdir = Path(path)
        outdir.mkdir(parents=True, exist_ok=overwrite_existing)

        for path, layer in self._save_files_iter(naming_scheme=naming_scheme):
            out = outdir / path
            if out.exists() and not overwrite_existing:
                raise SystemError(f'Path exists but overwrite_existing is False: {out}')
            layer.instance.save(out)

    def _save_files_iter(self, naming_scheme={}):
        def get_name(layer_type, layer):
            nonlocal naming_scheme

            if (m := re.match('inner_([0-9]*) copper', layer_type)):
                layer_type = 'inner copper'
                num = int(m[1])
            else:
                num = None

            if layer_type in naming_scheme:
                path = naming_scheme[layer_type].format(layer_number=num, board_name=self.board_name)
            elif layer.original_path.name:
                path = layer.original_path.name
            else:
                path = f'{self.board_name}-{layer_type.replace(" ", "_")}.gbr'

            return path

        for (side, use), layer in self.graphic_layers.items():
            yield get_name(f'{side} {use}', layer), layer

        #self.normalize_drill_layers()

        if self.drill_pth is not None:
            yield get_name('plated drill', self.drill_pth), self.drill_pth
        if self.drill_npth is not None:
            yield get_name('nonplated drill', self.drill_npth), self.drill_npth
        if self.drill_unknown is not None:
            yield get_name('unknown drill', self.drill_unknown), self.drill_unknown

        if self.netlist:
            yield get_name('other netlist', self.netlist), self.netlist

    def __str__(self):
        names = [ f'{side} {use}' for side, use in self.graphic_layers ]
        return f'<LayerStack {self.board_name} [{", ".join(names)}] and {len(self.drill_layers)} drill layers>'

    def __repr__(self):
        return str(self)

    def to_svg(self, margin=0, arg_unit=MM, svg_unit=MM, force_bounds=None, tag=Tag, page_bg="white"):
        if force_bounds:
            bounds = svg_unit.convert_bounds_from(arg_unit, force_bounds)
        else:
            bounds = self.bounding_box(svg_unit, default=((0, 0), (0, 0)))
        
        tags = []
        for (side, use), layer in self.graphic_layers.items():
            tags.append(tag('g', list(layer.svg_objects(svg_unit=svg_unit, fg='black', bg="white", tag=Tag)),
                id=f'l-{side}-{use}'))

        for i, layer in enumerate(self.drill_layers):
            tags.append(tag('g', list(layer.svg_objects(svg_unit=svg_unit, fg='black', bg="white", tag=Tag)),
                id=f'l-drill-{i}'))

        return setup_svg(tags, bounds, margin=margin, arg_unit=arg_unit, svg_unit=svg_unit, pagecolor=page_bg, tag=tag)

    def to_pretty_svg(self, side='top', margin=0, arg_unit=MM, svg_unit=MM, force_bounds=None, tag=Tag, inkscape=False, colors=None):
        if colors is None:
            colors = DEFAULT_COLORS

        colors_alpha = {}
        for layer, color in colors.items():
            if isinstance(color, str):
                if re.match(r'#[0-9a-fA-F]{8}', color):
                    colors_alpha[layer] = (color[:-2], int(color[-2:], 16)/255)
                else:
                    colors_alpha[layer] = (color, 1)
            else:
                colors_alpha[layer] = color

        if force_bounds:
            bounds = svg_unit.convert_bounds_from(arg_unit, force_bounds)
        else:
            bounds = self.board_bounds(unit=svg_unit, default=((0, 0), (0, 0)))
        
        filter_defs = []

        for layer, (color, alpha) in colors_alpha.items():
            filter_defs.append(textwrap.dedent(f'''
                <filter id="f-{layer}">
                <feFlood result="flood-black" flood-color="black" flood-opacity="1"/>
                <feFlood result="flood-green" flood-color="{color}"/>
                <feBlend in="SourceGraphic" in2="flood-black" result="overlay" mode="normal"/>
                <feBlend in="overlay" in2="flood-green" result="colored" mode="multiply"/>
                <feColorMatrix in="overlay" type="matrix" result="alphaOut" values="0 0 0 0 0
                0 0 0 0 0
                0 0 0 0 0
                {alpha} 0 0 0 0"/>
                <feComposite in="colored" in2="alphaOut" operator="in"/>
                </filter>'''.strip()))

        inkscape_attrs = lambda label: dict(inkscape__groupmode='layer', inkscape__label=label) if inkscape else {}
        
        layers = []
        for use in ['copper', 'mask', 'silk', 'paste']:
            if (side, use) not in self:
                warnings.warn(f'Layer "{side} {use}" not found. Found layers: {", ".join(side + " " + use for side, use in self.graphic_layers)}')
                continue

            layer = self[(side, use)]
            fg, bg = ('white', 'black') if use != 'mask' else ('black', 'white')
            objects = list(layer.instance.svg_objects(svg_unit=svg_unit, fg=fg, bg=bg, tag=Tag))
            if use == 'mask':
                objects.insert(0, tag('path', id='outline-path', d=self.outline_svg_d(unit=svg_unit), style='fill:white'))
            layers.append(tag('g', objects, id=f'l-{side}-{use}', filter=f'url(#f-{use})', **inkscape_attrs(f'{side} {use}')))

        for i, layer in enumerate(self.drill_layers):
            layers.append(tag('g', list(layer.instance.svg_objects(svg_unit=svg_unit, fg='white', bg='black', tag=Tag)),
                id=f'l-drill-{i}', filter=f'url(#f-drill)', **inkscape_attrs(f'drill-{i}')))

        if self.outline:
            layers.append(tag('g', list(self.outline.instance.svg_objects(svg_unit=svg_unit, fg='white', bg='black', tag=Tag)),
                id=f'l-outline-{i}', **inkscape_attrs(f'outline-{i}')))

        layer_group = tag('g', layers, transform=f'translate(0 {bounds[0][1] + bounds[1][1]}) scale(1 -1)')
        tags = [tag('defs', filter_defs), layer_group]
        return setup_svg(tags, bounds, margin=margin, arg_unit=arg_unit, svg_unit=svg_unit, pagecolor="white", tag=tag, inkscape=inkscape)

    def bounding_box(self, unit=MM, default=None):
        return sum_bounds(( layer.bounding_box(unit, default=default)
            for layer in itertools.chain(self.graphic_layers.values(), self.drill_layers) ), default=default)


    def board_bounds(self, unit=MM, default=None):
        if self.outline:
            return self.outline.instance.bounding_box(unit=unit, default=default)
        else:
            return self.bounding_box(unit=unit, default=default)

    def merge_drill_layers(self):
        target = ExcellonFile(comments=['Drill files merged by gerbonara'])

        for layer in self.drill_layers:
            if isinstance(layer, GerberFile):
                layer = layer.to_excellon()

            target.merge(layer)

        self.drill_pth = self.drill_npth = None
        self.drill_unknown = target

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
        if self.drill_pth or self.drill_npth or self.drill_unknown:
            return [self.drill_pth, self.drill_npth, self.drill_unknown]
        return []

    @drill_layers.setter
    def drill_layers(self, value):
        self._drill_layers = value
        self.drill_pth = self.drill_npth = self.drill_unknown = None

    def __len__(self):
        return len(self.layers)

    def get(self, index, default=None):
        if self.contains(key):
            return self[key]
        else:
            return default

    def __contains__(self, index):
        if isinstance(index, str):
            side, _, use = index.partition(' ')
            return (side, use) in self.layers

        elif isinstance(index, tuple):
            return index in self.graphic_layers

        return index < len(self.copper_layers)

    def __getitem__(self, index):
        if isinstance(index, str):
            side, _, use = index.partition(' ')
            return self.graphic_layers[(side, use)]

        elif isinstance(index, tuple):
            return self.graphic_layers[index]

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
        return { key: self[key] for key in ('top copper', 'top mask', 'top silk', 'top paste', 'mechanical outline') }

    @property
    def bottom_side(self):
        return { key: self[key] for key in ('bottom copper', 'bottom mask', 'bottom silk', 'bottom paste', 'mechanical outline') }

    @property
    def outline(self):
        return self['mechanical outline']

    def outline_svg_d(self, tol=0.01, unit=MM):
        chains = self.outline_polygons(tol, unit)
        polys = []
        for chain in chains:
            outline = [ (chain[0].x1, chain[0].y1), *((elem.x2, elem.y2) for elem in chain) ]
            arcs = [ (elem.clockwise, (elem.cx, elem.cy)) if isinstance(elem, gp.Arc) else None for elem in chain ]
            poly = gp.ArcPoly(outline=outline, arc_centers=arcs)
            polys.append(' '.join(poly.path_d()) + ' Z')
        return ' '.join(polys)

    def outline_polygons(self, tol=0.01, unit=MM):
        polygons = []
        lines = [ obj.as_primitive(unit) for obj in self.outline.instance.objects if isinstance(obj, (go.Line, go.Arc)) ]

        by_x = sorted([ (obj.x1, obj) for obj in lines ] + [ (obj.x2, obj) for obj in lines ], key=lambda x: x[0])
        dist_sq = lambda x1, y1, x2, y2: (x2-x1)**2 + (y2-y1)**2

        joins = {}
        for cur in lines:
            for i, (x, y) in enumerate([(cur.x1, cur.y1), (cur.x2, cur.y2)]):
                x_left  = bisect.bisect_left (by_x, x, key=lambda elem: elem[0] + tol)
                x_right = bisect.bisect_right(by_x, x, key=lambda elem: elem[0] - tol)
                selected = { elem for elem_x, elem in by_x[x_left:x_right] if elem != cur }

                if not selected:
                    continue # loose end

                nearest = sorted(selected, key=lambda elem: min(dist_sq(elem.x1, elem.y1, x, y), dist_sq(elem.x2, elem.y2, x, y)))[0]

                d1, d2 = dist_sq(nearest.x1, nearest.y1, x, y), dist_sq(nearest.x2, nearest.y2, x, y)
                j = 0 if d1 < d2 else 1

                if (nearest, j) in joins and joins[(nearest, j)] != (cur, i):
                    raise ValueError(f'Error: three-way intersection of {(nearest, j)}; {(cur, i)}; and {joins[(nearest, j)]}')

                if (cur, i) in joins and joins[(cur, i)] != (nearest, j):
                    raise ValueError(f'Error: three-way intersection of {(nearest, j)}; {(cur, i)}; and {joins[(nearest, j)]}')

                joins[(cur, i)] = (nearest, j)
                joins[(nearest, j)] = (cur, i)

        def flip_if(obj, i):
            if i:
                c = copy.copy(obj)
                c.flip()
                return c
            else:
                return obj

        while joins:
            (first, i), (cur, j) = joins.popitem()
            del joins[(cur, j)]
            l = [ flip_if(first, not i), flip_if(cur, j) ]
            while cur != first and (cur, not j) in joins:
                cur, j = joins.pop((cur, not j))
                del joins[(cur, j)]
                l.append(flip_if(cur, j))
            yield l


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

        self._merge_layer('mechanical outline', other['mechanical outline'])

        self.normalize_drill_layers()
        other.normalize_drill_layers()

        self.drill_pth.merge(other.drill_pth)
        self.drill_npth.merge(other.drill_npth)
        self.drill_unknown.merge(other.drill_unknown)
        self.netlist.merge(other.netlist)

