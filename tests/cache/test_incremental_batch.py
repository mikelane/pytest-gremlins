"""Tests for batch operations in IncrementalCache."""

from pathlib import Path

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache

from .commit_counter import record_commits


@pytest.mark.medium
class DescribeIncrementalCacheBatchOperations:
    """Tests for batch cache write support."""

    def it_batches_writes_in_deferred_cache_results(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """cache_result_deferred defers every write to a single commit on flush."""
        cache_dir = tmp_path / '.gremlins_cache'
        num_gremlins = 100

        commits = record_commits(monkeypatch)
        with IncrementalCache(cache_dir) as cache:
            commits.clear()
            for i in range(num_gremlins):
                cache.cache_result_deferred(
                    f'gremlin_{i}',
                    'source_hash',
                    {'test': 'hash'},
                    {'status': 'zapped'},
                )
            commits_before_flush = len(commits)
            cache.flush()
            commits_after_flush = len(commits)

        assert commits_before_flush == 0
        assert commits_after_flush == 1

        with IncrementalCache(cache_dir) as cache:
            results = [
                cache.get_cached_result(f'gremlin_{i}', 'source_hash', {'test': 'hash'}) for i in range(num_gremlins)
            ]

        assert results == [{'status': 'zapped'}] * num_gremlins

    def it_close_flushes_deferred_writes(self, tmp_path: Path) -> None:
        """Closing the cache flushes any pending deferred writes."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir) as cache:
            cache.cache_result_deferred('g1', 'src', {'t': 'h'}, {'status': 'zapped'})
            # No explicit flush

        # Data should be persisted
        with IncrementalCache(cache_dir) as cache:
            result = cache.get_cached_result('g1', 'src', {'t': 'h'})
            assert result == {'status': 'zapped'}
