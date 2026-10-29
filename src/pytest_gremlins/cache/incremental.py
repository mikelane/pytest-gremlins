"""Incremental analysis cache coordinator.

The IncrementalCache orchestrates content hashing and result storage
to implement smart cache invalidation based on content changes.
"""

from __future__ import annotations

import re
from typing import (
    TYPE_CHECKING,
    TypeAlias,
    cast,
)

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.cache.store import ResultStore
from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Iterable,
        Mapping,
    )
    from pathlib import Path

    from pytest_gremlins.cache.types import CachedGremlinResult
    from pytest_gremlins.operators.protocol import GremlinOperator


RUNNER_FIDELITY_VERSION = 'rf20'
"""Bump when a change to how tests are executed can alter cached verdicts.

This marker covers test execution and outcome-to-verdict mapping (``parallel/``, ``control_run.py``);
``CACHE_VERSION`` in ``versions.py`` covers what gets mutated (``operators/``, ``instrumentation/``).

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

``rf14`` retires verdicts cached while a gremlin subprocess that crashed outside a test, such as during pytest
startup, was scored ZAPPED (#656); it is now an ERROR.

``rf15`` retires verdicts cached before the key carried the rerun budget (#671); a kill reached without reruns
could be served to a run that reruns flaky tests whenever both settings scaled to the same timeout.

``rf16`` retires verdicts cached while gremlin runs reran failing tests in a session that did not load
pytest-rerunfailures, through a command-line ``-p no:rerunfailures`` or ``--disable-plugin-autoload`` (#670);
the key said no reruns, the runs rerun.

``rf17`` retires verdicts cached while gremlin runs did not rerun in a session that loaded pytest-rerunfailures
by a command-line ``-p`` while autoload was disabled for them, by ``PYTEST_DISABLE_PLUGIN_AUTOLOAD`` or by
``--disable-plugin-autoload`` in ``addopts`` or ``PYTEST_ADDOPTS`` (#679); the key said reruns, the runs did not.

``rf18`` retires verdicts cached under a key that ignored the rerun settings beyond count and delay (backoff factor,
``only_rerun``, ``rerun_except``, ``--reruns-mode``, ``--rerun-exclude-path``, ``--max-suite-reruns``; #677).

``rf19`` retires verdicts cached under a key that ignored ``conftest.py`` files above the covering tests, and
verdicts cached for a gremlin whose selected test had no node id (#702).

``rf20`` retires verdicts cached under a key that included the mutant timeout (#567). The timeout now lives in the
stored value, so a verdict can be reused at a different limit when it would not change; old entries are pruned when
the cache opens.

It also retires verdicts cached while doctest gremlins errored, because ``--doctest-modules`` typed on the command
line never reached gremlin runs, and verdicts cached as ZAPPED while ``doctest_optionflags`` or
``doctest_encoding`` set by ``-o`` or ``-c`` never reached them, so a doctest that needed them failed under every
gremlin (#594).  The resolved doctest settings also key the cache, so changing them is a miss (#594).

Verdicts cached while an in-process pytester session (``runpytest()``, ``inline_run()``) inside a gremlin run let its
assertion-rewrite hook serve an instrumented target uninstrumented (#615) are retired without a new marker: a session
that loads the pytester plugin adds ``PYTESTER_KEY_PART`` to every key, so only those projects miss once (#891).
Every other project keeps the ``rf20`` key it had under v1.13.1.
"""

PYTESTER_KEY_PART = 'pytester-615'
"""Key part added only while the pytester plugin is loaded, so just those sessions retire #615 verdicts."""


RerunBudget: TypeAlias = tuple[int, float]
"""``(reruns, reruns_delay)`` a gremlin run may use; see ``pytest_gremlins.rerun_options.session_rerun_budget``."""

NO_RERUNS: RerunBudget = (0, 0.0)
"""The budget of a run that never reruns a failing test: no reruns and no delay."""


