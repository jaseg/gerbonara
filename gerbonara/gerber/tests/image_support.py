import subprocess
from pathlib import Path
import tempfile

import numpy as np

class ImageDifference(float):
    def __init__(self, value, ref_path, out_path):
        super().__init__(value)
        self.ref_path, self.out_path = ref_path, out_path

def run_cargo_cmd(cmd, args, **kwargs):
    if cmd.upper() in os.environ:
        return subprocess.run([os.environ[cmd.upper()], *args], **kwargs)

    try:
        return subprocess.run([cmd, *args], **kwargs)

    except FileNotFoundError:
        return subprocess.run([str(Path.home() / '.cargo' / 'bin' / cmd), *args], **kwargs)

def svg_to_png(in_svg, out_png):
    run_cargo_cmd('resvg', [in_svg, out_png], check=True, stdout=subprocess.DEVNULL)

def gbr_to_svg(in_gbr, out_svg):
    cmd = ['gerbv', '-x', 'svg',
        '--border=0',
        #f'--origin={origin_x:.6f}x{origin_y:.6f}', f'--window_inch={width:.6f}x{height:.6f}',
        '--foreground=#ffffff',
        '-o', str(out_svg), str(in_gbr)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def gerber_difference(reference, actual):
    with tempfile.NamedTemporaryFile(suffix='.svg') as out_svg,\
        tempfile.NamedTemporaryFile(suffix='.svg') as ref_svg:

        gbr_to_svg(reference, ref_svg.name)
        gbr_to_svg(actual, act_svg.name)

        diff = svg_difference(ref_svg.name, act_svg.name)
        diff.ref_path, diff.act_path = reference, actual
        return diff

def svg_difference(reference, actual):
    with tempfile.NamedTemporaryFile(suffix='.png') as ref_png,\
        tempfile.NamedTemporaryFile(suffix='.png') as act_png:

        svg_to_png(reference, ref_png.name)
        svg_to_png(actual, act_png.name)

        diff = image_difference(ref_png.name, act_png.name)
        diff.ref_path, diff.act_path = reference, actual
        return diff

def image_difference(reference, actual):
    ref = np.array(Image.open(reference)).astype(float)
    out = np.array(Image.open(actual)).astype(float)

    ref, out = ref.mean(axis=2), out.mean(axis=2) # convert to grayscale
    delta = np.abs(out - ref).astype(float) / 255
    return ImageDifference(delta.mean(), ref, out)


