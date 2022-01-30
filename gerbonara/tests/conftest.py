
from pathlib import Path

import pytest

from .image_support import ImageDifference

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
    if not hasattr(session.config, 'workerinput'): # on worker
        return

    # on coordinator
    for f in chain(fail_dir.glob('*.gbr'), fail_dir.glob('*.png')):
        f.unlink()
