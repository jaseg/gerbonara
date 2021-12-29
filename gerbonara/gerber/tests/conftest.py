
import pytest

from .image_support import ImageDifference

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_assertrepr_compare(op, left, right):
    if isinstance(left, ImageDifference) or isinstance(right, ImageDifference):
        diff = left if isinstance(left, ImageDifference) else right
        return [
            f'Image difference assertion failed.',
            f'    Reference: {diff.ref_path}',
            f'    Actual: {diff.out_path}',
            f'    Calculated difference: {diff}', ]

# store report in node object so tmp_gbr can determine if the test failed.
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f'rep_{rep.when}', rep)

