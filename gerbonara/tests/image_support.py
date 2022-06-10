#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
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
# Based on https://github.com/tracespace/tracespace
#

import subprocess
from pathlib import Path
import tempfile
import textwrap
import os
from functools import total_ordering
import shutil
import bs4
from contextlib import contextmanager
import hashlib

import numpy as np
from PIL import Image

cachedir = Path(__file__).parent / 'image_cache'
cachedir.mkdir(exist_ok=True)

@total_ordering
class ImageDifference:
    def __init__(self, value, histogram):
        self.value = value
        self.histogram = histogram

    def __float__(self):
        return float(self.value)

    def __eq__(self, other):
        return float(self) == float(other)

    def __lt__(self, other):
        return float(self) < float(other)

    def __str__(self):
        return str(float(self))

@total_ordering
class Histogram:
    def __init__(self, value, size):
        self.value, self.size = value, size

    def __eq__(self, other):
        other = np.array(other)
        other[other == None] = self.value[other == None]
        return (self.value == other).all()

    def __lt__(self, other):
        other = np.array(other)
        other[other == None] = self.value[other == None]
        return (self.value <= other).all()

    def __getitem__(self, index):
        return self.value[index]

    def __str__(self):
        return f'{list(self.value)} size={self.size}'


def run_cargo_cmd(cmd, args, **kwargs):
    if cmd.upper() in os.environ:
        return subprocess.run([os.environ[cmd.upper()], *args], **kwargs)

    try:
        return subprocess.run([cmd, *args], **kwargs)

    except FileNotFoundError:
        return subprocess.run([str(Path.home() / '.cargo' / 'bin' / cmd), *args], **kwargs)

def svg_to_png(in_svg, out_png, dpi=100, bg=None):
    params = f'{dpi}{bg}'.encode()
    digest = hashlib.blake2b(Path(in_svg).read_bytes() + params).hexdigest()
    cachefile = cachedir / f'{digest}.png'

    if not cachefile.is_file():
        bg = 'black' if bg is None else bg
        run_cargo_cmd('resvg', ['--background', bg, '--dpi', str(dpi), in_svg, cachefile], check=True, stdout=subprocess.DEVNULL)

    shutil.copy(cachefile, out_png)

to_gerbv_svg_units = lambda val, unit='mm': val*72 if unit == 'inch' else val/25.4*72

def gerbv_export(in_gbr, out_svg, export_format='svg', origin=(0, 0), size=(6, 6), fg='#ffffff', bg='#000000', override_unit_spec=None):
    params = f'{origin}{size}{fg}{bg}'.encode()
    digest = hashlib.blake2b(Path(in_gbr).read_bytes() + params).hexdigest()
    cachefile = cachedir / f'{digest}.svg'

    if not cachefile.is_file():
        # NOTE: gerbv seems to always export 'clear' polarity apertures as white, irrespective of --foreground, --background
        # and project file color settings.
        # TODO: File issue upstream.
        with tempfile.NamedTemporaryFile('w') as f:
            if override_unit_spec:
                units, zeros, digits = override_unit_spec
                print(f'{Path(in_gbr).name}: overriding excellon unit spec to {units=} {zeros=} {digits=}')
                units = 0 if units == 'inch' else 1
                zeros = {None: 0, 'leading': 1, 'trailing': 2}[zeros]
                unit_spec = textwrap.dedent(f'''(cons 'attribs (list
                        (list 'autodetect 'Boolean 0)
                        (list 'zero_suppression 'Enum {zeros})
                        (list 'units 'Enum {units})
                        (list 'digits 'Integer {digits})
                    ))''')
            else:
                unit_spec = ''

            r, g, b = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:], 16)
            color = f"(cons 'color #({r*257} {g*257} {b*257}))"
            f.write(f'''(gerbv-file-version! "2.0A")(define-layer! 0 (cons 'filename "{in_gbr}"){unit_spec}{color})''')
            f.flush()
            if override_unit_spec:
                shutil.copy(f.name, '/tmp/foo.gbv')

            x, y = origin
            w, h = size
            cmd = ['gerbv', '-x', export_format,
                '--border=0',
                f'--origin={x:.6f}x{y:.6f}', f'--window_inch={w:.6f}x{h:.6f}',
                f'--background={bg}',
                f'--foreground={fg}',
                '-o', str(cachefile), '-p', f.name]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.copy(cachefile, out_svg)

@contextmanager
def svg_soup(filename):
    with open(filename, 'r') as f:
        soup = bs4.BeautifulSoup(f.read(), 'xml')

    yield soup

    with open(filename, 'w') as f:
        f.write(str(soup))

def cleanup_gerbv_svg(soup):
    soup.svg['width'] = f'{float(soup.svg["width"])/72*25.4:.4f}mm'
    soup.svg['height'] = f'{float(soup.svg["height"])/72*25.4:.4f}mm'
    for group in soup.find_all('g'):
        # gerbv uses Cairo's SVG canvas. Cairo's SVG canvas is kind of broken. It has no support for unit
        # handling at all, which means the output files just end up being in pixels at 72 dpi. Further, it
        # seems gerbv's aperture macro rendering interacts poorly with Cairo's SVG export. gerbv renders
        # aperture macros into a new surface, which for some reason gets clipped by Cairo to the given
        # canvas size. This is just wrong, so we just nuke the clip path from these SVG groups here.
        #
        # Apart from being graphically broken, this additionally causes very bad rendering performance.
        del group['clip-path']

