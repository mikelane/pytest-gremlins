"""Per-gremlin runs must not distribute tests to xdist workers (refs #486).

Every gremlin runs through the pytest bootstrap, and the gremlin import hook lives only in
the bootstrap process.  If the project's ``addopts`` (or ``PYTEST_ADDOPTS``) asks for
``-n N``, xdist workers import the original code, an adequate test passes against every
mutant and each gremlin is falsely reported as a survivor.  xdist options are stripped from
per-gremlin runs; xdist stays loaded and runs the tests in-process.
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

_CATCHES = """
from sample import classify


def test_big():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

_CATCHES_WITH_WORKER_ID = """
from sample import classify


def test_big(worker_id):
    assert isinstance(worker_id, str)
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

_GREMLIN_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=comparison',
    '-p',
    'no:cacheprovider',
)


def _verdicts(output: str) -> dict[str, int]:
    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Error')}


def _run_gremlins(pytester: pytest.Pytester, tests: str, *extra_args: str) -> dict[str, int]:
    pytester.makepyfile(sample=_SAMPLE)
    pytester.makepyfile(test_sample=tests)
    result = pytester.runpytest_subprocess(*_GREMLIN_ARGS, *extra_args)
    return _verdicts(result.stdout.str())


@pytest.mark.medium
class DescribeProjectsWithXdistInAddopts:
    """An ``addopts`` that asks for xdist workers must still have mutants judged against the mutated code."""

    @pytest.mark.parametrize(
        'addopts',
        ['-n 2', '-n auto', '--numprocesses=2 --dist=loadscope'],
    )
    def it_zaps_with_an_adequate_test(self, pytester_with_markers: pytest.Pytester, addopts: str) -> None:
        pytester_with_markers.makeini(f'[pytest]\naddopts = {addopts}\n')

        verdicts = _run_gremlins(pytester_with_markers, _CATCHES)

        assert verdicts['Survived'] == 0
        assert verdicts['Zapped'] > 0

    def it_zaps_under_parallel_gremlin_execution(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = -n 2\n')

        verdicts = _run_gremlins(pytester_with_markers, _CATCHES, '--gremlin-parallel', '--gremlin-workers=2')

        assert verdicts['Survived'] == 0
        assert verdicts['Zapped'] > 0

    def it_still_runs_tests_that_use_the_worker_id_fixture(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = -n 2\n')

        verdicts = _run_gremlins(pytester_with_markers, _CATCHES_WITH_WORKER_ID)

        assert verdicts['Error'] == 0
        assert verdicts['Survived'] == 0
        assert verdicts['Zapped'] > 0


@pytest.mark.medium
class DescribeProjectsWithXdistInPytestAddoptsEnv:
    """``PYTEST_ADDOPTS`` is appended to every pytest invocation, so it must not distribute gremlin runs either."""

    def it_zaps_with_an_adequate_test(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-n 2')

        verdicts = _run_gremlins(pytester_with_markers, _CATCHES)

        assert verdicts['Survived'] == 0
        assert verdicts['Zapped'] > 0

    def it_zaps_under_parallel_gremlin_execution(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-n 2')

        verdicts = _run_gremlins(pytester_with_markers, _CATCHES, '--gremlin-parallel', '--gremlin-workers=2')

        assert verdicts['Survived'] == 0
        assert verdicts['Zapped'] > 0
