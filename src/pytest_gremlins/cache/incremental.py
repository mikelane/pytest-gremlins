"""Incremental analysis cache coordinator.

The IncrementalCache orchestrates content hashing and result storage
to implement smart cache invalidation based on content changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.store import ResultStore

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from pytest_gremlins.cache.types import CachedGremlinResult


RUNNER_FIDELITY_VERSION = 'rf13'
"""Bump when a change to how tests are executed can alter cached verdicts.

``rf3`` retires every verdict cached by v1.9.0 or by interim builds, which judged tests with the
lightweight runner. That runner could fabricate verdicts (async, parametrized, fixture-taking tests,
conftest state, sys.path), so those results must never be reused.

``rf4`` retires verdicts cached while a mutant that broke an import or collection was scored ERROR;
such a gremlin is now ZAPPED with killing test ``<collection>``.

``rf5`` retires verdicts cached by development builds that confirmed collection kills against an unordered
selection.

``rf6`` retires verdicts cached before a timeout was confirmed against the unmutated selection (#565); a
cached TIMEOUT from an older build may be a gremlin that timed out only because the limit was too short.

``rf7`` retires verdicts cached while instrumented modules had no ``__file__`` (#525); target code that read
``Path(__file__)`` raised ``NameError`` under every gremlin, so a survivor could be cached as ZAPPED.

``rf8`` retires verdicts cached while a package ``__init__.py`` was registered as ``pkg.__init__``, a name
nothing imports (#591); every gremlin in such a file was cached as SURVIVED however well the tests caught it.

``rf9`` retires verdicts cached while an instrumented file was registered under a module name guessed from
``sys.path`` and ``pythonpath``, which could differ from the name the tests import it under (#597); every gremlin
in such a file was cached as SURVIVED however well the tests caught it. Instrumented files are now matched by the
file the import system resolves a name to, by its real path or, when a path is spelled differently from the
disk, by its device and inode. Two targets that are one file on disk generate gremlins once.

``rf10`` retires verdicts cached while instrumented modules were compiled under their dotted module name (#563);
``inspect.getsource`` raised under every gremlin, so a test that only looked up source could be cached as ZAPPED.

``rf11`` retires verdicts cached while a target pytest's assertion-rewrite hook serves (``conftest.py``, files
matching ``python_files``) was never instrumented (#603); every gremlin in such a file was cached as SURVIVED.

``rf12`` retires verdicts cached while code run in a ``multiprocessing`` spawn child was never instrumented (#604);
a gremlin only that child exercised was cached as SURVIVED.

``rf13`` retires verdicts cached before the key carried the optimize level (#613); a gremlin only an
``assert`` kills could be served across ``PYTHONOPTIMIZE`` settings.
"""


def subprocess_optimize_level(environ: Mapping[str, str]) -> int:
    """The optimize level a gremlin subprocess launched with ``environ`` compiles under.

    The subprocess gets no ``-O`` flag, so only ``PYTHONOPTIMIZE`` applies, read as CPython reads it:
    unset or empty is 0, a value that is not an integer counts as 1, and levels above 2 compile like 2.

    Args:
        environ: The environment the gremlin subprocess inherits.

    Returns:
        0, 1 or 2.
    """
    value = environ.get('PYTHONOPTIMIZE', '')
    if not value:
        return 0
    try:
        level = int(value)
    except ValueError:
        return 1
    return min(max(level, 0), 2)


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
    - mutant_timeout: the per-gremlin test timeout the verdict was reached under
    - optimize_level: the optimize level the gremlin subprocess compiled under
    - RUNNER_FIDELITY_VERSION: execution-semantics marker, so verdicts from an older
      runner are recomputed once

    Example:
        >>> from pathlib import Path
        >>> cache = IncrementalCache(Path('.gremlins_cache'))
        >>> cache.cache_result('g001', 'src_hash', {'test_foo': 'hash'}, {'status': 'zapped'})
        >>> cache.get_cached_result('g001', 'src_hash', {'test_foo': 'hash'})
        {'status': 'zapped'}
        >>> cache.close()
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
        mutant_timeout: int | None = None,
        optimize_level: int = 0,
    ) -> str:
        """Build a cache key from gremlin and content hashes.

        The key incorporates:
        - gremlin_id: unique mutation identifier
        - source_hash: content hash of the source file
        - test_hashes: combined hash of all relevant test files (names AND hashes)
        - mutant_timeout: the per-gremlin test timeout in seconds
        - optimize_level: the optimize level the gremlin subprocess compiles under

        Args:
            gremlin_id: Unique identifier for the gremlin.
            source_hash: SHA-256 hash of the source file.
            test_hashes: Mapping of test name to content hash.
            mutant_timeout: Per-gremlin test timeout in seconds; a different value is a miss.
            optimize_level: Optimize level of the gremlin subprocess; a different level is a miss.

        Returns:
            A cache key string.
        """
        # Include both test names AND hashes for correct invalidation
        # Renaming a test file (same content) should invalidate the cache
        sorted_test_items = [f'{name}:{test_hashes[name]}' for name in sorted(test_hashes.keys())]
        combined_test_hash = self._hasher.hash_string('|'.join(sorted_test_items)) if sorted_test_items else 'no_tests'

        return (
            f'{gremlin_id}:{source_hash}:{combined_test_hash}:timeout={mutant_timeout}'
            f':opt={optimize_level}:{RUNNER_FIDELITY_VERSION}'
        )

    def get_cached_result(
        self,
        gremlin_id: str,
        source_hash: str,
        test_hashes: dict[str, str],
        mutant_timeout: int | None = None,
        optimize_level: int = 0,
    ) -> CachedGremlinResult | None:
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
            mutant_timeout: Per-gremlin test timeout in seconds; a different value is a miss.
            optimize_level: Optimize level of the gremlin subprocess; a different level is a miss.

        Returns:
            Cached result dictionary, or None if cache miss.
        """
        cache_key = self._build_cache_key(gremlin_id, source_hash, test_hashes, mutant_timeout, optimize_level)
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
        result: CachedGremlinResult,
        mutant_timeout: int | None = None,
        *,
        optimize_level: int = 0,
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
            mutant_timeout: Per-gremlin test timeout in seconds the result was reached under.
            optimize_level: Optimize level of the gremlin subprocess the result was reached under.
        """
        cache_key = self._build_cache_key(gremlin_id, source_hash, test_hashes, mutant_timeout, optimize_level)
        self._store.put(cache_key, result)

    def cache_result_deferred(
        self,
        gremlin_id: str,
        source_hash: str,
        test_hashes: dict[str, str],
        result: CachedGremlinResult,
        mutant_timeout: int | None = None,
        *,
        optimize_level: int = 0,
    ) -> None:
        """Cache a gremlin test result without committing immediately.

        Results are batched and committed on flush() or close(). This is
        faster for bulk inserts during mutation testing runs.

        Args:
            gremlin_id: Unique identifier for the gremlin.
            source_hash: SHA-256 hash of the source file.
            test_hashes: Mapping of test name to content hash.
            result: The result dictionary to cache.
            mutant_timeout: Per-gremlin test timeout in seconds the result was reached under.
            optimize_level: Optimize level of the gremlin subprocess the result was reached under.
        """
        cache_key = self._build_cache_key(gremlin_id, source_hash, test_hashes, mutant_timeout, optimize_level)
        self._store.put_deferred(cache_key, result)

    def flush(self) -> None:
        """Commit all pending deferred cache writes."""
        self._store.flush()

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
