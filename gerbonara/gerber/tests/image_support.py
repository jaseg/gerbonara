import subprocess
from pathlib import Path
import tempfile
import os
from functools import total_ordering

import numpy as np
from PIL import Image

class ImageDifference:
    def __init__(self, value):
        self.value = value

    def __float__(self):
        return float(self.value)

    def __eq__(self, other):
        return float(self) == float(other)

    def __lt__(self, other):
        return float(self) < float(other)

    def __str__(self):
        return str(float(self))


def run_cargo_cmd(cmd, args, **kwargs):
    if cmd.upper() in os.environ:
        return subprocess.run([os.environ[cmd.upper()], *args], **kwargs)

    try:
        return subprocess.run([cmd, *args], **kwargs)

    except FileNotFoundError:
        return subprocess.run([str(Path.home() / '.cargo' / 'bin' / cmd), *args], **kwargs)

def svg_to_png(in_svg, out_png):
    run_cargo_cmd('resvg', [in_svg, out_png], check=True, stdout=subprocess.DEVNULL)

def gbr_to_svg(in_gbr, out_svg, origin=(0, 0), size=(10, 10)):
    x, y = origin
    w, h = size
    cmd = ['gerbv', '-x', 'svg',
        '--border=0',
        f'--origin={x:.6f}x{y:.6f}', f'--window_inch={w:.6f}x{h:.6f}',
        '--foreground=#ffffff',
        '-o', str(out_svg), str(in_gbr)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def gerber_difference(reference, actual, diff_out=None):
    with tempfile.NamedTemporaryFile(suffix='.svg') as act_svg,\
        tempfile.NamedTemporaryFile(suffix='.svg') as ref_svg:

        gbr_to_svg(reference, ref_svg.name)
        gbr_to_svg(actual, act_svg.name)

        return svg_difference(ref_svg.name, act_svg.name, diff_out=diff_out)

def svg_difference(reference, actual, diff_out=None):
    with tempfile.NamedTemporaryFile(suffix='.png') as ref_png,\
        tempfile.NamedTemporaryFile(suffix='.png') as act_png:

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
    return ImageDifference(delta.mean()), ImageDifference(delta.max())


