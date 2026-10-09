"""A verdict reached under one optimize level must not be served under another (#613)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache, subprocess_optimize_level
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import GremlinSession, _check_cache_for_gremlin

if TYPE_CHECKING:
    from pathlib import Path

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}


@pytest.mark.small
class DescribeSubprocessOptimizeLevel:
    """PYTHONOPTIMIZE is read the way CPython reads it."""

    @pytest.mark.parametrize(
        ('environ', 'level'),
        [
            ({}, 0),
            ({'PYTHONOPTIMIZE': ''}, 0),
            ({'PYTHONOPTIMIZE': '0'}, 0),
            ({'PYTHONOPTIMIZE': '1'}, 1),
            ({'PYTHONOPTIMIZE': 'x'}, 1),
            ({'PYTHONOPTIMIZE': '2'}, 2),
            ({'PYTHONOPTIMIZE': '3'}, 2),
            ({'PYTHONOPTIMIZE': '-1'}, 0),
        ],
    )
    def it_normalizes_the_level(self, environ: dict[str, str], level: int) -> None:
        assert subprocess_optimize_level(environ) == level


@pytest.mark.medium
class DescribeOptimizeLevelCacheKey:
    """The cache key carries the optimize level."""

    def it_misses_a_result_cached_under_another_level(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, {'status': 'zapped'}, optimize_level=0)  # type: ignore[arg-type]

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES, optimize_level=1) is None

    def it_hits_a_result_cached_under_the_same_level(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, {'status': 'survived'}, optimize_level=1)  # type: ignore[arg-type]

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES, optimize_level=1) == {'status': 'survived'}

    def it_keeps_levels_1_and_2_apart(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            assert cache._build_cache_key('g001', 'src_hash', TEST_HASHES, optimize_level=1) != cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, optimize_level=2
            )

    def it_misses_a_result_cached_without_a_level(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            current_key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)
            legacy_key = current_key.replace(':opt=0', '').rsplit(':', 1)[0] + ':rf12'
            cache._store.put(legacy_key, {'status': 'zapped'})  # type: ignore[arg-type]

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None


@pytest.mark.medium
class DescribePluginCacheLookup:
    """The plugin looks up verdicts under the level the subprocess will run with."""

    def it_misses_when_pythonoptimize_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            session = GremlinSession(enabled=True, cache_enabled=True, cache=cache)
            session.source_hashes = {'src/x.py': 'src_hash'}
            gremlin = Gremlin.__new__(Gremlin)
            object.__setattr__(gremlin, 'gremlin_id', 'g001')
            object.__setattr__(gremlin, 'file_path', 'src/x.py')
            monkeypatch.setattr(
                'pytest_gremlins.plugin._build_test_hashes_for_gremlin', lambda _tests, _session: TEST_HASHES
            )
            cache.cache_result(  # type: ignore[arg-type]
                'g001', 'src_hash', TEST_HASHES, {'status': 'zapped'}, mutant_timeout=session.mutant_timeout
            )

            monkeypatch.delenv('PYTHONOPTIMIZE', raising=False)
            assert _check_cache_for_gremlin(gremlin, [], session) is not None
            monkeypatch.setenv('PYTHONOPTIMIZE', '1')
            assert _check_cache_for_gremlin(gremlin, [], session) is None
