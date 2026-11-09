import math
from itertools import zip_longest
from collections import Counter
import pytest
import subprocess
import re
import xml.etree.ElementTree as ET

import bs4

from .utils import tmpfile, print_on_error
from .image_support import run_cargo_cmd, svg_soup

from gerbonara import graphic_objects as go
from gerbonara.utils import MM, arc_bounds, sum_bounds
from gerbonara.layers import LayerStack
from gerbonara.cad.kicad.sexp import build_sexp, parse_sexp, Atom
from gerbonara.cad.kicad.sexp_mapper import sexp
from gerbonara.cad.kicad.tmtheme import *
from gerbonara.cad.kicad.schematic import Schematic
from gerbonara.cad.kicad.base_types import kicad_text_width
from gerbonara.newstroke import Newstroke
from gerbonara.cad.kicad.schematic_colors import Colorscheme


def test_load_kicad_schematic(kicad_sch_file):
    if kicad_sch_file.name in [
            # contains legacy syntax
            ]:
        pytest.skip()
    # Refers to a sub-sheet that is missing from KiCad's repository
    if kicad_sch_file.parts[-2:] == ('pcbnew', 'component_classes.kicad_sch'):
        pytest.skip()
    # Invalid on purpose
    if kicad_sch_file.name in ['broken.kicad_sch', 'sibling.kicad_sch']:
        pytest.skip()
    sch = Schematic.open(kicad_sch_file)
    print('Loaded schematic with', len(sch.wires), 'wires and', len(sch.symbols), 'symbols.')
    for subsh in sch.subsheets:
        subsh = subsh.open()
        print('Loaded sub-sheet with', len(subsh.wires), 'wires and', len(subsh.symbols), 'symbols.')


def _format_version(path):
    if (m := re.search(r'\(version\s+(\d+)', path.read_text(errors='replace')[:200])):
        return int(m.group(1))
    return 0


# (path, values) of every node, with numbers rounded so 1 and 1.0 compare equal, and (at x y 0) equal to (at x y)
def _nodes(sexp_node, path=()):
    head = str(sexp_node[0]) if sexp_node and isinstance(sexp_node[0], Atom) else ''
    here = path + (head,)
    values = tuple(round(float(v), 4) if isinstance(v, (int, float)) else str(v)
                   for v in sexp_node[1:] if not isinstance(v, list))
    if head == 'at' and len(values) == 3 and values[2] == 0:
        values = values[:2]
    children = [v for v in sexp_node[1:] if isinstance(v, list)]
    # Bare flags such as (do_not_autoplace), which come out as (do_not_autoplace yes), and empty containers carry no
    # data of their own.
    if values or children:
        yield here, values
    for child in children:
        yield from _nodes(child, here)


def test_kicad_schematic_round_trip(kicad_sch_file):
    # Older file formats are supported on a best-effort basis: they have to load, but they may change on a round trip.
    if _format_version(kicad_sch_file) < 20250114: # KiCad 9
        pytest.skip('KiCad file format older than KiCad 9')
    if kicad_sch_file.name in [
            # Properties with two (effects ...), the subject of KiCad issue 20173
            'Kicad 9 - multi channel test.kicad_sch',
            # Invalid on purpose
            'broken.kicad_sch',
            ]:
        pytest.skip()

    original = kicad_sch_file.read_text()
    output = Schematic.load(original).serialize()
    assert Schematic.load(output).serialize() == output

    # Nothing in the original file may get lost. Gerbonara writes some defaults KiCad leaves out, so the output may
    # have more.
    lost = Counter(_nodes(parse_sexp(original))) - Counter(_nodes(parse_sexp(output)))
    lost = {'/'.join(path): values for path, values in lost if not {'generator', 'generator_version'} & set(path)}
    assert not lost


def test_kicad_schematic_svg_export(kicad_sch_file):
    if kicad_sch_file.name in ['broken.kicad_sch']: # Invalid on purpose
        pytest.skip()

    sch = Schematic.open(kicad_sch_file)
    root = ET.fromstring(str(sch.to_svg()))
    w, h = sch.page_settings.size
    assert [float(v) for v in root.get('viewBox').split()] == pytest.approx([0, 0, w, h])


