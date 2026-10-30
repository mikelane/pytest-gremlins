"""A cached verdict is reused across mutant timeouts only where the new limit cannot change it (#567)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache import incremental
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.types import CachedGremlinResult

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

TESTS = {'test_a': 'h'}


def _result(status: str, elapsed_seconds: float | None) -> CachedGremlinResult:
    millis = None if elapsed_seconds is None else elapsed_seconds * 1000
    return CachedGremlinResult(status=status, killing_test=None, execution_time_ms=millis)


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[IncrementalCache]:
    incremental = IncrementalCache(tmp_path / 'cache')
    yield incremental
    incremental.close()


@pytest.mark.medium
class DescribeNonTimeoutReuse:
    """A ZAPPED, SURVIVED or ERROR verdict is reused when it would have finished inside the new limit."""

    @pytest.mark.parametrize('status', ['zapped', 'survived', 'error'])
    @pytest.mark.parametrize('new_limit', [31, 100])
    def it_hits_when_elapsed_time_is_below_the_new_limit(
        self, cache: IncrementalCache, status: str, new_limit: int
    ) -> None:
        cache.cache_result('g1', 'src', TESTS, _result(status, 5.0), mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=new_limit) == _result(status, 5.0)

    def it_hits_at_a_lower_limit_that_still_exceeds_the_elapsed_time(self, cache: IncrementalCache) -> None:
        cache.cache_result('g1', 'src', TESTS, _result('zapped', 5.0), mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=6) == _result('zapped', 5.0)

    @pytest.mark.parametrize('new_limit', [5, 4, 1])
    def it_misses_when_elapsed_time_reaches_the_new_limit(self, cache: IncrementalCache, new_limit: int) -> None:
        cache.cache_result('g1', 'src', TESTS, _result('survived', 5.0), mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=new_limit) is None

    def it_misses_at_a_different_limit_when_elapsed_time_is_unknown(self, cache: IncrementalCache) -> None:
        cache.cache_result('g1', 'src', TESTS, _result('zapped', None), mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=31) is None

    def it_hits_at_the_same_limit_when_elapsed_time_is_unknown(self, cache: IncrementalCache) -> None:
        cache.cache_result('g1', 'src', TESTS, _result('zapped', None), mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=30) == _result('zapped', None)

    def it_hits_for_a_deferred_write_once_flushed(self, cache: IncrementalCache) -> None:
        cache.cache_result_deferred('g1', 'src', TESTS, _result('zapped', 5.0), mutant_timeout=30)
        cache.flush()

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=31) == _result('zapped', 5.0)

    def it_returns_the_result_without_bookkeeping_fields(self, cache: IncrementalCache) -> None:
        cache.cache_result('g1', 'src', TESTS, {'status': 'zapped'}, mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=30) == {'status': 'zapped'}


@pytest.mark.medium
class DescribeTimeoutReuse:
    """A TIMEOUT verdict is reused only at the limit it was confirmed under."""

    @pytest.mark.parametrize('new_limit', [31, 60])
    def it_misses_above_the_original_limit(self, cache: IncrementalCache, new_limit: int) -> None:
        cache.cache_result('g1', 'src', TESTS, _result('timeout', 30.0), mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=new_limit) is None

    @pytest.mark.parametrize('new_limit', [29, 15, 1])
    def it_misses_below_the_original_limit_because_the_confirmation_may_not_hold(
        self, cache: IncrementalCache, new_limit: int
    ) -> None:
        cache.cache_result('g1', 'src', TESTS, _result('timeout', 30.0), mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=new_limit) is None

    def it_hits_at_the_original_limit(self, cache: IncrementalCache) -> None:
        cache.cache_result('g1', 'src', TESTS, _result('timeout', 30.0), mutant_timeout=30)

        assert cache.get_cached_result('g1', 'src', TESTS, mutant_timeout=30) == _result('timeout', 30.0)


@pytest.mark.medium
class DescribeOldFormatEntries:
    """Entries written by an older cache version are discarded, not served."""

    def it_prunes_entries_from_other_cache_versions_on_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with monkeypatch.context() as older:
            older.setattr(incremental, 'RUNNER_FIDELITY_VERSION', 'rf18')
            previous = IncrementalCache(tmp_path / 'cache')
            previous.cache_result('g1', 'src', TESTS, _result('zapped', 1.0), mutant_timeout=30)
            previous.close()

        reopened = IncrementalCache(tmp_path / 'cache')
        try:
            assert reopened.get_stats()['total_entries'] == 0
        finally:
            reopened.close()
