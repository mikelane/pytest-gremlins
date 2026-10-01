"""Per-mutant verdicts must not depend on state pytest sets up before a test runs (issue #486).

Conftest imports, ``pytest_configure`` hooks, and pytest's ``sys.path`` (test file basedir and ini
``pythonpath``) all exist in a real pytest run. A runner that skips pytest sees none of them, so a
test relying on them fails for every gremlin and would be scored as a kill.
"""

from __future__ import annotations

import re

import pytest

_SAMPLE = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

_SETTINGS = """
MODE = 'production'
"""

_CONFTEST_MODULE_LEVEL = """
import appsettings
appsettings.MODE = 'test'
"""

_CONFTEST_PYTEST_CONFIGURE = """
import appsettings


def pytest_configure(config):
    appsettings.MODE = 'test'
"""

_SAYS_NOTHING_ABOUT_CLASSIFY = """
import appsettings
from sample import classify


def test_runs_in_test_mode():
    assert appsettings.MODE == 'test'
    classify(11)
"""

_CONFTEST_SETUPS = {
    'module_level': _CONFTEST_MODULE_LEVEL,
    'pytest_configure': _CONFTEST_PYTEST_CONFIGURE,
}


def _verdicts(output: str) -> dict[str, int]:
    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Error')}


@pytest.mark.medium
class DescribeTestsPreparedByConftestConfiguration:
    """Conftest set-up outside the runtest hooks is invisible to the eligibility predicate."""

    @pytest.mark.parametrize('setup', list(_CONFTEST_SETUPS))
    def it_does_not_count_a_conftest_dependent_test_as_a_kill(
        self, pytester_with_markers: pytest.Pytester, setup: str
    ) -> None:
        existing = pytester_with_markers.path.joinpath('conftest.py').read_text()
        pytester_with_markers.makeconftest(existing + _CONFTEST_SETUPS[setup])
        pytester_with_markers.makepyfile(appsettings=_SETTINGS, sample=_SAMPLE)
        pytester_with_markers.makepyfile(test_sample=_SAYS_NOTHING_ABOUT_CLASSIFY)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '--gremlin-no-coverage-filter',
            '-p',
            'no:cacheprovider',
        )
        verdicts = _verdicts(result.stdout.str())

        assert verdicts['Zapped'] == 0
        assert verdicts['Survived'] > 0


_HELPER = """
def big():
    return 11
"""

_LAZY_HELPER_SAYS_NOTHING = """
from sample import classify


def test_big():
    from helpers import big
    classify(big())
"""

_MODULE_LEVEL_HELPER_CATCHES = """
from helpers import big
from sample import classify


def test_big():
    assert classify(big()) == 'big'
    assert classify(10) == 'small'
"""

_GREMLIN_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=comparison',
    '--gremlin-no-coverage-filter',
    '-p',
    'no:cacheprovider',
)


@pytest.mark.medium
class DescribeTestsImportingFromPytestsSysPath:
    """pytest puts the test file's basedir and ini ``pythonpath`` on sys.path; the runner does not."""

    def it_does_not_count_a_failed_lazy_helper_import_as_a_kill(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(**{'tests/helpers': _HELPER, 'tests/test_sample': _LAZY_HELPER_SAYS_NOTHING})

        result = pytester_with_markers.runpytest_subprocess(*_GREMLIN_ARGS)
        verdicts = _verdicts(result.stdout.str())

        assert verdicts['Zapped'] == 0
        assert verdicts['Survived'] > 0

    def it_zaps_with_a_test_that_imports_a_sibling_helper(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(
            **{'tests/helpers': _HELPER, 'tests/test_sample': _MODULE_LEVEL_HELPER_CATCHES}
        )

        result = pytester_with_markers.runpytest_subprocess(*_GREMLIN_ARGS)
        verdicts = _verdicts(result.stdout.str())

        assert verdicts['Error'] == 0
        assert verdicts['Zapped'] > 0

    def it_zaps_with_a_test_whose_helper_is_on_the_pytest_ini_pythonpath(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = app\n')
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(**{'app/helpers': _HELPER, 'test_sample': _MODULE_LEVEL_HELPER_CATCHES})

        result = pytester_with_markers.runpytest_subprocess(*_GREMLIN_ARGS)
        verdicts = _verdicts(result.stdout.str())

        assert verdicts['Error'] == 0
        assert verdicts['Zapped'] > 0
