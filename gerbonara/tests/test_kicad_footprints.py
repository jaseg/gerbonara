
from itertools import zip_longest
import subprocess
import re

from .utils import tmpfile, print_on_error
from .image_support import kicad_fp_export, svg_difference, svg_soup, svg_to_png, run_cargo_cmd

from .. import graphic_objects as go
from ..utils import MM
from ..layers import LayerStack
from ..cad.kicad.sexp import build_sexp
from ..cad.kicad.sexp_mapper import sexp
from ..cad.kicad.footprints import Footprint, FootprintInstance, LAYER_MAP_G2K
from ..cad.kicad.layer_colors import KICAD_LAYER_COLORS, KICAD_DRILL_COLORS


def test_parse(kicad_mod_file):
    Footprint.open_mod(kicad_mod_file)


def test_round_trip(kicad_mod_file):
    print('========== Stage 1 load ==========')
    orig_fp = Footprint.open_mod(kicad_mod_file)
    print('========== Stage 1 save ==========')
    stage1_sexp = build_sexp(orig_fp.sexp())
    with open('/tmp/foo.sexp', 'w') as f:
        f.write(stage1_sexp)

    print('========== Stage 2 load ==========')
    reparsed_fp = Footprint.parse(stage1_sexp)
    print('========== Stage 2 save ==========')
    stage2_sexp = build_sexp(reparsed_fp.sexp())
    print('========== Checks ==========')

    for stage1, stage2 in zip_longest(stage1_sexp.splitlines(), stage2_sexp.splitlines()):
        assert stage1 == stage2

    return

    original = re.sub(r'\(', '\n(', re.sub(r'\s+', ' ', kicad_mod_file.read_text()))
    original = re.sub(r'\) \)', '))', original)
    original = re.sub(r'\) \)', '))', original)
    original = re.sub(r'\) \)', '))', original)
    original = re.sub(r'\) \)', '))', original)
    stage1 = re.sub(r'\(', '\n(', re.sub(r'\s+', ' ', stage1_sexp))
    for original, stage1 in zip_longest(original.splitlines(), stage1.splitlines()):
        if original.startswith('(version'):
            continue

        original, stage1 = original.strip(), stage1.strip()
        if original != stage1:
            if any(original.startswith(f'({foo}') for foo in ['arc', 'circle', 'rectangle', 'polyline', 'text']):
                # These files have symbols with graphic primitives in non-standard order
                return

            if original.startswith('(symbol') and stage1.startswith('(symbol'):
                # Re-export can change symbol order. This is ok.
                return

            if original.startswith('(at') and stage1.startswith('(at'):
                # There is some disagreement as to whether rotation angles are ints or floats, and the spec doesn't say.
                return

            assert original == stage1
    

def _parse_path_d(path):
    path_d = path.get('d')
    if not path_d:
        return

    for match in re.finditer(r'[ML] ?([0-9.]+) *,? *([0-9.]+)', path_d):
        x, y = match.groups()
        x, y = float(x), float(y)
        yield x, y

def test_render(kicad_mod_file, tmpfile, print_on_error):
    # Hide text and remove text from KiCad's renders. Our text rendering is alright, but KiCad has some weird issue
    # where it seems to mis-calculate the bounding box of stroke font text, leading to a wonky viewport not matching the
    # actual content, and text that is slightly off from where it should be. The difference is only a few hundred
    # micrometers, but it's enough to really throw off our error calculation, so we just ignore text.
    fp = FootprintInstance(0, 0, sexp=Footprint.open_mod(kicad_mod_file), hide_text=True)
    stack = LayerStack(courtyard=True, fabrication=True)
    fp.render(stack)
    color_map = {gn_id: KICAD_LAYER_COLORS[kicad_id] for gn_id, kicad_id in LAYER_MAP_G2K.items()}
    color_map[('drill', 'pth')] = (255, 255, 255, 1)
    color_map[('drill', 'npth')] = (255, 255, 255, 1)
    color_map = {key: (f'#{r:02x}{g:02x}{b:02x}', str(a)) for key, (r, g, b, a) in color_map.items()}

    margin = 10 # mm

    layer = stack[('top', 'courtyard')]
    points = []
    for obj in layer.objects:
        if isinstance(obj, (go.Line, go.Arc)):
            points.append((obj.x1, obj.y1))
            points.append((obj.x2, obj.y2))

    if not points:
        print('Footprint has no paths on courtyard layer')
        return

    min_x = min(x for x, y in points)
    min_y = min(y for x, y in points)
    max_x = max(x for x, y in points)
    max_y = max(y for x, y in points)
    w, h = max_x-min_x, max_y-min_y
    bounds = ((min_x, min_y), (max_x, max_y))
    print_on_error('Gerbonara bounds:', bounds, f'w={w:.6f}', f'h={h:.6f}')

    out_svg = tmpfile('Output', '.svg')
    out_svg.write_text(str(stack.to_svg(color_map=color_map, force_bounds=bounds, margin=margin)))

    print_on_error('Input footprint:', kicad_mod_file)
    ref_svg = tmpfile('Reference render', '.svg')
    kicad_fp_export(kicad_mod_file, ref_svg)

    # KiCad's bounding box calculation for SVG output looks broken, and the resulting files have viewports that are too
    # large. We align our output and KiCad's output using the footprint's courtyard layer.
    points = []
    with svg_soup(ref_svg) as soup:
        for group in soup.find_all('g'):
            style = group.get('style', '').lower().replace(' ', '')
            if 'fill:#ff26e2' not in style or 'stroke:#ff26e2' not in style:
                continue

            # This group contains courtyard layer items.
            for path in group.find_all('path'):
                points += _parse_path_d(path)

        if not points:
            print('Footprint has no paths on courtyard layer')
            return

        min_x = min(x for x, y in points)
        min_y = min(y for x, y in points)
        max_x = max(x for x, y in points)
        max_y = max(y for x, y in points)
        print_on_error('KiCad bounds:', ((min_x, min_y), (max_x, max_y)), f'w={max_x-min_x:.6f}', f'h={max_y-min_y:.6f}')
        min_x -= margin
        min_y -= margin
        max_x += margin
        max_y += margin
        w, h = max_x-min_x, max_y-min_y

        root = soup.find('svg')
        root_w = root['width'] = f'{w:.6f}mm'
        root_h = root['height'] = f'{h:.6f}mm'
        root['viewBox'] = f'{min_x:.6f} {min_y:.6f} {w:.6f} {h:.6f}'

        for group in soup.find_all('g', attrs={'class': 'stroked-text'}):
            group.decompose()

    # Currently, there is a bug in resvg leading to mis-rendering. On the file below from the KiCad standard lib, resvg
    # renders all round pads in a wrong color (?). Interestingly, passing the file through usvg before rendering fixes
    # this.
    # Sample footprint: Connector_PinSocket_2.00mm.pretty/PinSocket_2x11_P2.00mm_Vertical.kicad_mod
    run_cargo_cmd('usvg', [str(ref_svg), str(ref_svg)])

    # fix up usvg width/height
    with svg_soup(ref_svg) as soup:
        root = soup.find('svg')
        root['width'] = root_w
        root['height'] = root_h

    svg_to_png(ref_svg, tmpfile('Reference render', '.png'), bg=None, dpi=600)
    svg_to_png(out_svg, tmpfile('Output render', '.png'), bg=None, dpi=600)
    mean, _max, hist = svg_difference(ref_svg, out_svg, dpi=600, diff_out=tmpfile('Difference', '.png'))
    assert mean < 1e-3
    assert hist[9] < 100
    assert hist[3:].sum() < 1e-3*hist.size
    
