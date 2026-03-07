"""Tests for pardoned gremlin accounting in MutationScore."""

from __future__ import annotations

import pytest

from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


@pytest.mark.small
class DescribeMutationScorePardonedCounting:
    """Tests for pardoned count in MutationScore."""

    def it_counts_pardoned_results(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.PARDONED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        assert score.pardoned == 2

    def it_pardoned_defaults_to_zero_when_none_present(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        assert score.pardoned == 0


@pytest.mark.small
class DescribeMutationScorePercentageExcludesPardoned:
    """Tests that pardoned gremlins are excluded from the score denominator."""

    def it_excludes_pardoned_from_denominator(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        # 3 zapped / (5 total - 1 pardoned) = 3/4 = 75%
        assert score.percentage == 75.0

    def it_returns_zero_when_all_are_pardoned(self, make_result):
        results = [make_result(GremlinResultStatus.PARDONED) for _ in range(5)]
        score = MutationScore.from_results(results)
        assert score.percentage == 0.0

    def it_returns_100_when_all_non_pardoned_are_zapped(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        assert score.percentage == 100.0

    def it_pardoned_does_not_affect_total(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        assert score.total == 2
