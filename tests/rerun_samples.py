"""Shared project samples and result parsing for the rerun option tests (refs #546).

The flaky test fails on its first call in every fresh process and passes on a rerun, so a baseline
run passes only because it is rerun.  The weak variant leaves some mutants of ``classify`` alive; the
strong variant also pins the boundary and catches them all.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

SAMPLE = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

FLAKY_WEAK_TEST = """
from sample import classify

calls = []


def test_big():
    calls.append(1)
    assert len(calls) > 1, 'flaky: fails on the first call in every fresh process'
    assert classify(11) == 'big'
"""

FLAKY_STRONG_TEST = """
from sample import classify

calls = []


def test_big():
    calls.append(1)
    assert len(calls) > 1, 'flaky: fails on the first call in every fresh process'
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

GREMLIN_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=comparison',
    '-p',
    'no:cacheprovider',
)


def verdicts(output: str) -> dict[str, int]:
    """Return how many gremlins the report counts as zapped, survived and errored."""

    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Error')}


def survivor_count(output: str) -> int:
    return verdicts(output)['Survived']


def write_flaky_project(pytester: pytest.Pytester, tests: str = FLAKY_WEAK_TEST) -> None:
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=tests)


def run_gremlins(pytester: pytest.Pytester, *extra_args: str, tests: str = FLAKY_WEAK_TEST) -> pytest.RunResult:
    write_flaky_project(pytester, tests)
    return pytester.runpytest_subprocess(*GREMLIN_ARGS, *extra_args)
