
import math
from itertools import zip_longest
import subprocess
import re

import bs4

from .utils import tmpfile, print_on_error
from .image_support import kicad_fp_export, svg_difference, svg_soup, svg_to_png, run_cargo_cmd

from .. import graphic_objects as go
from ..utils import MM, arc_bounds, sum_bounds
from ..layers import LayerStack
from ..cad.kicad.sexp import build_sexp, Atom
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
    

# Regrettably, we have to re-implement a significant part of the SVG spec to fix up the SVGs that kicad-cli produces.

def _compute_style(elem):
    current_style = {}
    for elem in [*reversed(list(elem.parents)), elem]:
        attrs = dict(elem.attrs)
        for match in re.finditer(r'([^:;]+):([^:;]+)', attrs.pop('style', '')):
            k, v = match.groups()
            current_style[k.strip().lower()] = v.strip()

        for k, v in elem.attrs.items():
            current_style[k.lower()] = v
    return current_style


def _parse_path_d(path):
    path_d = path.get('d')
    if not path_d:
        return

    style = _compute_style(path)
    if style.get('stroke', 'none') != 'none':
        sr = float(style.get('stroke-width', 0)) / 2
    else:
        sr = 0

    if 'C' in path_d:
        raise ValueError('Path contains cubic beziers')

    last_x, last_y = None, None
    # NOTE: kicad-cli exports oddly broken svgs. One of  the weirder issues is that in some paths, the "L" command is
    # simply ommitted.
    for match in re.finditer(r'([ML]?) ?([0-9.]+) *,? *([0-9.]+)|(A) ?([0-9.]+) *,? *([0-9.]+) *,? *([0-9.]+) *,? * ([01]) *,? *([01]) *,? *([0-9.]+) *,? *([0-9.]+)', path_d):
        ml, x, y, a, rx, ry, angle, large_arc, sweep, ax, ay = match.groups()

        if ml or not a:
            x, y = float(x), float(y)
            last_x, last_y = x, y
            yield x-sr, y-sr
            yield x-sr, y+sr
            yield x+sr, y-sr
            yield x+sr, y+sr

        else: # a
            rx, ry = float(rx), float(ry)
            ax, ay = float(ax), float(ay)
            angle = float(angle)
            large_arc = bool(int(large_arc))
            sweep = bool(int(sweep))

            if not math.isclose(rx, ry, abs_tol=1e-6):
                raise ValueError("Elliptical arcs not supported. How did that end up here? KiCad can't do those either!")

            mx = (last_x + ax)/2
            my = (last_y + ay)/2
            dx = ax - last_x
            dy = ay - last_y
            l = math.hypot(dx, dy)

            # clockwise normal
            nx = -dy/l
            ny = dx/l
            arg = rx**2 - (l/2)**2
            if arg < 0 or math.isclose(arg, 0, abs_tol=1e-6):
                cx, cy = mx, my
            else:
                nl = math.sqrt(arg)
                if sweep != large_arc:
                    cx = mx + nx*nl
                    cy = my + ny*nl
                else:
                    cx = mx - nx*nl
                    cy = my - ny*nl

            (min_x, min_y), (max_x, max_y) = arc_bounds(last_x, last_y, ax, ay, cx, cy, clockwise=(not sweep))
            min_x -= sr
            min_y -= sr
            max_x += sr
            max_y += sr
            # dbg_i += 1
            # with open(f'/tmp/dbg-arc-{dbg_i}.svg', 'w') as f:
            #     vbx, vby = min(last_x, ax), min(last_y, ay)
            #     vbw, vbh = max(last_x, ax), max(last_y, ay)
            #     vbw -= vbx
            #     vbh -= vby
            #     k = 2
            #     vbx -= vbw*k
            #     vby -= vbh*k
            #     vbw *= 2*k+1
            #     vbh *= 2*k+1
            #     sw = min(vbw, vbh)*1e-3
            #     mr = 3*sw
            #     f.write('<?xml version="1.0" standalone="no"?>\n')
            #     f.write('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n')
            #     f.write(f'<svg version="1.1" width="200mm" height="200mm" viewBox="{vbx} {vby} {vbw} {vbh}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">>\n')
            #     f.write(f'<path fill="none" stroke="#ff00ff" stroke-width="{sw}" d="{path_d}"/>\n')
            #     f.write(f'<rect fill="none" stroke="#404040" stroke-width="{sw}" x="{min_x}" y="{min_y}" width="{max_x-min_x}" height="{max_y-min_y}"/>\n')
            #     f.write(f'<circle fill="none" r="{mr}" stroke="blue" stroke-width="{sw}" cx="{last_x}" cy="{last_y}"/>\n')
            #     f.write(f'<circle fill="none" r="{mr}" stroke="blue" stroke-width="{sw}" cx="{ax}" cy="{ay}"/>\n')
            #     f.write(f'<circle fill="none" r="{mr}" stroke="red" stroke-width="{sw}" cx="{mx}" cy="{my}"/>\n')
            #     f.write(f'<circle fill="none" r="{mr}" stroke="red" stroke-width="{sw}" cx="{cx}" cy="{cy}"/>\n')
            #     f.write('</svg>\n')
            yield min_x, min_y
            yield min_x, max_y
            yield max_x, min_y
            yield max_x, max_y
            last_x, last_y = ax, ay

