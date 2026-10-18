"""Gremlins covered only by a doctest get real verdicts, not ERROR (refs #594)."""

from __future__ import annotations

import pytest
from rerun_samples import (
    GREMLIN_ARGS,
    verdicts,
)

STRONG_DOCTEST_SAMPLE = '''
def classify(n):
    """Classify a number.

    >>> classify(11)
    'big'
    >>> classify(10)
    'small'
    """
    if n > 10:
        return 'big'
    return 'small'
'''

WEAK_DOCTEST_SAMPLE = '''
def classify(n):
    """Classify a number.

    >>> classify(11)
    'big'
    """
    if n > 10:
        return 'big'
    return 'small'
'''


def run_doctest_gremlins(pytester: pytest.Pytester, sample: str, *extra_args: str) -> dict[str, int]:
    pytester.makepyfile(sample=sample)
    result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--doctest-modules', *extra_args)
    return verdicts(result.stdout.str())


@pytest.mark.medium
class DescribeDoctestCoveredGremlins:
    def it_zaps_gremlins_that_a_doctest_catches(self, pytester_with_markers: pytest.Pytester) -> None:
        counts = run_doctest_gremlins(pytester_with_markers, STRONG_DOCTEST_SAMPLE)

        assert counts['Error'] == 0
        assert counts['Zapped'] > 0

    def it_leaves_gremlins_that_a_doctest_misses_surviving(self, pytester_with_markers: pytest.Pytester) -> None:
        counts = run_doctest_gremlins(pytester_with_markers, WEAK_DOCTEST_SAMPLE)

        assert counts['Error'] == 0
        assert counts['Survived'] > 0

    def it_gives_real_verdicts_when_doctest_modules_comes_from_addopts(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = --doctest-modules\n')
        pytester_with_markers.makepyfile(sample=STRONG_DOCTEST_SAMPLE)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS)

        counts = verdicts(result.stdout.str())
        assert counts['Error'] == 0
        assert counts['Zapped'] > 0