def _never_loaded() -> bool:
    """Report that pytester is not loaded; the default for caches opened outside a pytest session.

    Returns:
        Always ``False``, so the key carries no ``PYTESTER_KEY_PART``.
    """
    return False


def _effective_rerun_budget(rerun_budget: RerunBudget) -> RerunBudget:
    """Return ``rerun_budget`` reduced to what the runs actually do, so equal behavior keys equally.

    A non-positive count means no reruns, and a delay only applies before a rerun; a negative or
    ``-0.0`` delay waits no time. A NaN delay is kept: pytest-rerunfailures sleeps it, which raises, so it
    behaves like neither no delay nor any real one and keys as ``nan``.
    """
    reruns, reruns_delay = rerun_budget
    if reruns <= 0:
        return NO_RERUNS
    return reruns, 0.0 if reruns_delay <= 0 else float(reruns_delay)


MILLISECONDS_PER_SECOND = 1000

_C_INTEGER = re.compile(r'[ \t\n\v\f\r]*(?P<sign>[+-]?)(?P<digits>[0-9]+)')
_C_INT_MAX = 2**31 - 1
_C_INT_MAX_DIGITS = len(str(_C_INT_MAX))


def subprocess_optimize_level(environ: Mapping[str, str]) -> int:
    """The optimize level a gremlin subprocess launched with ``environ`` compiles under.

    The subprocess gets no ``-O`` flag, so only ``PYTHONOPTIMIZE`` applies, read as CPython reads it
    (``strtol`` over the whole string): unset or empty is 0, a value that is not a plain integer (trailing
    characters, ``_``, non-ASCII digits, overflow past a C ``int``) counts as 1, a negative value counts as 1,
    and levels above 2 compile like 2. Length does not matter: thousands of leading zeros still read as the
    number they spell, and the child interpreter starts normally either way.

    Args:
        environ: The environment the gremlin subprocess inherits.

    Returns:
        0, 1 or 2.
    """
    value = environ.get('PYTHONOPTIMIZE', '')
    if not value:
        return 0
    match = _C_INTEGER.fullmatch(value)
    if match is None:
        return 1
    return _level_from_digits(match['sign'], match['digits'].lstrip('0'))


def _level_from_digits(sign: str, significant_digits: str) -> int:
    """Return the level for a C integer given as a sign and digits without leading zeros.

    The digit count is checked before ``int`` runs, so a value of any length is read without tripping
    the interpreter's int/str conversion digit limit.
    """
    if len(significant_digits) > _C_INT_MAX_DIGITS:
        return 1
    level = int(significant_digits or '0')
    if level > _C_INT_MAX or (sign == '-' and level > 0):
        return 1
    return min(level, 2)


_STORED_TIMEOUT_FIELD = '_mutant_timeout'
"""Bookkeeping field holding the limit a verdict was reached under; stripped before a result is returned."""

_TIMEOUT_STATUS = 'timeout'


def _with_timeout(result: CachedGremlinResult, mutant_timeout: int | None) -> CachedGremlinResult:
    """Return a copy of ``result`` that also records the limit it was reached under."""
    stored: dict[str, object] = {**result, _STORED_TIMEOUT_FIELD: mutant_timeout}
    return cast('CachedGremlinResult', stored)


def _reusable_result(stored: CachedGremlinResult | None, mutant_timeout: int | None) -> CachedGremlinResult | None:
    """Return the stored verdict without bookkeeping if it still holds at ``mutant_timeout``, else None."""
    if stored is None:
        return None
    fields = dict(stored)
    stored_timeout = fields.pop(_STORED_TIMEOUT_FIELD, None)
    if not _holds_at_timeout(stored['status'], stored.get('execution_time_ms'), stored_timeout, mutant_timeout):
        return None
    return cast('CachedGremlinResult', fields)


