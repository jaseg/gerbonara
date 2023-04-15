
from itertools import zip_longest
import re

from ..cad.kicad.sexp import build_sexp
from ..cad.kicad.sexp_mapper import sexp
from ..cad.kicad.symbols import Library


def test_parse(kicad_library_file):
    Library.open(kicad_library_file)


def test_round_trip(kicad_library_file):
    print('========== Stage 1 load ==========')
    orig_lib = Library.open(kicad_library_file)
    print('========== Stage 1 save ==========')
    stage1_sexp = build_sexp(orig_lib.sexp())

    print('========== Stage 2 load ==========')
    reparsed_lib = Library.parse(stage1_sexp)
    print('========== Stage 2 save ==========')
    stage2_sexp = build_sexp(reparsed_lib.sexp())
    print('========== Checks ==========')

    for stage1, stage2 in zip_longest(stage1_sexp.splitlines(), stage2_sexp.splitlines()):
        assert stage1 == stage2

    original = re.sub(r'\(', '\n(', re.sub(r'\s+', ' ', kicad_library_file.read_text()))
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

            if original.startswith('(offset') and stage1.startswith('(offset'):
                # Some symbol files contain ints where floats should be.
                return

            if original.startswith('(symbol') and stage1.startswith('(symbol'):
                # Re-export can change symbol order. This is ok.
                return

            if original.startswith('(at') and stage1.startswith('(at'):
                # There is some disagreement as to whether rotation angles are ints or floats, and the spec doesn't say.
                return

            assert original == stage1
    

