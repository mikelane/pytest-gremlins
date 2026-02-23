"""Tests for the IncrementalCache coordinator.

The IncrementalCache orchestrates content hashing and result storage to
implement the invalidation rules for incremental analysis.
"""

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache


@pytest.mark.medium
class DescribeIncrementalCache:
    """Tests for IncrementalCache class."""

    def it_creates_cache_directory(self, tmp_path):
        """Cache creates storage directory at initialization."""
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir):
            pass

        assert cache_dir.exists()

    def it_returns_none_on_cache_miss(self, tmp_path):
        """get_cached_result returns None for cache miss."""
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            result = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='abc123',
                test_hashes={'test_foo': 'def456'},
            )

        assert result is None

    def it_caches_and_retrieves_result(self, tmp_path):
        """Cached results can be retrieved with same hashes."""
        result_data = {
            'gremlin_id': 'g001',
            'status': 'zapped',
            'killing_test': 'test_foo',
        }

        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='abc123',
                test_hashes={'test_foo': 'def456'},
                result=result_data,
            )

            retrieved = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='abc123',
                test_hashes={'test_foo': 'def456'},
            )

        assert retrieved == result_data

    def it_invalidates_cache_when_source_file_changes(self, tmp_path):
        """Changed source hash causes cache miss."""
        result_data = {'gremlin_id': 'g001', 'status': 'zapped'}

        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='original_hash',
                test_hashes={'test_foo': 'test_hash'},
                result=result_data,
            )

            # Same gremlin, different source hash
            retrieved = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='modified_hash',
                test_hashes={'test_foo': 'test_hash'},
            )

        assert retrieved is None

    def it_invalidates_cache_when_test_file_is_modified(self, tmp_path):
        """Changed test hash causes cache miss."""
        result_data = {'gremlin_id': 'g001', 'status': 'zapped'}

        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'original_test_hash'},
                result=result_data,
            )

            # Same gremlin, different test hash
            retrieved = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'modified_test_hash'},
            )

        assert retrieved is None

    def it_invalidates_cache_when_new_test_is_added(self, tmp_path):
        """Adding a new test causes cache miss."""
        result_data = {'gremlin_id': 'g001', 'status': 'survived'}

        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
                result=result_data,
            )

            # Same gremlin, but with an additional test
            retrieved = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={
                    'test_foo': 'test_hash',
                    'test_bar': 'new_test_hash',
                },
            )

        assert retrieved is None

    def it_deleted_test_invalidates_cache(self, tmp_path):
        """Removing a test causes cache miss."""
        result_data = {'gremlin_id': 'g001', 'status': 'zapped'}

        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={
                    'test_foo': 'test_hash_foo',
                    'test_bar': 'test_hash_bar',
                },
                result=result_data,
            )

            # Same gremlin, but with one test removed
            retrieved = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash_foo'},
            )

        assert retrieved is None

    def it_unchanged_code_returns_cached_result(self, tmp_path):
        """Identical hashes return cached result instantly."""
        result_data = {'gremlin_id': 'g001', 'status': 'survived'}
        test_hashes = {
            'test_foo': 'hash_foo',
            'test_bar': 'hash_bar',
            'test_baz': 'hash_baz',
        }

        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes=test_hashes,
                result=result_data,
            )

            retrieved = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes=test_hashes,
            )

        assert retrieved == result_data

    def it_caches_different_gremlins_separately(self, tmp_path):
        """Different gremlins in same file have separate cache entries."""
        result_g001 = {'gremlin_id': 'g001', 'status': 'zapped'}
        result_g002 = {'gremlin_id': 'g002', 'status': 'survived'}

        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
                result=result_g001,
            )
            cache.cache_result(
                gremlin_id='g002',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
                result=result_g002,
            )

            retrieved_g001 = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
            )
            retrieved_g002 = cache.get_cached_result(
                gremlin_id='g002',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
            )

        assert retrieved_g001 == result_g001
        assert retrieved_g002 == result_g002

    def it_persists_cache_between_sessions(self, tmp_path):
        """Cache data persists after closing and reopening."""
        cache_dir = tmp_path / '.gremlins_cache'
        result_data = {'gremlin_id': 'g001', 'status': 'zapped'}

        with IncrementalCache(cache_dir) as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
                result=result_data,
            )

        with IncrementalCache(cache_dir) as cache:
            retrieved = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
            )

        assert retrieved == result_data

    def it_invalidate_by_source_file(self, tmp_path):
        """invalidate_file removes all cached results for a file."""
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            # Cache results for two gremlins in the same file
            cache.cache_result(
                gremlin_id='file1:g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
                result={'status': 'zapped'},
            )
            cache.cache_result(
                gremlin_id='file1:g002',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
                result={'status': 'survived'},
            )
            # Cache result for gremlin in different file
            cache.cache_result(
                gremlin_id='file2:g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
                result={'status': 'zapped'},
            )

            cache.invalidate_file('file1')

            # file1 gremlins should be invalidated
            assert (
                cache.get_cached_result(
                    gremlin_id='file1:g001',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                )
                is None
            )
            assert (
                cache.get_cached_result(
                    gremlin_id='file1:g002',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                )
                is None
            )

            # file2 gremlins should still be cached
            assert (
                cache.get_cached_result(
                    gremlin_id='file2:g001',
                    source_hash='source_hash',
                    test_hashes={'test_foo': 'test_hash'},
                )
                is not None
            )

    def it_clear_removes_all_cache(self, tmp_path):
        """clear removes all cached results."""
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='hash1',
                test_hashes={'test': 'hash'},
                result={'status': 'zapped'},
            )
            cache.cache_result(
                gremlin_id='g002',
                source_hash='hash2',
                test_hashes={'test': 'hash'},
                result={'status': 'survived'},
            )

            cache.clear()

            assert (
                cache.get_cached_result(
                    gremlin_id='g001',
                    source_hash='hash1',
                    test_hashes={'test': 'hash'},
                )
                is None
            )

    def it_returns_cache_statistics(self, tmp_path):
        """get_stats returns cache hit/miss statistics."""
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='hash',
                test_hashes={'test': 'hash'},
                result={'status': 'zapped'},
            )

            # Cache hit
            cache.get_cached_result(
                gremlin_id='g001',
                source_hash='hash',
                test_hashes={'test': 'hash'},
            )
            # Cache miss
            cache.get_cached_result(
                gremlin_id='g002',
                source_hash='hash',
                test_hashes={'test': 'hash'},
            )

            stats = cache.get_stats()

        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert stats['total_entries'] == 1

    def it_supports_empty_test_hashes(self, tmp_path):
        """Cache works with empty test_hashes (no tests cover gremlin)."""
        result_data = {'gremlin_id': 'g001', 'status': 'survived'}

        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={},
                result=result_data,
            )

            retrieved = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='source_hash',
                test_hashes={},
            )

        assert retrieved == result_data

    def test_invalidate_file_with_no_matching_entries_is_noop(self, tmp_path) -> None:
        """invalidate_file('nonexistent') does not affect existing entries."""
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='file1:g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
                result={'status': 'zapped'},
            )

            cache.invalidate_file('nonexistent')

            result = cache.get_cached_result(
                gremlin_id='file1:g001',
                source_hash='source_hash',
                test_hashes={'test_foo': 'test_hash'},
            )
            assert result == {'status': 'zapped'}