def test_render(kicad_mod_file, tmpfile, print_on_error):
    # These files have a large, mask-only pad that has a large solder mask margin set. Kicad doesn't render the margin
    # at all, which I think it should. We render things exactly as I'd expect.
    if kicad_mod_file.name in ['Fiducial_classic_big_CopperBottom_Type2.kicad_mod',
                               'Fiducial_classic_big_CopperTop_Type2.kicad_mod',
                               'Fiducial_classic_big_SilkscreenTop_Type2.kicad_mod']:
        return

    # Hide text and remove text from KiCad's renders. Our text rendering is alright, but KiCad has some weird issue
    # where it seems to mis-calculate the bounding box of stroke font text, leading to a wonky viewport not matching the
    # actual content, and text that is slightly off from where it should be. The difference is only a few hundred
    # micrometers, but it's enough to really throw off our error calculation, so we just ignore text.
    fp = FootprintInstance(0, 0, sexp=Footprint.open_mod(kicad_mod_file), hide_text=True)

    stack = LayerStack(courtyard=True, fabrication=True, adhesive=True)
    stack.add_layer('mechanical drawings')
    stack.add_layer('mechanical comments')
    fp.render(stack)
    color_map = {f'{side} {use}': KICAD_LAYER_COLORS[kicad_id] for (side, use), kicad_id in LAYER_MAP_G2K.items()}
    color_map['drill pth'] = (255, 255, 255, 1)
    color_map['drill npth'] = (255, 255, 255, 1)
    # Remove alpha since overlaid shapes won't work correctly with non-1 alpha without complicated svg filter hacks
    color_map = {key: (f'#{r:02x}{g:02x}{b:02x}', '1') for key, (r, g, b, _a) in color_map.items()}

    margin = 10 # mm

    layer = stack[('top', 'courtyard')]
    bounds = []
    #print('===== BOUNDS =====')
    for obj in layer.objects:
        if isinstance(obj, (go.Line, go.Arc)):
            bbox = (min_x, min_y), (max_x, max_y) = obj.bounding_box(unit=MM)
            #import textwrap
            #print(f'{min_x: 3.6f} {min_y: 3.6f} {max_x: 3.6f} {max_y: 3.6f}', '\n'.join(textwrap.wrap(str(obj), width=80, subsequent_indent=' '*(3+4*(3+1+6)))))
            bounds.append(bbox)
    #print('===== END =====')

    if not bounds:
        print('Footprint has no paths on courtyard layer')
        return

    bounds = sum_bounds(bounds)
    (min_x, min_y), (max_x, max_y) = bounds
    w, h = max_x-min_x, max_y-min_y
    print_on_error('Gerbonara bounds:', bounds, f'w={w:.6f}', f'h={h:.6f}')

    out_svg = tmpfile('Output', '.svg')
    out_svg.write_text(str(stack.to_svg(colors=color_map, force_bounds=bounds, margin=margin)))

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

        # nuke text since kicad-cli's text positioning looks sligthly wonky and we failed to replicate that wonkyness
        # exactly. 
        for elem in soup.find_all('g', attrs={'class': 'stroked-text'}):
            elem.decompose()

        for elem in soup.find_all('text'):
            elem.decompose()

    # Currently, there is a bug in resvg leading to mis-rendering. On the file below from the KiCad standard lib, resvg
    # renders all round pads in a wrong color (?). Interestingly, passing the file through usvg before rendering fixes
    # this.
    # Sample footprint: Connector_PinSocket_2.00mm.pretty/PinSocket_2x11_P2.00mm_Vertical.kicad_mod
    run_cargo_cmd('usvg', [str(ref_svg), str(ref_svg)])

    with svg_soup(ref_svg) as soup:
        # fix up usvg width/height
        root = soup.find('svg')
        root['width'] = root_w
        root['height'] = root_h

        #for elem in root.find_all('path'):
        #    if elem.attrs.get('fill', '').lower() == '#d864ff' and math.isclose(float(elem.attrs.get('fill-opacity', 0)), 0.4): 
        #        elem.decompose()

        # remove alpha to avoid complicated filter hacks
        for elem in root.descendants:
            if not isinstance(elem, bs4.Tag):
                continue

            if elem.has_attr('opacity'):
                elem['opacity'] = '1'

            if elem.has_attr('fill-opacity'):
                elem['fill-opacity'] = '1'

            if elem.has_attr('stroke-opacity'):
                elem['stroke-opacity'] = '1'

        # kicad-cli incorrectly fills arcs
        for elem in root.find_all('path'):
            if ' C ' in elem.get('d', '') and elem.get('stroke', 'none') != 'none':
                elem['fill'] = 'none'

    # Move fabrication layers above drills because kicad-cli's svg rendering is wonky.
    with svg_soup(out_svg) as soup:
        root = soup.find('svg')
        root.append(soup.find('g', id='l-bottom-fabrication').extract())
        root.append(soup.find('g', id='l-top-fabrication').extract())

    svg_to_png(ref_svg, tmpfile('Reference render', '.png'), bg=None, dpi=600)
    svg_to_png(out_svg, tmpfile('Output render', '.png'), bg=None, dpi=600)
    mean, _max, hist = svg_difference(ref_svg, out_svg, dpi=600, diff_out=tmpfile('Difference', '.png'))

    # compensate for circular pads aliasing badly
    aliasing_artifacts =  1e-3 * len(fp.sexp.pads)/10
    assert mean < 3e-3 + aliasing_artifacts
    assert hist[9] < 100
    assert hist[3:].sum() < (1e-3 + 10*aliasing_artifacts)*hist.size
    
