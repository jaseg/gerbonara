
import os
from pathlib import Path
import tqdm
import multiprocessing.pool
import subprocess
from itertools import chain

import pytest

from .image_support import ImageDifference, run_cargo_cmd, ImageSupport


@pytest.fixture
def kicad_container(request):
    return request.config.kicad_container


@pytest.fixture()
def kicad_footprints_libdir(request):
    return request.config.kicad_footprints_libdir


@pytest.fixture()
def kicad_symbols_libdir(request):
    return request.config.kicad_symbols_libdir


@pytest.fixture()
def img_support(request):
    return request.config.image_support


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
        run_cargo_cmd('resvg', ['--help'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pytest.exit('resvg binary not found, aborting test.', 2)


def _update_repo_cache(lib_dir, repo_url, rev, sparse_patterns=None):
    """ Check out `rev` (a tag, branch or commit) of `repo_url` into `lib_dir` without history. With `sparse_patterns`,
    only the files matching them are fetched. """
    def git(*args, check=True, **kwargs):
        return subprocess.run(['git', '-c', 'advice.detachedHead=false', '-C', str(lib_dir), *args], check=check,
                              **kwargs)

    if not lib_dir.is_dir():
        print(f'Checking out {repo_url} at {rev}')
        lib_dir.mkdir(parents=True)
        git('init', '-q')
        git('remote', 'add', 'origin', repo_url)
    if sparse_patterns:
        git('sparse-checkout', 'set', '--no-cone', *sparse_patterns)

    # Remember what each rev resolved to, so that being up to date can be checked without fetching
    ref = f'refs/cache/{rev}'
    head, cached = (git('rev-parse', '-q', '--verify', f'{r}^{{commit}}', capture_output=True, text=True,
                        check=False).stdout.strip() for r in ('HEAD', ref))
    if head and head == cached:
        print(f'{lib_dir} is up to date, only cleaning.')
        git('clean', '-q', '--force', '-d', '-x')
        return False

    git('fetch', '-q', '--depth', '1', *(['--filter=blob:none'] if sparse_patterns else []), 'origin', f'+{rev}:{ref}')
    git('checkout', '-q', '--force', '--detach', ref)
    git('clean', '-q', '--force', '-d', '-x')
    return True


KICAD_SOURCE_PATTERNS = ['/demos/**/*.kicad_sch', '/qa/data/**/*.kicad_sch']
KICAD_SOURCE_PCB_PATTERNS = ['/demos/*.kicad_pcb', '/qa/data/**/*.kicad_pcb']


def pytest_addoption(parser):
    parser.addini('kicad_footprints_tag', 'git tag or branch for KiCad footprint library repo used as testdata', default='main')
    parser.addini('kicad_symbols_tag', 'git tag or branch for KiCad symbol library repo used as testdata', default='main')
    parser.addini('kicad_container_tag', 'docker hub tag for the KiCad container to use for exporting footprint images', default='main')
    parser.addini('kicad_source_tag', 'git tags or commits of the KiCad source repo whose demo and QA files are used as testdata, separated by spaces', default='main')
    parser.addoption("--use-cached-data", action="store_true", help="Do not re-check git repo caches and podman image")


def pytest_configure(config):
    os.nice(20)
    # Resvg can sometimes consume a lot of memory. Make sure we don't kill the user's session.
    if (oom_adj := Path('/proc/self/oom_adj')).is_file():
        oom_adj.write_text('15\n')

    if (lib_dir := os.environ.get('KICAD_FOOTPRINTS')):
        config.kicad_footprints_libdir = Path(lib_dir).expanduser()
    else:
        config.kicad_footprints_libdir = config.cache.mkdir('kicad-footprints') / 'repo'

    if (lib_dir := os.environ.get('KICAD_SYMBOLS')):
        config.kicad_symbols_libdir = Path(lib_dir).expanduser()
    else:
        config.kicad_symbols_libdir = config.cache.mkdir('kicad-symbols') / 'repo'

    if (lib_dirs := os.environ.get('KICAD_SOURCE')):
        config.kicad_source_dirs = [Path(d).expanduser() for d in lib_dirs.split(os.pathsep)]
    else:
        config.kicad_source_dirs = [config.cache.mkdir(f'kicad-source-{rev}') / 'repo'
                                    for rev in config.getini('kicad_source_tag').split()]

    did_updates = False
    is_pytest_controller = 'PYTEST_XDIST_WORKER' not in os.environ
    if is_pytest_controller and not config.getoption("--use-cached-data"):
        # Update cached library repos unless they are overridden from outside.
        if not os.environ.get('KICAD_FOOTPRINTS'):
            tag = config.getini('kicad_footprints_tag')
            did_updates |= _update_repo_cache(config.kicad_footprints_libdir, 'https://gitlab.com/kicad/libraries/kicad-footprints', tag)

        if not os.environ.get('KICAD_SYMBOLS'):
            tag = config.getini('kicad_symbols_tag')
            did_updates |= _update_repo_cache(config.kicad_symbols_libdir, 'https://gitlab.com/kicad/libraries/kicad-symbols', tag)

        if not os.environ.get('KICAD_SOURCE'):
            revs = config.getini('kicad_source_tag').split()
            for i, (rev, lib_dir) in enumerate(zip(revs, config.kicad_source_dirs)):
                # PCBs are only tested with the first KiCad version
                patterns = KICAD_SOURCE_PATTERNS + (KICAD_SOURCE_PCB_PATTERNS if i == 0 else [])
                did_updates |= _update_repo_cache(lib_dir, 'https://gitlab.com/kicad/code/kicad', rev, patterns)

    tag = config.getini("kicad_container_tag")
    config.kicad_container = os.environ.get('KICAD_CONTAINER', f'registry.hub.docker.com/kicad/kicad:{tag}')

    if is_pytest_controller and not config.getoption("--use-cached-data"):
        print('Checking podman image')
        res = subprocess.run(['podman', 'image', 'exists', config.kicad_container])
        if res.returncode:
            print('Updating podman image')
            subprocess.run(['podman', 'pull', config.kicad_container], check=True)
            did_updates = True
        else:
            print('Up to date.')

    config.image_support = ImageSupport(config.cache.mkdir('image_cache'), config.kicad_container)

    if is_pytest_controller and did_updates and not config.getoption("--use-cached-data"):
        print('Checking KiCad footprint library render cache')
        with multiprocessing.pool.ThreadPool() as pool: # use thread pool here since we're only monitoring podman processes 
            lib_dirs = list(config.kicad_footprints_libdir.glob('*.pretty'))
            res = list(tqdm.tqdm(pool.imap(lambda path: config.image_support.bulk_populate_kicad_fp_export_cache(path), lib_dirs), total=len(lib_dirs)))


def pytest_generate_tests(metafunc):
    if 'kicad_library_file' in metafunc.fixturenames:
        library_files = list(metafunc.config.kicad_symbols_libdir.glob('*.kicad_sym'))
        metafunc.parametrize('kicad_library_file', library_files, ids=list(map(str, library_files)))

    if 'kicad_mod_file' in metafunc.fixturenames:
        mod_files = list(metafunc.config.kicad_footprints_libdir.glob('*.pretty/*.kicad_mod'))
        metafunc.parametrize('kicad_mod_file', mod_files, ids=list(map(str, mod_files)))

    source_dirs = metafunc.config.kicad_source_dirs
    if 'kicad_sch_file' in metafunc.fixturenames:
        files = [f for d in source_dirs for pattern in ('demos/**/*.kicad_sch', 'qa/data/**/*.kicad_sch')
                 for f in sorted(d.glob(pattern))]
        metafunc.parametrize('kicad_sch_file', files, ids=list(map(str, files)))

    if 'kicad_pcb_file' in metafunc.fixturenames:
        # PCBs are only tested with the first KiCad version
        files = list(source_dirs[0].glob('demos/*.kicad_pcb'))
        files += list(source_dirs[0].glob('qa/data/**/*.kicad_pcb'))
        metafunc.parametrize('kicad_pcb_file', files, ids=list(map(str, files)))