# Our SVG export compared to KiCad's as images: these documents as a whole, and at a high resolution, the area around
# the first item of each kind, shape, direction and style in them, and the names of pins that select an alternate
# function. Between them, they have every pin shape, label shape and direction, line style and fill that KiCad's demos
# have. The schematics are exported with kicad-cli in the KiCad schematic container, so only the corpus of the
# container's KiCad version is used.
KICAD_RENDER_DOCUMENTS = [
    'demos/pic_programmer/pic_programmer.kicad_sch',
    'demos/kit-dev-coldfire-xilinx_5213/kit-dev-coldfire-xilinx_5213.kicad_sch',
    'demos/kit-dev-coldfire-xilinx_5213/in_out_conn.kicad_sch',
    'demos/cm5_minima/CM5.kicad_sch',
    'demos/cm5_minima/CM5_MINIMA_3.kicad_sch',
    'demos/cm5_minima/IO.kicad_sch',
    'demos/cm5_minima/Ethernet.kicad_sch',
    'demos/complex_hierarchy/ampli_ht.kicad_sch',
    'demos/interf_u/interf_u.kicad_sch',
    'demos/simulation/ibis/ibis.kicad_sch',
    'demos/simulation/amplifier-ac/amplifier-ac.kicad_sch',
    'demos/simulation/q17/Q17ng.kicad_sch',
    'demos/tiny_tapeout/tinytapeout-demo.kicad_sch',
    'demos/tiny_tapeout/rp2040.kicad_sch',
    'demos/video/esvideo.kicad_sch',
    'demos/vme-wren/clocks.kicad_sch',
    'demos/jetson-agx-thor-baseboard/jetson-agx-thor-baseboard.kicad_sch',
    'qa/data/eeschema/issue19646/Resolver.kicad_sch',
    'demos/jetson-agx-thor-baseboard/expansion_connector.kicad_sch',
    'demos/jetson-agx-thor-baseboard/power.kicad_sch',
    'demos/jetson-agx-thor-baseboard/som_io.kicad_sch',
    'qa/data/eeschema/issue13431.kicad_sch',
]


class _BlackAndWhite(Colorscheme.KiCad):
    # Like KiCad's black and white export
    fill = 'none'
    item_colors = alternate_icons = False


class _NoText(_BlackAndWhite):
    # No text, as we remove it from KiCad's export
    text = values = labels = pin_names = pin_numbers = 'none'


def _area(box, anchor, margin=1.5, size=20):
    # (x, y, w, h) of a bounding box with a margin. Of long items, only size mm around their anchor.
    (x1, y1), (x2, y2) = box
    x1, y1, x2, y2 = x1 - margin, y1 - margin, x2 + margin, y2 + margin
    if x2 - x1 > size:
        x1 = min(max(anchor[0] - size/2, x1), x2 - size)
        x2 = x1 + size
    if y2 - y1 > size:
        y1 = min(max(anchor[1] - size/2, y1), y2 - size)
        y2 = y1 + size
    return x1, y1, x2 - x1, y2 - y1


def _anchor(item):
    # Where KiCad starts drawing an item: at the anchor of labels, and the start of lines and shapes
    for pt in (getattr(item, 'at', None), getattr(item, 'start', None), *getattr(item, 'points', [])[:1]):
        if pt is not None:
            return pt.x, pt.y
    return item.bounding_box()[0]


