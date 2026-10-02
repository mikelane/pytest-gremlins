"""Results cached before the runner could abstain may be fabricated, so they must miss once."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import (
    RUNNER_FIDELITY_VERSION,
    IncrementalCache,
)

if TYPE_CHECKING:
    from pathlib import Path

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}


@pytest.mark.medium
class DescribeRunnerFidelityCacheKey:
    """The cache key carries the runner-fidelity version."""

    def it_misses_a_result_stored_under_the_pre_fidelity_key(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            current_key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)
            legacy_key = current_key.removesuffix(f':{RUNNER_FIDELITY_VERSION}')
            cache._store.put(legacy_key, {'status': 'zapped'})  # type: ignore[arg-type]

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_hits_a_result_stored_under_the_current_key(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, {'status': 'zapped'})  # type: ignore[arg-type]

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == {'status': 'zapped'}

    def it_ends_the_key_with_the_version(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)

        assert key.endswith(f':{RUNNER_FIDELITY_VERSION}')

    def it_retires_results_cached_before_load_failures_became_kills(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            current_key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)
            rf3_key = current_key.rsplit(':', 1)[0] + ':rf3'
            cache._store.put(rf3_key, {'status': 'error'})  # type: ignore[arg-type]

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None
