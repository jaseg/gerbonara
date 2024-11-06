
import os
from pathlib import Path
import tqdm
import multiprocessing.pool
import subprocess
from itertools import chain

import pytest

from .image_support import ImageDifference, run_cargo_cmd, bulk_populate_kicad_fp_export_cache, KICAD_CONTAINER

def pytest_assertrepr_compare(op, left, right):
    if isinstance(left, ImageDifference) or isinstance(right, ImageDifference):
        diff = left if isinstance(left, ImageDifference) else right
        return [
            f'Image difference assertion failed.',
            f'    Calculated difference: {diff}',
            f'    Histogram: {diff.histogram}', ]


# store report in node object so tmp_gbr can determine if the test failed.
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f'rep_{rep.when}', rep)


fail_dir = Path('gerbonara_test_failures')
def pytest_sessionstart(session):
    if 'PYTEST_XDIST_WORKER' in os.environ: # only run this on the controller
        return

    for f in chain(fail_dir.glob('*.gbr'), fail_dir.glob('*.png')):
        f.unlink()

    try:
        run_cargo_cmd('resvg', '--help', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pytest.exit('resvg binary not found, aborting test.', 2)


def pytest_configure(config):
    os.nice(20)
    # Resvg can sometimes consume a lot of memory. Make sure we don't kill the user's session.
    if (oom_adj := Path('/proc/self/oom_adj')).is_file():
        oom_adj.write_text('15\n')

    if 'PYTEST_XDIST_WORKER' in os.environ: # only run this on the controller
        return

    if (lib_dir := os.environ.get('KICAD_FOOTPRINTS')):
        lib_dir = Path(lib_dir).expanduser()
        if not lib_dir.is_dir():
            raise ValueError(f'Path "{lib_dir}" given by KICAD_FOOTPRINTS environment variable does not exist or is not a directory.')

        print('Updating podman image')
        subprocess.run(['podman', 'pull', KICAD_CONTAINER], check=True)

        print('Checking and bulk re-building KiCad footprint library cache')
        with multiprocessing.pool.ThreadPool() as pool: # use thread pool here since we're only monitoring podman processes 
            lib_dirs = list(lib_dir.glob('*.pretty'))
            res = list(tqdm.tqdm(pool.imap(lambda path: bulk_populate_kicad_fp_export_cache(path), lib_dirs), total=len(lib_dirs)))


def pytest_addoption(parser):
    parser.addoption('--kicad-symbol-library', nargs='*', help='Run symbol library tests on given symbol libraries. May be given multiple times.')
    parser.addoption('--kicad-footprint-files', nargs='*', help='Run footprint library tests on given footprint files. May be given multiple times.')


def pytest_generate_tests(metafunc):
    if 'kicad_library_file' in metafunc.fixturenames:
        if not (library_files := metafunc.config.getoption('symbol_library', None)):
            if (lib_dir := os.environ.get('KICAD_SYMBOLS')):
                lib_dir = Path(lib_dir).expanduser()
                library_files = list(lib_dir.glob('*.kicad_sym'))
            else:
                raise ValueError('Either --kicad-symbol-library command line parameter or KICAD_SYMBOLS environment variable must be given to run kicad symbol tests.')
        metafunc.parametrize('kicad_library_file', library_files, ids=list(map(str, library_files)))

    if 'kicad_mod_file' in metafunc.fixturenames:
        if not (mod_files := metafunc.config.getoption('footprint_files', None)):
            if (lib_dir := os.environ.get('KICAD_FOOTPRINTS')):
                lib_dir = Path(lib_dir).expanduser()
                mod_files = list(lib_dir.glob('*.pretty/*.kicad_mod'))
            else:
                raise ValueError('Either --kicad-footprint-files command line parameter or KICAD_FOOTPRINTS environment variable must be given to run kicad footprint tests.')
        metafunc.parametrize('kicad_mod_file', mod_files, ids=list(map(str, mod_files)))