def _render_features(sch):
    # {description: area} of the first item of each kind, shape, direction and style in a schematic
    features = {}

    def add(what, item):
        features.setdefault(what, _area(item.bounding_box(), _anchor(item)))

    for sym in sch.symbols:
        lib = sch.lookup_symbol(sym.lib_name, sym.lib_id)
        to_sheet = sym.transform_point
        mirror = 'mirrored ' if sym.mirror and (sym.mirror.x or sym.mirror.y) else ''
        boxes = []
        for pin in (pin for unit in sym._units() for pin in unit.pins if not pin.hide):
            # From the connection point to the root of the pin. The bounding box of a pin also has its name, which is not
            # compared.
            a = math.radians(pin.at.rotation or 0)
            (tx, ty), (rx, ry) = to_sheet(pin.at.x, pin.at.y), \
                to_sheet(pin.at.x + pin.length*math.cos(a), pin.at.y + pin.length*math.sin(a))
            boxes.append(box := sum_bounds([((tx, ty), (tx, ty)), ((rx, ry), (rx, ry))]))
            direction = ('right' if tx > rx else 'left') if abs(tx - rx) > abs(ty - ry) else \
                ('down' if ty > ry else 'up')
            length = 'zero length ' if pin.length == 0 else ''
            features.setdefault(f'{length}{pin.style} {pin.etype} pin pointing {direction} of a {mirror}symbol',
                                _area(box, (tx, ty)))
        if boxes and any(unit.demorgan_style == 2 for unit in lib.units):
            features.setdefault('symbol with a De Morgan body style', _area(sum_bounds(boxes), (sym.at.x, sym.at.y)))

    for kind in ('global_labels', 'hierarchical_labels'):
        for label in getattr(sch, kind):
            overbar = ' with an overbar' if '~{' in label.text else ''
            add(f'{label.shape} {kind[:-1].replace("_", " ")} at {round(label.at.rotation or 0)} degrees{overbar}', label)
    for kind in ('junctions', 'no_connects'):
        for item in getattr(sch, kind):
            add(kind[:-1].replace('_', ' '), item)
    for entry in sch.bus_entries:
        add(f'{entry.stroke.type} bus entry', entry)
    for kind, name in (('wires', 'wire'), ('buses', 'bus'), ('polylines', 'polyline')):
        for line in getattr(sch, kind):
            style = 'legacy default' if getattr(line, 'legacy_dashed', False) else line.stroke.type
            fill = f' {line.fill.type} filled' if getattr(line, 'fill', None) is not None else ''
            add(f'{style}{fill} {name} of {min(len(line.points), 3)} points', line)
    for kind in ('rectangles', 'circles', 'arcs'):
        for shape in getattr(sch, kind, []):
            fill = shape.fill.type if shape.fill is not None else 'none'
            add(f'{shape.stroke.type} {fill} filled {kind[:-1]}', shape)
    for box in sch.text_boxes:
        fill = box.fill.type if box.fill is not None else 'none'
        add(f'{box.stroke.type} {fill} filled text box', box)
    for table in sch.tables:
        if table.cells:
            add('table', table)
    for flag in sch.netclass_flags:
        add(f'{flag.shape} netclass flag at {round(flag.at.rotation or 0)} degrees', flag)

    return features


def _render_text_features(sch):
    # {description: area} of the first pin pointing in each direction whose name is that of an alternate function
    features = {}
    for sym in sch.symbols:
        selected = {pin.name: pin.alternate for pin in sym.pins if pin.alternate}
        lib = sch.lookup_symbol(sym.lib_name, sym.lib_id)
        for pin in (pin for unit in lib.units for pin in unit.pins if pin.number.value in selected):
            a = math.radians(pin.at.rotation or 0)
            # Up to the end of the name inside the body
            ends = [pin.length, pin.length + 0.508 + kicad_text_width(selected[pin.number.value], 1.27)]
            (x0, y0), *ends = [sym.transform_point(pin.at.x + d*math.cos(a), pin.at.y + d*math.sin(a))
                               for d in [0] + ends]
            direction = ('right' if x0 > ends[0][0] else 'left') if abs(x0 - ends[0][0]) > 1e-6 else \
                ('down' if y0 > ends[0][1] else 'up')
            features.setdefault(f'name of the selected alternate function of a pin pointing {direction}',
                                _area(sum_bounds((pt, pt) for pt in [(x0, y0)] + ends), (x0, y0)))
    return features


def _kicad_and_our_render(sch_file, tmpfile, img_support, colorscheme=_NoText):
    ref_svg, out_svg = tmpfile('KiCad render', '.svg'), tmpfile('Gerbonara render', '.svg')
    img_support.kicad_sch_export(sch_file, ref_svg)
    out_svg.write_text(str(Schematic.open(sch_file).to_svg(colorscheme=colorscheme)))
    for svg in (ref_svg, out_svg):
        with svg_soup(svg) as soup:
            # KiCad draws each text's strokes in a <g class="stroked-text">. Images are scaled differently.
            text = soup.find_all('g', class_='stroked-text') if colorscheme is _NoText else []
            for elem in text + soup.find_all('image'):
                elem.decompose()
    return ref_svg, out_svg


