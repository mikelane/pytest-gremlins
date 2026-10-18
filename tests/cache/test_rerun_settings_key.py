"""A verdict reached under one set of rerun filters must not be served under another (#677)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _check_cache_for_gremlin,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.cache.types import CachedGremlinResult

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}
ZAPPED: CachedGremlinResult = {'status': 'zapped', 'killing_test': 'tests/test_x.py::test_a', 'execution_time_ms': 1.0}


@pytest.mark.medium
class DescribeRerunSettingsCacheKey:
    """The cache key carries the resolved rerun settings beyond the count and delay."""

    def it_misses_a_result_cached_under_other_rerun_settings(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED, rerun_settings='only=ConnectionError')

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES, rerun_settings='') is None

    def it_hits_a_result_cached_under_the_same_rerun_settings(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED, rerun_settings='only=ConnectionError')

            assert (
                cache.get_cached_result('g001', 'src_hash', TEST_HASHES, rerun_settings='only=ConnectionError')
                == ZAPPED
            )

    def it_misses_a_deferred_result_cached_under_other_rerun_settings(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result_deferred('g001', 'src_hash', TEST_HASHES, ZAPPED, rerun_settings='a')

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES, rerun_settings='b') is None


@pytest.mark.medium
class DescribePluginCacheLookupUnderRerunSettings:
    """The plugin looks up verdicts under the rerun settings of the session."""

    def it_misses_when_the_session_rerun_settings_differ(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cached_under = GremlinSession(enabled=True, cache_enabled=True, cache=cache, rerun_cache_settings='a')
            looked_up_under = GremlinSession(enabled=True, cache_enabled=True, cache=cache, rerun_cache_settings='b')
            cached_under.source_hashes = {'src/x.py': 'src_hash'}
            looked_up_under.source_hashes = {'src/x.py': 'src_hash'}
            gremlin = Gremlin.__new__(Gremlin)
            object.__setattr__(gremlin, 'gremlin_id', 'g001')
            object.__setattr__(gremlin, 'file_path', 'src/x.py')
            monkeypatch.setattr(
                'pytest_gremlins.plugin._build_test_hashes_for_gremlin', lambda _tests, _session: TEST_HASHES
            )
            monkeypatch.delenv('PYTHONOPTIMIZE', raising=False)
            cache.cache_result(
                'g001',
                'src_hash',
                TEST_HASHES,
                ZAPPED,
                cached_under.mutant_timeout,
                rerun_settings=cached_under.rerun_cache_settings,
            )

            assert _check_cache_for_gremlin(gremlin, [], cached_under) is not None
            assert _check_cache_for_gremlin(gremlin, [], looked_up_under) is None
