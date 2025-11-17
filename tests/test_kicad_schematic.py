import math
from itertools import zip_longest
import pytest
import subprocess
import re

import bs4

from .utils import tmpfile, print_on_error
from .image_support import run_cargo_cmd, svg_soup

from gerbonara import graphic_objects as go
from gerbonara.utils import MM, arc_bounds, sum_bounds
from gerbonara.layers import LayerStack
from gerbonara.cad.kicad.sexp import build_sexp, Atom
from gerbonara.cad.kicad.sexp_mapper import sexp
from gerbonara.cad.kicad.tmtheme import *
from gerbonara.cad.kicad.schematic import Schematic


def test_load_kicad_schematic(kicad_sch_file):
    if kicad_sch_file.name in [
            # contains legacy syntax
            ]:
        pytest.skip()
    sch = Schematic.open(kicad_sch_file)
    print('Loaded schematic with', len(sch.wires), 'wires and', len(sch.symbols), 'symbols.')
    for subsh in sch.subsheets:
        subsh = subsh.open()
        print('Loaded sub-sheet with', len(subsh.wires), 'wires and', len(subsh.symbols), 'symbols.')
