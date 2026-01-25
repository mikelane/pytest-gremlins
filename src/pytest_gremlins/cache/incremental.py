"""Incremental analysis cache coordinator.

The IncrementalCache orchestrates content hashing and result storage
to implement smart cache invalidation based on content changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.store import ResultStore


if TYPE_CHECKING:
    from pathlib import Path


class IncrementalCache:
    """Coordinator for incremental analysis caching.

    Combines content hashing with result storage to implement the
    incremental analysis invalidation rules:

    - Source file modified: cache miss (re-run gremlins in that file)
    - Test file modified: cache miss (re-run gremlins covered by those tests)
    - New test added: cache miss (re-run gremlins the new test covers)
    - Test deleted: cache miss (re-run gremlins that test was zapping)
    - Nothing changed: cache hit (return cached results instantly)

    The cache key is composed of:
    - gremlin_id: Unique identifier for the mutation
    - source_hash: SHA-256 hash of the source file content
    - test_hashes: Combined hash of all test files covering this gremlin

    Example:
        >>> cache = IncrementalCache(Path('.gremlins_cache'))
        >>> cache.cache_result('g001', 'src_hash', {'test_foo': 'hash'}, {'status': 'zapped'})
        >>> cache.get_cached_result('g001', 'src_hash', {'test_foo': 'hash'})
        {'status': 'zapped'}
    """

    def __init__(self, cache_dir: Path) -> None:
        """Initialize the incremental cache.

        Args:
            cache_dir: Directory to store cache files.
        """
        self._cache_dir = cache_dir
        self._hasher = ContentHasher()
        self._store = ResultStore(cache_dir / 'results.db')
        self._hits = 0
        self._misses = 0

    def _build_cache_key(
        self,
        gremlin_id: str,
        source_hash: str,
        test_hashes: dict[str, str],
    ) -> str:
        """Build a cache key from gremlin and content hashes.

        The key incorporates:
        - gremlin_id: unique mutation identifier
        - source_hash: content hash of the source file
        - test_hashes: combined hash of all relevant test files

        Args:
            gremlin_id: Unique identifier for the gremlin.
            source_hash: SHA-256 hash of the source file.
            test_hashes: Mapping of test name to content hash.

        Returns:
            A cache key string.
        """
        # Sort test hashes by name for deterministic ordering
        sorted_test_hashes = [
            test_hashes[name] for name in sorted(test_hashes.keys())
        ]
        combined_test_hash = self._hasher.hash_combined(sorted_test_hashes) if sorted_test_hashes else 'no_tests'

        return f'{gremlin_id}:{source_hash}:{combined_test_hash}'

    def get_cached_result(
        self,
        gremlin_id: str,
        source_hash: str,
        test_hashes: dict[str, str],
    ) -> dict[str, Any] | None:
        """Retrieve a cached result if available.

        Returns None (cache miss) if:
        - No cached result exists for this gremlin
        - Source file content has changed
        - Any relevant test file content has changed
        - Tests have been added or removed

        Args:
            gremlin_id: Unique identifier for the gremlin.
            source_hash: Current SHA-256 hash of the source file.
            test_hashes: Current mapping of test name to content hash.

        Returns:
            Cached result dictionary, or None if cache miss.
        """
        cache_key = self._build_cache_key(gremlin_id, source_hash, test_hashes)
        result = self._store.get(cache_key)

        if result is None:
            self._misses += 1
        else:
            self._hits += 1

        return result

    def cache_result(
        self,
        gremlin_id: str,
        source_hash: str,
        test_hashes: dict[str, str],
        result: dict[str, Any],
    ) -> None:
        """Cache a gremlin test result.

        The result is stored with a key that incorporates the gremlin ID
        and content hashes. Any change to source or test files will
        produce a different key, causing a cache miss.

        Args:
            gremlin_id: Unique identifier for the gremlin.
            source_hash: SHA-256 hash of the source file.
            test_hashes: Mapping of test name to content hash.
            result: The result dictionary to cache.
        """
        cache_key = self._build_cache_key(gremlin_id, source_hash, test_hashes)
        self._store.put(cache_key, result)

    def invalidate_file(self, file_prefix: str) -> None:
        """Invalidate all cached results for gremlins in a file.

        Removes all cache entries where the gremlin_id starts with
        the given prefix. Useful when a source file changes and all
        its gremlins need re-testing.

        Args:
            file_prefix: Prefix to match in gremlin IDs.
        """
        self._store.delete_by_prefix(f'{file_prefix}:')

    def clear(self) -> None:
        """Remove all cached results."""
        self._store.clear()
        self._hits = 0
        self._misses = 0

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with hits, misses, and total_entries counts.
        """
        return {
            'hits': self._hits,
            'misses': self._misses,
            'total_entries': self._store.count(),
        }

    def close(self) -> None:
        """Close the cache and release resources."""
        self._store.close()

    def __enter__(self) -> IncrementalCache:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object,
    ) -> None:
        """Context manager exit - closes the cache."""
        self.close()
