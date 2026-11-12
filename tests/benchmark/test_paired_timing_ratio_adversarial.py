"""Adversarial QA (#997): replay of import times recorded under CPU contention.

The durations below were measured on this machine for argparse (loader import vs PR #610 import) by the same
alternating pair loop ``_paired_timing_ratio`` runs, while 24 busy loops competed for 12 cores. An uncontended
import takes about 27 ms on both sides, so the true ratio is about 0.98. Contention stretched most runs to 60-190 ms
at random, on either side of a pair.
"""

import pytest

from tests.benchmark.test_sources_json_payload import (
    ALLOWED_REGRESSION,
    _paired_timing_ratio,
    _ScriptedClock,
)

CANDIDATE_MS = [
    110.9, 99.3, 69.1, 26.3, 121.0, 28.3, 80.0, 74.6, 83.6, 54.8, 103.0, 88.4, 37.5,
    113.7, 102.4, 28.0, 92.5, 27.2, 129.7, 127.7, 108.5, 91.6, 28.0, 108.0, 41.9,
]  # fmt: skip
BASELINE_MS = [
    69.8, 64.1, 108.5, 87.6, 26.8, 152.4, 83.6, 103.0, 27.2, 162.1, 72.3, 40.4, 27.1,
    85.1, 27.5, 141.2, 83.6, 70.2, 83.3, 27.4, 82.6, 101.6, 27.8, 193.1, 26.9,
]  # fmt: skip


@pytest.mark.small
class DescribePairedTimingRatioUnderSustainedContention:
    def it_does_not_report_a_regression_when_contention_hits_most_runs_on_both_sides(self):
        clock = _ScriptedClock()
        candidate = clock.timed(CANDIDATE_MS)
        baseline = clock.timed(BASELINE_MS)

        ratio = _paired_timing_ratio(candidate, baseline, repeats=len(CANDIDATE_MS), clock=clock)

        assert ratio <= ALLOWED_REGRESSION