def _holds_at_timeout(
    status: str,
    execution_time_ms: float | None,
    stored_timeout: object,
    mutant_timeout: int | None,
) -> bool:
    """Whether a verdict reached under ``stored_timeout`` is the verdict a cold run at ``mutant_timeout`` reaches.

    The same limit always holds. At another limit only a non-TIMEOUT verdict that finished strictly inside the new
    limit holds; an elapsed time equal to the limit is a miss, and an unknown elapsed time is a miss.
    """
    if stored_timeout == mutant_timeout:
        return True
    if status == _TIMEOUT_STATUS or execution_time_ms is None or mutant_timeout is None:
        return False
    return execution_time_ms / MILLISECONDS_PER_SECOND < mutant_timeout


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
    - mutant_timeout: not part of the key; stored with the verdict and checked on lookup (see below)
    - optimize_level: the optimize level the gremlin subprocess compiled under
    - rerun_budget: the ``(reruns, reruns_delay)`` the gremlin runs were allowed
    - rerun_settings: the other resolved rerun settings (backoff factor, filters, mode, exclusions, suite cap)
    - versions: ``CACHE_VERSION`` and operator-package versions (any change retires the whole cache)
    - PYTESTER_KEY_PART: present only while the session loads the pytester plugin (#891)
    - RUNNER_FIDELITY_VERSION: execution-semantics marker, so verdicts from an older
      runner are recomputed once

    A verdict is reused at a different ``mutant_timeout`` only when the new limit cannot change it: a non-TIMEOUT
    verdict whose elapsed time is strictly below the new limit. A TIMEOUT verdict is reused only at the limit it was
    reached under, because its confirmation (the unmutated run fitting in half the limit) is not known to hold at
    another limit.

    Example:
        >>> from pathlib import Path
        >>> cache = IncrementalCache(Path('.gremlins_cache'))
        >>> cache.cache_result('g001', 'src_hash', {'test_foo': 'hash'}, {'status': 'zapped'})
        >>> cache.get_cached_result('g001', 'src_hash', {'test_foo': 'hash'})
        {'status': 'zapped'}
        >>> cache.close()
    """

    def __init__(
        self,
        cache_dir: Path,
        operators: Iterable[GremlinOperator] = (),
        project_root: Path | None = None,
        pytester_loaded: Callable[[], bool] = _never_loaded,
    ) -> None:
        """Initialize the incremental cache.

        Args:
            cache_dir: Directory to store cache files.
            operators: The operators registered for this run; the installed distributions that own them are
                part of the cache key, so upgrading a package that supplies one retires its verdicts.
            project_root: The pytest rootdir; operator modules under it are project code and add nothing.
            pytester_loaded: Reports whether the session loads the pytester plugin. It is asked each time a key is
                built, because a nested ``conftest.py`` can enable pytester after the cache opens.
        """
        self._pytester_loaded = pytester_loaded
        self._cache_dir = cache_dir
        self._hasher = ContentHasher()
        self._store = ResultStore(cache_dir / 'results.db')
        self._store.delete_keys_not_ending_with(f':{RUNNER_FIDELITY_VERSION}')
        self._versions_hash = self._hasher.hash_string(installed_versions_fingerprint(operators, project_root))
        self._hits = 0
        self._misses = 0

    def _build_cache_key(
        self,
        gremlin_id: str,
        source_hash: str,
        test_hashes: dict[str, str],
        optimize_level: int = 0,
        *,
        rerun_budget: RerunBudget = NO_RERUNS,
        rerun_settings: str = '',
    ) -> str:
        """Build a cache key from gremlin and content hashes.

        The key incorporates:
        - gremlin_id: unique mutation identifier
        - source_hash: content hash of the source file
        - test_hashes: combined hash of all relevant test files (names AND hashes)
        - optimize_level: the optimize level the gremlin subprocess compiles under
        - rerun_budget: the reruns and rerun delay the gremlin runs were allowed
        - rerun_settings: the other resolved rerun settings the gremlin runs used

        Args:
            gremlin_id: Unique identifier for the gremlin.
            source_hash: SHA-256 hash of the source file.
            test_hashes: Mapping of test name to content hash.
            optimize_level: Optimize level of the gremlin subprocess; a different level is a miss.
            rerun_budget: ``(reruns, reruns_delay)`` the gremlin runs were allowed; a different budget is a miss
                even when it scales the timeout to the same value.
            rerun_settings: The other resolved rerun settings (backoff factor, filters, mode, exclusions, suite
                cap) the gremlin runs used; different settings are a miss.

        Returns:
            A cache key string.
        """
        # Include both test names AND hashes for correct invalidation
        # Renaming a test file (same content) should invalidate the cache
        sorted_test_items = [f'{name}:{test_hashes[name]}' for name in sorted(test_hashes.keys())]
        combined_test_hash = self._hasher.hash_string('|'.join(sorted_test_items)) if sorted_test_items else 'no_tests'

        reruns, reruns_delay = _effective_rerun_budget(rerun_budget)
        pytester_part = f':{PYTESTER_KEY_PART}' if self._pytester_loaded() else ''
        return (
            f'{gremlin_id}:{source_hash}:{combined_test_hash}'
            f':opt={optimize_level}:reruns={reruns}x{reruns_delay}:rr={rerun_settings}'
            f':v={self._versions_hash}{pytester_part}:{RUNNER_FIDELITY_VERSION}'
        )

    def get_cached_result(
        self,
        gremlin_id: str,
        source_hash: str,
        test_hashes: dict[str, str],
        mutant_timeout: int | None = None,
        optimize_level: int = 0,
        *,
        rerun_budget: RerunBudget = NO_RERUNS,
        rerun_settings: str = '',
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
            mutant_timeout: Per-gremlin test timeout in seconds; a verdict reached under another limit is
                reused only if it still holds there.
            optimize_level: Optimize level of the gremlin subprocess; a different level is a miss.
            rerun_budget: ``(reruns, reruns_delay)`` of the run; a different budget is a miss.
            rerun_settings: The other resolved rerun settings of the run; different settings are a miss.

        Returns:
            Cached result dictionary, or None if cache miss.
        """
        cache_key = self._build_cache_key(
            gremlin_id,
            source_hash,
            test_hashes,
            optimize_level,
            rerun_budget=rerun_budget,
            rerun_settings=rerun_settings,
        )
        result = _reusable_result(self._store.get(cache_key), mutant_timeout)

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
        rerun_budget: RerunBudget = NO_RERUNS,
        rerun_settings: str = '',
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
            rerun_budget: ``(reruns, reruns_delay)`` the result was reached under.
            rerun_settings: The other resolved rerun settings the result was reached under.
        """
        cache_key = self._build_cache_key(
            gremlin_id,
            source_hash,
            test_hashes,
            optimize_level,
            rerun_budget=rerun_budget,
            rerun_settings=rerun_settings,
        )
        self._store.put(cache_key, _with_timeout(result, mutant_timeout))

    def cache_result_deferred(
        self,
        gremlin_id: str,
        source_hash: str,
        test_hashes: dict[str, str],
        result: CachedGremlinResult,
        mutant_timeout: int | None = None,
        *,
        optimize_level: int = 0,
        rerun_budget: RerunBudget = NO_RERUNS,
        rerun_settings: str = '',
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
            rerun_budget: ``(reruns, reruns_delay)`` the result was reached under.
            rerun_settings: The other resolved rerun settings the result was reached under.
        """
        cache_key = self._build_cache_key(
            gremlin_id,
            source_hash,
            test_hashes,
            optimize_level,
            rerun_budget=rerun_budget,
            rerun_settings=rerun_settings,
        )
        self._store.put_deferred(cache_key, _with_timeout(result, mutant_timeout))

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
