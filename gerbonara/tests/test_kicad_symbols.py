
from itertools import zip_longest
import re

from ..cad.kicad.sexp import build_sexp
from ..cad.kicad.sexp_mapper import sexp
from ..cad.kicad.symbols import Library

from .utils import tmpfile


def test_parse(kicad_library_file):
    Library.open(kicad_library_file)


def test_round_trip(kicad_library_file, tmpfile):
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
    tmpfile('Processed original', '.kicad_sym').write_text(original)

    stage1 = re.sub(r'\(', '\n(', re.sub(r'\s+', ' ', stage1_sexp))
    tmpfile('Processed stage 1 output', '.kicad_sym').write_text(stage1)

    original_lines, stage1_lines = original.splitlines(), stage1.splitlines()

    i, j = 0, 0
    while i < len(original_lines) and j < len(stage1_lines):
        original, stage1 = original_lines[i], stage1_lines[j]

        if original.startswith('(version'):
            i, j = i+1, j+1
            continue

        original, stage1 = original.strip(), stage1.strip()
        if original != stage1:
            if any(original.startswith(f'({foo}') for foo in ['arc', 'circle', 'rectangle', 'polyline', 'text']):
                # These files have symbols with graphic primitives in non-standard order
                i, j = i+1, j+1
                return

            # Some symbol files contain ints where floats should be.
            # For instance, there is some disagreement as to whether rotation angles are ints or floats, and the spec doesn't say.
            FLOAT_INT_ISSUES = ['offset', 'at', 'width', 'xy', 'start', 'mid', 'end', 'center', 'length']
            if any(original.startswith(f'({name}') and stage1.startswith(f'({name}') for name in FLOAT_INT_ISSUES):
                fix_floats = lambda s: re.sub(r'\.0+(\W)', r'\1', s)
                original, stage1 = fix_floats(original), fix_floats(stage1)

            if original.startswith('(symbol') and stage1.startswith('(symbol'):
                # Re-export can change symbol order. This is ok.
                i, j = i+1, j+1
                continue

            # KiCad changed some flags from a bare flag to a named yes/no flag, which emits one more line here.
            NOW_NAMED = ['hide', 'bold', 'italic']
            if any(f'{name} yes' in stage1 for name in NOW_NAMED):
                j += 1
                continue

            if any(name in original or name in stage1 for name in NOW_NAMED):
                # KiCad changed the position of some flags inside text effects between versions.
                i, j = i+1, j+1
                continue

            if 'generator' in original:
                # KiCad changed the generator field from an atom to a str
                i, j = i+1, j+1
                continue

            NEW_FIELDS = [
                    'generator_version',
                    'exclude_from_sim',
                    ]
            if any(field in stage1 for field in NEW_FIELDS):
                # New field, skip only on right (new) side
                j += 1
                continue

        assert original == stage1
        i, j = i+1, j+1
    

