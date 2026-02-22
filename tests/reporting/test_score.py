"""Tests for mutation score calculation."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.reporting.score import MutationScore


@pytest.fixture
def make_gremlin():
    """Factory fixture for creating test gremlins."""
    counter = 0

    def _make_gremlin(file_path: str = 'test.py', line_number: int = 1) -> Gremlin:
        nonlocal counter
        counter += 1
        return Gremlin(
            gremlin_id=f'g{counter:03d}',
            file_path=file_path,
            line_number=line_number,
            original_node=ast.parse('x >= 0', mode='eval').body,
            mutated_node=ast.parse('x > 0', mode='eval').body,
            operator_name='comparison',
            description='>= to >',
        )

    return _make_gremlin


@pytest.fixture
def make_result(make_gremlin):
    """Factory fixture for creating test results."""

    def _make_result(
        status: GremlinResultStatus = GremlinResultStatus.ZAPPED,
        file_path: str = 'test.py',
        line_number: int = 1,
    ) -> GremlinResult:
        gremlin = make_gremlin(file_path=file_path, line_number=line_number)
        return GremlinResult(gremlin=gremlin, status=status)

    return _make_result


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
