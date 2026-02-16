"""Tests for SQLite-based result cache.

The ResultStore persists gremlin results keyed by content hashes,
enabling instant cache hits for unchanged code.
"""

import pytest

from pytest_gremlins.cache.store import ResultStore
from pytest_gremlins.reporting.results import GremlinResultStatus


@pytest.mark.medium
class TestResultStore:
    """Tests for ResultStore class."""

    def test_store_creates_database_file(self, tmp_path):
        """Store creates SQLite database at specified path."""
        db_path = tmp_path / '.gremlins_cache' / 'results.db'

        with ResultStore(db_path):
            pass

        assert db_path.exists()

    def test_store_creates_parent_directories(self, tmp_path):
        """Store creates parent directories if they don't exist."""
        db_path = tmp_path / 'nested' / 'deep' / 'results.db'

        with ResultStore(db_path):
            pass

        assert db_path.exists()

    def test_get_returns_none_for_unknown_key(self, tmp_path):
        """get returns None for cache miss."""
        with ResultStore(tmp_path / 'results.db') as store:
            result = store.get('nonexistent_key')

        assert result is None

    def test_put_and_get_retrieves_stored_result(self, tmp_path):
        """put stores result that can be retrieved with get."""
        cache_key = 'abc123'
        result = {
            'gremlin_id': 'g001',
            'status': GremlinResultStatus.ZAPPED.value,
            'killing_test': 'test_foo',
        }

        with ResultStore(tmp_path / 'results.db') as store:
            store.put(cache_key, result)
            retrieved = store.get(cache_key)

        assert retrieved == result

    def test_put_overwrites_existing_entry(self, tmp_path):
        """put replaces existing entry with same key."""
        cache_key = 'abc123'
        original = {'gremlin_id': 'g001', 'status': 'zapped'}
        updated = {'gremlin_id': 'g001', 'status': 'survived'}

        with ResultStore(tmp_path / 'results.db') as store:
            store.put(cache_key, original)
            store.put(cache_key, updated)
            retrieved = store.get(cache_key)

        assert retrieved == updated

    def test_store_persists_across_instances(self, tmp_path):
        """Data persists when store is reopened."""
        db_path = tmp_path / 'results.db'
        cache_key = 'persistent_key'
        result = {'gremlin_id': 'g001', 'status': 'zapped'}

        with ResultStore(db_path) as store1:
            store1.put(cache_key, result)

        with ResultStore(db_path) as store2:
            retrieved = store2.get(cache_key)

        assert retrieved == result

    def test_delete_removes_entry(self, tmp_path):
        """delete removes entry from cache."""
        cache_key = 'to_delete'
        result = {'gremlin_id': 'g001', 'status': 'zapped'}

        with ResultStore(tmp_path / 'results.db') as store:
            store.put(cache_key, result)
            store.delete(cache_key)
            retrieved = store.get(cache_key)

        assert retrieved is None

    def test_delete_nonexistent_key_is_noop(self, tmp_path):
        """delete on missing key does nothing (no error)."""
        with ResultStore(tmp_path / 'results.db') as store:
            store.delete('nonexistent')  # No exception raised

    def test_clear_removes_all_entries(self, tmp_path):
        """clear removes all cached entries."""
        with ResultStore(tmp_path / 'results.db') as store:
            store.put('key1', {'status': 'zapped'})
            store.put('key2', {'status': 'survived'})
            store.clear()
            result1 = store.get('key1')
            result2 = store.get('key2')

        assert result1 is None
        assert result2 is None

    def test_has_returns_true_for_existing_key(self, tmp_path):
        """has returns True when key exists in cache."""
        with ResultStore(tmp_path / 'results.db') as store:
            store.put('exists', {'status': 'zapped'})
            result = store.has('exists')

        assert result is True

    def test_has_returns_false_for_missing_key(self, tmp_path):
        """has returns False when key not in cache."""
        with ResultStore(tmp_path / 'results.db') as store:
            result = store.has('missing')

        assert result is False

    def test_keys_returns_all_cache_keys(self, tmp_path):
        """keys returns list of all cached keys."""
        with ResultStore(tmp_path / 'results.db') as store:
            store.put('alpha', {'status': 'zapped'})
            store.put('beta', {'status': 'survived'})
            store.put('gamma', {'status': 'timeout'})
            keys = store.keys()

        assert set(keys) == {'alpha', 'beta', 'gamma'}

    def test_keys_returns_empty_list_when_empty(self, tmp_path):
        """keys returns empty list for empty cache."""
        with ResultStore(tmp_path / 'results.db') as store:
            keys = store.keys()

        assert keys == []

    def test_count_returns_number_of_entries(self, tmp_path):
        """count returns total number of cached entries."""
        with ResultStore(tmp_path / 'results.db') as store:
            store.put('key1', {'status': 'zapped'})
            store.put('key2', {'status': 'survived'})
            count = store.count()

        assert count == 2

    def test_count_returns_zero_when_empty(self, tmp_path):
        """count returns 0 for empty cache."""
        with ResultStore(tmp_path / 'results.db') as store:
            count = store.count()

        assert count == 0

    def test_context_manager_closes_connection(self, tmp_path):
        """Store can be used as context manager."""
        db_path = tmp_path / 'results.db'

        with ResultStore(db_path) as store:
            store.put('key', {'status': 'zapped'})

        # Reopening should work (connection was closed properly)
        with ResultStore(db_path) as store2:
            result = store2.get('key')

        assert result == {'status': 'zapped'}

    def test_stores_complex_nested_data(self, tmp_path):
        """Store handles complex nested data structures."""
        complex_result = {
            'gremlin_id': 'g001',
            'file_path': '/path/to/file.py',
            'line_number': 42,
            'status': 'survived',
            'tests_run': ['test_a', 'test_b', 'test_c'],
            'metadata': {
                'operator': 'comparison',
                'original': '<',
                'mutated': '<=',
            },
        }

        with ResultStore(tmp_path / 'results.db') as store:
            store.put('complex', complex_result)
            retrieved = store.get('complex')

        assert retrieved == complex_result

    def test_delete_by_prefix_removes_matching_keys(self, tmp_path):
        """delete_by_prefix removes all keys with given prefix."""
        with ResultStore(tmp_path / 'results.db') as store:
            store.put('file1:g001', {'status': 'zapped'})
            store.put('file1:g002', {'status': 'survived'})
            store.put('file2:g001', {'status': 'zapped'})
            store.delete_by_prefix('file1:')
            file1_g001 = store.get('file1:g001')
            file1_g002 = store.get('file1:g002')
            file2_g001 = store.get('file2:g001')

        assert file1_g001 is None
        assert file1_g002 is None
        assert file2_g001 is not None

    def test_corrupted_database_is_recreated(self, tmp_path, caplog):
        """Corrupted database file is deleted and recreated with warning."""
        db_path = tmp_path / 'results.db'
        db_path.write_bytes(b'not a valid sqlite database')

        with ResultStore(db_path) as store:
            store.put('key1', {'status': 'zapped'})
            retrieved = store.get('key1')

        assert retrieved == {'status': 'zapped'}
        assert 'corrupted' in caplog.text.lower()
