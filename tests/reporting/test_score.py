"""Tests for mutation score calculation."""

from __future__ import annotations

import pytest

from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


@pytest.mark.small
class DescribeMutationScore:
    """Tests for MutationScore dataclass."""

    def it_stores_total(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED) for _ in range(10)]
        score = MutationScore.from_results(results)
        assert score.total == 10

    def it_stores_zapped_count(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        assert score.zapped == 2

    def it_stores_survived_count(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        assert score.survived == 2

    def it_stores_timeout_count(self, make_result):
        results = [
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.TIMEOUT),
        ]
        score = MutationScore.from_results(results)
        assert score.timeout == 2

    def it_stores_error_count(self, make_result):
        results = [
            make_result(GremlinResultStatus.ERROR),
        ]
        score = MutationScore.from_results(results)
        assert score.error == 1

    def it_stores_pardoned_count(self, make_result):
        results = [
            make_result(GremlinResultStatus.PARDONED),
            make_result(GremlinResultStatus.PARDONED),
            make_result(GremlinResultStatus.ZAPPED),
        ]
        score = MutationScore.from_results(results)
        assert score.pardoned == 2


@pytest.mark.small
class DescribeMutationScorePercentage:
    """Tests for mutation score percentage calculation."""

    def it_percentage_when_all_zapped(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED) for _ in range(10)]
        score = MutationScore.from_results(results)
        assert score.percentage == 100.0

    def it_percentage_when_none_zapped(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED) for _ in range(10)]
        score = MutationScore.from_results(results)
        assert score.percentage == 0.0

    def it_percentage_with_mixed_results(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),  # 9 zapped
            make_result(GremlinResultStatus.SURVIVED),  # 1 survived
        ]
        score = MutationScore.from_results(results)
        assert score.percentage == 90.0

    def it_percentage_with_no_results(self):
        score = MutationScore.from_results([])
        assert score.percentage == 0.0

    def it_percentage_treats_timeout_as_zapped(self, make_result):
        """Timeouts count as zapped for score calculation (test caught something)."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        # 2 out of 3 (zapped + timeout) = 66.67%
        assert score.percentage == pytest.approx(66.67, rel=0.01)

    def it_percentage_denominator_excludes_pardoned_gremlins(self, make_result):
        """Pardoned gremlins are excluded from the percentage denominator."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.PARDONED),
            make_result(GremlinResultStatus.PARDONED),
        ]
        score = MutationScore.from_results(results)
        # 2 zapped out of 2 effective (4 total - 2 pardoned) = 100.0%
        assert score.total == 4
        assert score.pardoned == 2
        assert score.percentage == 100.0


@pytest.mark.small
class DescribeMutationScoreByFile:
    """Tests for file-level score breakdown."""

    def it_returns_dict_keyed_by_file_path(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, file_path='auth.py'),
            make_result(GremlinResultStatus.SURVIVED, file_path='utils.py'),
        ]
        score = MutationScore.from_results(results)
        file_scores = score.by_file()
        assert set(file_scores.keys()) == {'auth.py', 'utils.py'}

    def it_calculates_per_file_score(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, file_path='auth.py'),
            make_result(GremlinResultStatus.ZAPPED, file_path='auth.py'),
            make_result(GremlinResultStatus.SURVIVED, file_path='utils.py'),
        ]
        score = MutationScore.from_results(results)
        file_scores = score.by_file()
        assert file_scores['auth.py'].percentage == 100.0
        assert file_scores['utils.py'].percentage == 0.0


@pytest.mark.small
class DescribeMutationScoreTopSurvivors:
    """Tests for getting top surviving gremlins."""

    def it_top_survivors_returns_survived_results(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        survivors = score.top_survivors()
        assert len(survivors) == 2
        assert all(r.is_survived for r in survivors)

    def it_top_survivors_limits_results(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED) for _ in range(10)]
        score = MutationScore.from_results(results)
        survivors = score.top_survivors(limit=3)
        assert len(survivors) == 3

    def it_top_survivors_returns_empty_when_none_survived(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED) for _ in range(5)]
        score = MutationScore.from_results(results)
        survivors = score.top_survivors()
        assert len(survivors) == 0