def gerber_difference(reference, actual, diff_out=None, svg_transform=None, size=(10,10), ref_unit_spec=None):
    with tempfile.NamedTemporaryFile(suffix='.svg') as act_svg,\
        tempfile.NamedTemporaryFile(suffix='.svg') as ref_svg:

        gerbv_export(reference, ref_svg.name, size=size, export_format='svg', override_unit_spec=ref_unit_spec)
        gerbv_export(actual, act_svg.name, size=size, export_format='svg')

        with svg_soup(ref_svg.name) as soup:
            if svg_transform is not None:
                svg = soup.svg
                children = list(svg.children)
                g = soup.new_tag('g', attrs={'transform': svg_transform})
                for c in children:
                    g.append(c.extract())
                svg.append(g)

            cleanup_gerbv_svg(soup)

        with svg_soup(act_svg.name) as soup:
            cleanup_gerbv_svg(soup)

        return svg_difference(ref_svg.name, act_svg.name, diff_out=diff_out)

def gerber_difference_merge(ref1, ref2, actual, diff_out=None, composite_out=None, svg_transform1=None, svg_transform2=None, size=(10,10)):
    with tempfile.NamedTemporaryFile(suffix='.svg') as act_svg,\
        tempfile.NamedTemporaryFile(suffix='.svg') as ref1_svg,\
        tempfile.NamedTemporaryFile(suffix='.svg') as ref2_svg:

        gerbv_export(ref1, ref1_svg.name, size=size, export_format='svg')
        gerbv_export(ref2, ref2_svg.name, size=size, export_format='svg')
        gerbv_export(actual, act_svg.name, size=size, export_format='svg')
        for var in ['ref1_svg', 'ref2_svg', 'act_svg']:
            print(f'=== {var} ===')
            print(Path(locals()[var].name).read_text().splitlines()[1])

        with svg_soup(ref1_svg.name) as soup1:
            if svg_transform1 is not None:
                svg = soup1.svg
                children = list(svg.children)
                g = soup1.new_tag('g', attrs={'transform': svg_transform1})
                for c in children:
                    g.append(c.extract())
                svg.append(g)
            cleanup_gerbv_svg(soup1)

            with svg_soup(ref2_svg.name) as soup2:
                if svg_transform2 is not None:
                    svg = soup2.svg
                    children = list(svg.children)
                    g = soup2.new_tag('g', attrs={'transform': svg_transform2})
                    for c in children:
                        g.append(c.extract())
                    svg.append(g)
                cleanup_gerbv_svg(soup2)

                defs1 = soup1.find('defs')
                if not defs1:
                    defs1 = soup1.new_tag('defs')
                    soup1.find('svg').insert(0, defs1)

                defs2 = soup2.find('defs')
                if defs2:
                    defs2 = defs2.extract()
                    # explicitly convert .contents into list here and below because else bs4 stumbles over itself
                    # iterating because we modify the tree in the loop body.
                    for c in list(defs2.contents):
                        if hasattr(c, 'attrs'):
                            c['id'] = 'gn-merge-b-' + c.attrs.get('id', str(id(c)))
                        defs1.append(c)

                for use in soup2.find_all('use', recursive=True):
                    if (href := use.get('xlink:href', '')).startswith('#'):
                        use['xlink:href'] = f'#gn-merge-b-{href[1:]}'

                svg1 = soup1.find('svg')
                for c in list(soup2.find('svg').contents):
                    if hasattr(c, 'attrs'):
                        c['id'] = 'gn-merge-b-' + c.attrs.get('id', str(id(c)))
                    svg1.append(c)

        if composite_out:
            shutil.copyfile(ref1_svg.name, composite_out)

        with svg_soup(act_svg.name) as soup:
            cleanup_gerbv_svg(soup)

        return svg_difference(ref1_svg.name, act_svg.name, diff_out=diff_out)

def svg_difference(reference, actual, diff_out=None, background=None):
    with tempfile.NamedTemporaryFile(suffix='-ref.png') as ref_png,\
        tempfile.NamedTemporaryFile(suffix='-act.png') as act_png:

        svg_to_png(reference, ref_png.name, bg=background)
        svg_to_png(actual, act_png.name, bg=background)

        return image_difference(ref_png.name, act_png.name, diff_out=diff_out)

def image_difference(reference, actual, diff_out=None):
    ref = np.array(Image.open(reference)).astype(float)
    out = np.array(Image.open(actual)).astype(float)

    ref, out = ref.mean(axis=2), out.mean(axis=2) # convert to grayscale
    # TODO blur images here before comparison to mitigate aliasing issue
    delta = np.abs(out - ref).astype(float) / 255
    if diff_out:
        Image.fromarray((delta*255).astype(np.uint8), mode='L').save(diff_out)

    hist, _bins = np.histogram(delta, bins=10, range=(0, 1))
    return (ImageDifference(delta.mean(), hist),
            ImageDifference(delta.max(), hist),
            Histogram(hist, out.size))


