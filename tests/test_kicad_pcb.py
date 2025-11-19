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
from gerbonara.cad.kicad.pcb import Board


def test_load_kicad_pcb(kicad_pcb_file):
    if kicad_pcb_file.name in [
            # contains legacy syntax
            ]:
        pytest.skip()
    pcb = Board.open(kicad_pcb_file)
    print('Loaded PCB with', len(pcb.track_segments), 'track segments and', len(pcb.footprints), 'footprints.')
