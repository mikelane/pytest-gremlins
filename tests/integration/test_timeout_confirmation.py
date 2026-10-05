"""A timeout is a kill only if the unmutated tests finish inside the timeout (issue #565).

A per-mutant timeout shorter than the tests' own runtime makes every gremlin time out, survivors
included. Counting those as kills scored a suite that asserts nothing as perfect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

_TARGET_WITH_A_COMPARISON = """
def is_larger(a, b):
    return a > b
"""

_SLOW_TEST_THAT_ASSERTS_NOTHING = """
import time

import pytest
import sample


@pytest.mark.medium
def test_is_larger():
    sample.is_larger(2, 1)
    time.sleep(2)
"""

_TARGET_THAT_LOOPS_FOREVER_WHEN_MUTATED = """
def count_down(n):
    while n > 0:
        n = n - 1
    return n
"""

_FAST_TEST_THAT_ASSERTS = """
import pytest
import sample


@pytest.mark.medium
def test_count_down():
    assert sample.count_down(3) == 0
"""

_COMMON_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-report=json',
    '-p',
    'no:cacheprovider',
)

_MODES = {
    'sequential': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


def _json_report(pytester: pytest.Pytester) -> dict:
    return json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text())


@pytest.mark.parametrize(
    'mode',
    [
        # The sequential run is the CI medium-tier regression of the fake score. Its 1s mutants die fast and the
        # confirmation fails on pytest start-up alone, so it stays cheap and gets steadier, not flakier, under load.
        pytest.param('sequential', marks=pytest.mark.medium),
        pytest.param('parallel', marks=pytest.mark.large),
        pytest.param('batch', marks=pytest.mark.large),
    ],
)
class DescribeTimeoutShorterThanTheUnmutatedTests:
    """A timeout that the unmutated selection hits too says nothing about the mutant."""

    def it_counts_the_timeouts_as_errors_and_says_so(self, pytester_with_markers: pytest.Pytester, mode: str) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET_WITH_A_COMPARISON)
        pytester_with_markers.makepyfile(test_sample=_SLOW_TEST_THAT_ASSERTS_NOTHING)

        result = pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-operators=comparison', '--gremlin-mutant-timeout=1', *_MODES[mode]
        )

        report = _json_report(pytester_with_markers)
        assert report['summary']['percentage'] < 100.0
        assert report['summary']['timeout'] == 0
        assert report['timeout_warning']['downgraded'] == report['summary']['error'] >= 1
        assert report['timeout_warning']['mutant_timeout'] == 1
        assert result.stdout.str().count('Raise the timeout with --gremlin-mutant-timeout') == 1


@pytest.mark.large
class DescribeTimeoutCausedByTheMutant:
    """A mutant that hangs a test that is fast without it is still a kill."""

    def it_keeps_the_timeout_as_a_kill_and_does_not_warn(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET_THAT_LOOPS_FOREVER_WHEN_MUTATED)
        pytester_with_markers.makepyfile(test_sample=_FAST_TEST_THAT_ASSERTS)

        pytester_with_markers.runpytest_subprocess(
            *_COMMON_ARGS, '--gremlin-operators=arithmetic', '--gremlin-mutant-timeout=30'
        )

        report = _json_report(pytester_with_markers)
        assert report['summary']['timeout'] >= 1
        assert 'timeout_warning' not in report
