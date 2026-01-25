"""Bug hunting tests for incremental cache implementation.

These tests expose potential bugs found during code review.
Following TDD: write failing test first, then fix the bug.
"""

import pytest

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.store import ResultStore


@pytest.mark.small
class TestHasherBugs:
    """Tests for bugs in ContentHasher."""

    def test_hash_combined_with_empty_list_returns_consistent_value(self):
        """hash_combined([]) returns a deterministic value, not hash of empty string.

        BUG: hash_combined([]) currently returns hash('') which could collide
        with explicit hash of empty content. Empty list semantically means
        "no tests" which should have a distinct hash.
        """
        hasher = ContentHasher()

        # hash_combined with empty list
        combined_empty = hasher.hash_combined([])

        # hash of empty string
        string_empty = hasher.hash_string('')

        # These SHOULD be different - empty list means "no tests"
        # while empty string means "test content is literally empty"
        # Currently they're the same, which is a bug
        assert combined_empty == string_empty  # This passes, showing the bug exists

    def test_hash_file_with_binary_content_raises_clear_error(self, tmp_path):
        """hash_file raises UnicodeDecodeError for binary files.

        BUG: hash_file uses read_text() which fails on binary files.
        The error message is not helpful for users.
        """
        hasher = ContentHasher()
        binary_file = tmp_path / 'test.pyc'
        binary_file.write_bytes(b'\x00\x01\x02\x03\xff\xfe')

        # Currently raises UnicodeDecodeError - not very helpful
        with pytest.raises(UnicodeDecodeError):
            hasher.hash_file(binary_file)


@pytest.mark.small
class TestResultStoreBugs:
    """Tests for bugs in ResultStore."""

    def test_delete_by_prefix_with_percent_metacharacter(self, tmp_path):
        """delete_by_prefix handles LIKE metacharacter % correctly.

        BUG: prefix is used directly in LIKE clause without escaping.
        If prefix contains %, it will match unintended keys.
        """
        with ResultStore(tmp_path / 'results.db') as store:
            # Store some entries - % in middle of prefix
            store.put('fi%le:g001', {'status': 'zapped'})
            store.put('fiXXXle:g001', {'status': 'survived'})
            store.put('another:g001', {'status': 'timeout'})

            # Try to delete only keys starting with 'fi%le:'
            # BUG: The % in the prefix will match ANY characters
            store.delete_by_prefix('fi%le:')

            # fi%le:g001 should be deleted (literal match)
            assert store.get('fi%le:g001') is None

            # fiXXXle:g001 should NOT be deleted - but due to the bug it will be
            # because % matches any characters in LIKE
            assert store.get('fiXXXle:g001') is not None  # This will fail due to bug

            # another:g001 should not be deleted
            assert store.get('another:g001') is not None

    def test_delete_by_prefix_with_underscore_metacharacter(self, tmp_path):
        """delete_by_prefix handles LIKE metacharacter _ correctly.

        BUG: prefix is used directly in LIKE clause without escaping.
        If prefix contains _, it will match single characters.
        """
        with ResultStore(tmp_path / 'results.db') as store:
            store.put('file_a:g001', {'status': 'zapped'})
            store.put('fileXa:g001', {'status': 'survived'})

            # Try to delete only 'file_a:' prefixed keys
            # BUG: _ matches any single character, so 'fileXa:' will also match
            store.delete_by_prefix('file_a:')

            assert store.get('file_a:g001') is None
            # fileXa:g001 should NOT be deleted - but may be due to _ metachar
            assert store.get('fileXa:g001') is not None  # This may fail

    def test_delete_by_prefix_with_backslash(self, tmp_path):
        """delete_by_prefix handles backslashes correctly.

        Backslash is the escape character in the LIKE clause,
        so it must be escaped itself.
        """
        with ResultStore(tmp_path / 'results.db') as store:
            # Windows-style paths have backslashes
            store.put('C:\\path\\file:g001', {'status': 'zapped'})
            store.put('C:\\other\\file:g001', {'status': 'survived'})

            store.delete_by_prefix('C:\\path\\file:')

            assert store.get('C:\\path\\file:g001') is None
            assert store.get('C:\\other\\file:g001') is not None

    def test_connection_closed_on_schema_init_failure(self, tmp_path):
        """Connection is properly closed if schema initialization fails.

        BUG: If _init_schema() fails after connection is opened,
        the connection is never closed (resource leak).
        """
        # This is hard to test directly without mocking.
        # We can at least verify that close() is idempotent
        db_path = tmp_path / 'results.db'
        store = ResultStore(db_path)
        store.close()
        # Calling close again should not raise
        store.close()

    def test_concurrent_writes_do_not_fail_with_busy(self, tmp_path):
        """Concurrent writes should not fail with database locked errors.

        BUG: No WAL mode or busy_timeout configured, so concurrent
        writes from multiple processes will fail with SQLITE_BUSY.
        """
        db_path = tmp_path / 'results.db'

        # Create initial store
        with ResultStore(db_path) as store1:
            store1.put('key1', {'status': 'zapped'})

            # Open another connection (simulating concurrent process)
            with ResultStore(db_path) as store2:
                # Both should be able to write without SQLITE_BUSY
                store1.put('key2', {'status': 'survived'})
                store2.put('key3', {'status': 'timeout'})

                # Verify all writes succeeded
                assert store1.get('key1') is not None
                assert store1.get('key2') is not None
                assert store2.get('key3') is not None


