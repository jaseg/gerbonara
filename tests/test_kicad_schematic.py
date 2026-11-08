import math
from itertools import zip_longest
from collections import Counter
import pytest
import subprocess
import re

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


def test_load_kicad_schematic(kicad_sch_file):
    if kicad_sch_file.name in [
            # contains legacy syntax
            ]:
        pytest.skip()
    # Refers to a sub-sheet that is missing from KiCad's repository
    if kicad_sch_file.parts[-2:] == ('pcbnew', 'component_classes.kicad_sch'):
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