def _compare_area(ref_svg, out_svg, area, name, tmpfile, img_support, dpi):
    ref_area, out_area = tmpfile(f'KiCad {name}', '.svg'), tmpfile(f'Gerbonara {name}', '.svg')
    for src, dst in ((ref_svg, ref_area), (out_svg, out_area)):
        dst.write_bytes(src.read_bytes())
        if area is not None:
            with svg_soup(dst) as soup:
                x, y, w, h = area
                soup.svg['viewBox'], soup.svg['width'], soup.svg['height'] = f'{x} {y} {w} {h}', f'{w}mm', f'{h}mm'
    return img_support.svg_difference(ref_area, out_area, diff_out=tmpfile(f'Difference {name}', '.png'),
                                      background='white', dpi=dpi)


def test_kicad_schematic_render(kicad_sch_render_file, tmpfile, img_support):
    if kicad_sch_render_file.name == 'clocks.kicad_sch':
        pytest.skip("KiCad's export draws symbol IC18 twice")
    ref_svg, out_svg = _kicad_and_our_render(kicad_sch_render_file, tmpfile, img_support)
    mean, _max, hist = _compare_area(ref_svg, out_svg, None, 'document', tmpfile, img_support, dpi=150)
    assert mean < 1e-3
    assert hist[3:].sum() < 2e-4*hist.size


def test_kicad_schematic_render_features(kicad_sch_render_file, tmpfile, img_support):
    sch = Schematic.open(kicad_sch_render_file)
    failed = []
    # Without text, and the names of pins of alternate functions with their text
    for colorscheme, features, dpi, max_differing in ((_NoText, _render_features(sch), 1200, 1e-4),
                                                      (_BlackAndWhite, _render_text_features(sch), 600, 1e-3)):
        if not features:
            continue
        ref_svg, out_svg = _kicad_and_our_render(kicad_sch_render_file, tmpfile, img_support, colorscheme)
        for what, area in features.items():
            mean, _max, hist = _compare_area(ref_svg, out_svg, area, what, tmpfile, img_support, dpi=dpi)
            if not (mean < 5e-3 and hist[3:].sum() < max_differing*hist.size):
                failed.append(f'{what} at {area}: mean {float(mean):.5f}, {hist[3:].sum()/hist.size:.5f} of pixels '
                              'differ')
    assert not failed, '\n'.join(failed)


class _TextOnly(Colorscheme.KiCad):
    wire = bus = lines = no_connect = fill = 'none'


def test_kicad_schematic_text_placement(kicad_sch_reference, tmpfile, img_support):
    # Only the texts of KiCad's own SVG export of a schematic and of ours, compared as images. KiCad draws each text's
    # strokes in a <g class="stroked-text">, so everything else is removed from its export, and we only draw texts.
    sch_file, svg_file = kicad_sch_reference
    ref_svg, out_svg = tmpfile('KiCad texts', '.svg'), tmpfile('Gerbonara texts', '.svg')

    ref_svg.write_bytes(svg_file.read_bytes())
    with svg_soup(ref_svg) as soup:
        for elem in soup.find_all(['path', 'rect', 'circle', 'polyline', 'polygon', 'text', 'image']):
            if not elem.find_parent('g', class_='stroked-text'):
                elem.decompose()
        coords = [float(v) for path in soup.find_all('path') for v in re.findall(r'-?\d+(?:\.\d+)?', path['d'])]
        # The area around the texts, to compare it at a high resolution
        x, y = min(coords[0::2]) - 2, min(coords[1::2]) - 2
        w, h = max(coords[0::2]) + 2 - x, max(coords[1::2]) + 2 - y
        soup.svg['viewBox'], soup.svg['width'], soup.svg['height'] = f'{x} {y} {w} {h}', f'{w}mm', f'{h}mm'

    out_svg.write_text(str(Schematic.open(sch_file).to_svg(colorscheme=_TextOnly)))
    with svg_soup(out_svg) as soup:
        soup.svg['viewBox'], soup.svg['width'], soup.svg['height'] = f'{x} {y} {w} {h}', f'{w}mm', f'{h}mm'

    mean, _max, hist = img_support.svg_difference(ref_svg, out_svg, diff_out=tmpfile('Difference', '.png'),
                                                 background='white', dpi=600)
    assert mean < 5e-3
    assert hist[4:].sum() < 1e-3*hist.size