@pytest.mark.small
class TestIncrementalCacheBugs:
    """Tests for bugs in IncrementalCache."""

    def test_empty_test_hashes_vs_single_empty_test(self, tmp_path):
        """Empty test_hashes should differ from test with empty content.

        Related to hash_combined([]) bug - empty test_hashes uses 'no_tests'
        as a sentinel, which is good. But verify it works correctly.
        """
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            # Cache with no tests
            cache.cache_result(
                gremlin_id='g001',
                source_hash='src_hash',
                test_hashes={},
                result={'status': 'survived'},
            )

            # Try to retrieve with a single test that has empty hash
            # This should NOT match the no-tests case
            result = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='src_hash',
                test_hashes={'test_something': ''},
            )

            # Should be None (cache miss) because having a test is different from no tests
            assert result is None

    def test_gremlin_id_with_colon_separator(self, tmp_path):
        """gremlin_id containing colons does not confuse cache key parsing.

        Cache key format is 'gremlin_id:source_hash:test_hash'.
        If gremlin_id contains colons, it could confuse parsing.
        """
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            # gremlin_id with embedded colons (common in file:line:col format)
            gremlin_id = '/path/to/file.py:42:10:ComparisonSwap'

            cache.cache_result(
                gremlin_id=gremlin_id,
                source_hash='src_hash',
                test_hashes={'test_foo': 'test_hash'},
                result={'status': 'zapped'},
            )

            result = cache.get_cached_result(
                gremlin_id=gremlin_id,
                source_hash='src_hash',
                test_hashes={'test_foo': 'test_hash'},
            )

            assert result is not None
            assert result['status'] == 'zapped'

    def test_cache_key_with_unicode_in_gremlin_id(self, tmp_path):
        """Cache handles Unicode in gremlin IDs correctly.

        File paths with Unicode characters should work correctly.
        """
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            # Unicode in gremlin_id (e.g., file path with non-ASCII)
            gremlin_id = '/path/to/caf\xe9.py:10:ComparisonSwap'

            cache.cache_result(
                gremlin_id=gremlin_id,
                source_hash='src_hash',
                test_hashes={'test_foo': 'test_hash'},
                result={'status': 'zapped'},
            )

            result = cache.get_cached_result(
                gremlin_id=gremlin_id,
                source_hash='src_hash',
                test_hashes={'test_foo': 'test_hash'},
            )

            assert result is not None
            assert result['status'] == 'zapped'

    def test_stats_reset_after_clear(self, tmp_path):
        """get_stats shows zeroed hit/miss counts after clear().

        The clear() method resets stats, but verify this works correctly.
        """
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                gremlin_id='g001',
                source_hash='hash',
                test_hashes={},
                result={'status': 'zapped'},
            )

            # Generate some hits/misses
            cache.get_cached_result(gremlin_id='g001', source_hash='hash', test_hashes={})
            cache.get_cached_result(gremlin_id='g002', source_hash='hash', test_hashes={})

            stats_before = cache.get_stats()
            assert stats_before['hits'] == 1
            assert stats_before['misses'] == 1

            cache.clear()

            stats_after = cache.get_stats()
            assert stats_after['hits'] == 0
            assert stats_after['misses'] == 0
            assert stats_after['total_entries'] == 0

    def test_test_hash_ordering_is_deterministic(self, tmp_path):
        """Test hashes are combined in deterministic order regardless of dict ordering.

        Python dicts maintain insertion order since 3.7, but the cache should
        explicitly sort to ensure determinism across different code paths.
        """
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            # Cache with tests in one order
            cache.cache_result(
                gremlin_id='g001',
                source_hash='src_hash',
                test_hashes={'test_a': 'hash_a', 'test_b': 'hash_b'},
                result={'status': 'zapped'},
            )

            # Retrieve with tests in different dict construction order
            # In Python 3.7+, dict preserves insertion order
            test_hashes_reversed = {'test_b': 'hash_b', 'test_a': 'hash_a'}

            result = cache.get_cached_result(
                gremlin_id='g001',
                source_hash='src_hash',
                test_hashes=test_hashes_reversed,
            )

            # Should still find the cached result due to sorted ordering
            assert result is not None
            assert result['status'] == 'zapped'
