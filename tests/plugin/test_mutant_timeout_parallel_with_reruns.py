"""The mutant timeout still stops a hung gremlin in parallel workers when pytest-rerunfailures is loaded (issue #915).

With reruns configured, the per-attempt timeout is widened to the rerun budget, so a gremlin that fails fast and
then waits out ``reruns_delay`` finishes inside the widened limit and keeps its first-attempt Zapped verdict. A
gremlin that hangs past the widened limit must still be stopped and reported as a Timeout.
"""

from __future__ import annotations

import re

import pytest

SAMPLE = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

HANGS_UNDER_A_MUTANT = """
import os
import time

import pytest
from sample import classify


@pytest.mark.medium
def test_classify():
    if os.environ.get('ACTIVE_GREMLIN'):
        time.sleep(300)
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=comparison',
    '-p',
    'no:cacheprovider',
    '--gremlin-mutant-timeout',
    '3',
    '--gremlin-parallel',
    '--gremlin-workers=2',
)

# Per-attempt 3s plus one rerun of (3s + 8s delay) widens the limit to 14s; the hang lasts 300s.
LONGEST_PLAUSIBLE_RUN_SECONDS = 150


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


@pytest.mark.large
class DescribeMutantTimeoutInParallelWorkersWithReruns:
    def it_stops_a_hung_gremlin_and_reports_a_timeout(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE, test_sample=HANGS_UNDER_A_MUTANT)
        pytester.makeini('[pytest]\nreruns = 1\nreruns_delay = 8\n')

        result = pytester.runpytest_subprocess(*ARGS)

        output = result.stdout.str()
        assert _count(output, 'Timeout') > 0
        assert _count(output, 'Zapped') == 0
        assert result.duration < LONGEST_PLAUSIBLE_RUN_SECONDS
