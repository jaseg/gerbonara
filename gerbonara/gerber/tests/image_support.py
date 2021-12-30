import subprocess
from pathlib import Path
import tempfile
import os
from functools import total_ordering
import shutil
import bs4
from contextlib import contextmanager

import numpy as np
from PIL import Image

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

def svg_to_png(in_svg, out_png):
    run_cargo_cmd('resvg', ['--dpi', '100', in_svg, out_png], check=True, stdout=subprocess.DEVNULL)

def gbr_to_svg(in_gbr, out_svg, origin=(0, 0), size=(6, 6)):
    x, y = origin
    w, h = size
    cmd = ['gerbv', '-x', 'svg',
        '--border=0',
        f'--origin={x:.6f}x{y:.6f}', f'--window_inch={w:.6f}x{h:.6f}',
        '--foreground=#ffffff',
        '-o', str(out_svg), str(in_gbr)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

@contextmanager
def svg_soup(filename):
    with open(filename, 'r') as f:
        soup = bs4.BeautifulSoup(f.read(), 'xml')

    yield soup

    with open(filename, 'w') as f:
        f.write(str(soup))

def cleanup_clips(soup):
    for group in soup.find_all('g'):
        # gerbv uses Cairo's SVG canvas. Cairo's SVG canvas is kind of broken. It has no support for unit
        # handling at all, which means the output files just end up being in pixels at 72 dpi. Further, it
        # seems gerbv's aperture macro rendering interacts poorly with Cairo's SVG export. gerbv renders
        # aperture macros into a new surface, which for some reason gets clipped by Cairo to the given
        # canvas size. This is just wrong, so we just nuke the clip path from these SVG groups here.
        #
        # Apart from being graphically broken, this additionally causes very bad rendering performance.
        del group['clip-path'] # remove broken clip

def gerber_difference(reference, actual, diff_out=None, svg_transform=None, size=(10,10)):
    with tempfile.NamedTemporaryFile(suffix='.svg') as act_svg,\
        tempfile.NamedTemporaryFile(suffix='.svg') as ref_svg:

        gbr_to_svg(reference, ref_svg.name, size=size)
        gbr_to_svg(actual, act_svg.name, size=size)

        with svg_soup(ref_svg.name) as soup:
            if svg_transform is not None:
                soup.find('g', attrs={'id': 'surface1'})['transform'] = svg_transform
            cleanup_clips(soup)

        with svg_soup(act_svg.name) as soup:
            cleanup_clips(soup)

        # FIXME DEBUG
        shutil.copyfile(act_svg.name, '/tmp/test-act.svg')
        shutil.copyfile(ref_svg.name, '/tmp/test-ref.svg')

        return svg_difference(ref_svg.name, act_svg.name, diff_out=diff_out)

def svg_difference(reference, actual, diff_out=None):
    with tempfile.NamedTemporaryFile(suffix='-ref.png') as ref_png,\
        tempfile.NamedTemporaryFile(suffix='-act.png') as act_png:

        svg_to_png(reference, ref_png.name)
        svg_to_png(actual, act_png.name)

        return image_difference(ref_png.name, act_png.name, diff_out=diff_out)

def image_difference(reference, actual, diff_out=None):
    ref = np.array(Image.open(reference)).astype(float)
    out = np.array(Image.open(actual)).astype(float)

    ref, out = ref.mean(axis=2), out.mean(axis=2) # convert to grayscale
    delta = np.abs(out - ref).astype(float) / 255
    if diff_out:
        Image.fromarray((delta*255).astype(np.uint8), mode='L').save(diff_out)

    hist, _bins = np.histogram(delta, bins=10, range=(0, 1))
    return (ImageDifference(delta.mean(), hist),
            ImageDifference(delta.max(), hist),
            Histogram(hist, out.size))


