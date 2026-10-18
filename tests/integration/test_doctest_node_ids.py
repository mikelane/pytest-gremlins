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


def run_doctest_gremlins(pytester: pytest.Pytester, sample: str) -> dict[str, int]:
    pytester.makepyfile(sample=sample)
    result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--doctest-modules')
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


LOOSE_DOCTEST_SAMPLE = '''
def scale(n):
    """Scale a number.

    >>> _ = scale(3); print('a     b')
    a b
    """
    if n > 2:
        return n * 10
    return n + 1
'''


@pytest.mark.medium
class DescribeDoctestIniSettingsInGremlinRuns:
    """The doctest only passes under NORMALIZE_WHITESPACE and never checks ``scale``, so nothing may be zapped."""

    def it_leaves_survivors_when_the_optionflags_come_from_dash_o(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(sample=LOOSE_DOCTEST_SAMPLE)

        flags = 'doctest_optionflags=NORMALIZE_WHITESPACE'  # pragma: allowlist secret
        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '--doctest-modules', '-o', flags)

        counts = verdicts(result.stdout.str())
        assert counts['Zapped'] == 0
        assert counts['Survived'] > 0

    def it_leaves_survivors_when_the_optionflags_come_from_a_dash_c_file(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(sample=LOOSE_DOCTEST_SAMPLE)
        (pytester_with_markers.path / 'alt.ini').write_text(
            '[pytest]\ndoctest_optionflags = NORMALIZE_WHITESPACE\n', encoding='utf-8'
        )

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '--doctest-modules', '-c', 'alt.ini')

        counts = verdicts(result.stdout.str())
        assert counts['Zapped'] == 0
        assert counts['Survived'] > 0
