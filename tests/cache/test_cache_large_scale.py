"""Large-scale integration tests for cache performance.

These tests simulate a more realistic workload with many gremlins to identify
scaling issues with the cache.
"""

from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from typing import (
    TYPE_CHECKING,
    Any,
)

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_GREMLIN_ARGS = (
    '--gremlins',
    '--gremlin-targets=validator.py',
    '--gremlin-operators=comparison',
    '--gremlin-cache',
    '--gremlin-report=json',
)
_REPORT_RELATIVE_PATH = ('coverage', 'gremlins', 'gremlins.json')


def _overwrite_cached_statuses(db_path: Path, *, only_status: str, new_status: str) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        for cache_key, result_json in conn.execute('SELECT cache_key, result_json FROM results').fetchall():
            entry = json.loads(result_json)
            if entry['status'] == only_status:
                entry['status'] = new_status
                conn.execute('UPDATE results SET result_json = ? WHERE cache_key = ?', (json.dumps(entry), cache_key))
        conn.commit()


@pytest.mark.medium
class DescribeCacheLargeScale:
    """Tests for cache with larger number of gremlins."""

    @pytest.fixture
    def large_project(self, pytester_with_markers: pytest.Pytester) -> pytest.Pytester:
        """Write a project whose validator.py yields about a dozen comparison gremlins over 26 tests.

        Every gremlin runs through a full pytest bootstrap, so the workload is kept small enough for
        the medium time limit.
        """
        # Create source files similar to benchmark
        pytester_with_markers.makepyfile(
            calculator="""
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def power(base, exp):
    if exp < 0:
        raise ValueError("Negative exponent")
    result = 1
    for _ in range(exp):
        result *= base
    return result
            """,
        )

        pytester_with_markers.makepyfile(
            validator="""
def is_adult(age):
    return age >= 18

def is_valid_percentage(value):
    return value >= 0 and value <= 100

def is_positive(n):
    return n > 0

def is_negative(n):
    return n < 0

def is_zero(n):
    return n == 0

def is_small(n):
    return n < 1000
            """,
        )

        # Create comprehensive tests
        pytester_with_markers.makepyfile(
            test_calculator="""
import pytest
from calculator import add, subtract, multiply, divide, power

@pytest.mark.medium
class TestAdd:
    def test_positive(self):
        assert add(2, 3) == 5

    def test_negative(self):
        assert add(-2, -3) == -5

    def test_zero(self):
        assert add(0, 5) == 5

@pytest.mark.medium
class TestSubtract:
    def test_positive(self):
        assert subtract(5, 3) == 2

    def test_negative_result(self):
        assert subtract(3, 5) == -2

@pytest.mark.medium
class TestMultiply:
    def test_positive(self):
        assert multiply(3, 4) == 12

    def test_zero(self):
        assert multiply(5, 0) == 0

@pytest.mark.medium
class TestDivide:
    def test_even(self):
        assert divide(10, 2) == 5.0

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            divide(10, 0)

@pytest.mark.medium
class TestPower:
    def test_positive(self):
        assert power(2, 3) == 8

    def test_zero_exp(self):
        assert power(5, 0) == 1

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            power(2, -1)
            """,
        )

        pytester_with_markers.makepyfile(
            test_validator="""
import pytest
from validator import is_adult, is_valid_percentage, is_positive, is_negative, is_zero, is_small

@pytest.mark.medium
class TestIsAdult:
    def test_at_18(self):
        assert is_adult(18) is True

    def test_over_18(self):
        assert is_adult(25) is True

    def test_under_18(self):
        assert is_adult(17) is False

@pytest.mark.medium
class TestIsValidPercentage:
    def test_zero(self):
        assert is_valid_percentage(0) is True

    def test_hundred(self):
        assert is_valid_percentage(100) is True

    def test_negative(self):
        assert is_valid_percentage(-1) is False

    def test_over_hundred(self):
        assert is_valid_percentage(101) is False

@pytest.mark.medium
class TestIsPositive:
    def test_positive(self):
        assert is_positive(1) is True

    def test_zero(self):
        assert is_positive(0) is False

@pytest.mark.medium
class TestIsNegative:
    def test_negative(self):
        assert is_negative(-1) is True

    def test_zero(self):
        assert is_negative(0) is False

@pytest.mark.medium
class TestIsZero:
    def test_zero(self):
        assert is_zero(0) is True

    def test_positive(self):
        assert is_zero(1) is False

@pytest.mark.medium
class TestIsSmall:
    def test_far_below_the_limit(self):
        assert is_small(5) is True
            """,
        )

        return pytester_with_markers

    def _run_with_json_report(self, pytester: pytest.Pytester) -> tuple[pytest.RunResult, list[dict[str, Any]]]:
        report_path = pytester.path.joinpath(*_REPORT_RELATIVE_PATH)
        report_path.unlink(missing_ok=True)
        result = pytester.runpytest(*_GREMLIN_ARGS)
        report = json.loads(report_path.read_text())
        verdicts = sorted(report['results'], key=lambda entry: entry['gremlin_id'])
        return result, [{key: entry.get(key) for key in ('gremlin_id', 'status', 'killing_test')} for entry in verdicts]

    def it_returns_identical_scores_on_warm_cache_rerun_with_many_gremlins(
        self,
        large_project: pytest.Pytester,
    ) -> None:
        """Cache replays the cold run's verdicts on a warm rerun, with every gremlin served from the cache."""
        _, cold_verdicts = self._run_with_json_report(large_project)

        warm_result, warm_verdicts = self._run_with_json_report(large_project)

        warm_result.assert_outcomes(passed=26)
        assert len(cold_verdicts) > 0
        assert warm_verdicts == cold_verdicts
        warm_result.stdout.fnmatch_lines([f'Cache: {len(cold_verdicts)} hits, 0 misses (100% hit rate)'])

    def it_reports_both_zapped_and_survived_verdicts_in_the_cold_run(
        self,
        large_project: pytest.Pytester,
    ) -> None:
        """The workload has survivors and kills, so a cache fabricating either kind changes the verdicts."""
        _, cold_verdicts = self._run_with_json_report(large_project)

        assert {verdict['status'] for verdict in cold_verdicts} == {'zapped', 'survived'}

    @pytest.mark.parametrize(
        ('original_status', 'fabricated_status'),
        [('survived', 'zapped'), ('zapped', 'survived')],
    )
    def it_detects_a_cache_that_fabricates_verdicts_of_one_kind(
        self,
        large_project: pytest.Pytester,
        original_status: str,
        fabricated_status: str,
    ) -> None:
        """Rewriting every cached verdict of one kind changes the warm verdicts."""
        _, cold_verdicts = self._run_with_json_report(large_project)
        _overwrite_cached_statuses(
            large_project.path / '.gremlins_cache' / 'results.db',
            only_status=original_status,
            new_status=fabricated_status,
        )

        _, warm_verdicts = self._run_with_json_report(large_project)

        assert warm_verdicts != cold_verdicts

    def it_fails_loudly_when_the_warm_run_writes_no_report(
        self,
        large_project: pytest.Pytester,
    ) -> None:
        """A stale report from the cold run is never read as the warm run's report."""
        self._run_with_json_report(large_project)
        report_path = large_project.path.joinpath(*_REPORT_RELATIVE_PATH)
        report_path.unlink()
        report_path.mkdir()

        with pytest.raises((OSError, json.JSONDecodeError)):
            self._run_with_json_report(large_project)
