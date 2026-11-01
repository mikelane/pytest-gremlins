"""Verdicts cached before #668 must not replay in sessions whose gremlin runs now load xdist (#668).

Before #668, a session started with plugin autoload disabled and ``-p xdist.plugin`` on its command line forwarded
neither a loader nor ``-n 0``. Its gremlin runs ran without pytest-xdist, so a test that takes the ``worker_id``
fixture errored at setup under every gremlin and each gremlin was cached as ZAPPED under ``rf20``. #668 loads xdist
in those runs, so the same gremlins now survive. Only those sessions add ``XDIST_KEY_PART``, so every other
session keeps the key it had (the same pattern as #891 for pytester).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import (
    RUNNER_FIDELITY_VERSION,
    XDIST_KEY_PART,
    IncrementalCache,
)
from pytest_gremlins.cache.types import CachedGremlinResult

if TYPE_CHECKING:
    from pathlib import Path

TESTS = {'test_sample.py::test_weak': 'h'}
ZAPPED = CachedGremlinResult(status='zapped', killing_test='test_sample.py::test_weak', execution_time_ms=5.0)


def _cache_zapped_verdict_in_ordinary_session(cache_dir: Path) -> None:
    with IncrementalCache(cache_dir) as ordinary:
        ordinary.cache_result('sample_feec_g002', 'src', TESTS, ZAPPED, mutant_timeout=30)


@pytest.mark.medium
class DescribeVerdictsCachedBeforeXdistWasLoadedUnderDisabledAutoload:
    def it_does_not_serve_a_pre_668_verdict_in_a_session_that_now_loads_xdist(self, tmp_path: Path) -> None:
        _cache_zapped_verdict_in_ordinary_session(tmp_path / 'cache')

        with IncrementalCache(tmp_path / 'cache', xdist_loader_loaded=lambda: True) as upgraded:
            assert upgraded.get_cached_result('sample_feec_g002', 'src', TESTS, mutant_timeout=30) is None

    def it_still_serves_a_cached_verdict_in_an_ordinary_session(self, tmp_path: Path) -> None:
        _cache_zapped_verdict_in_ordinary_session(tmp_path / 'cache')

        with IncrementalCache(tmp_path / 'cache') as ordinary:
            assert ordinary.get_cached_result('sample_feec_g002', 'src', TESTS, mutant_timeout=30) == ZAPPED

    def it_serves_a_verdict_cached_by_an_earlier_xdist_loading_session(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / 'cache', xdist_loader_loaded=lambda: True) as first:
            first.cache_result('sample_feec_g002', 'src', TESTS, ZAPPED, mutant_timeout=30)

        with IncrementalCache(tmp_path / 'cache', xdist_loader_loaded=lambda: True) as second:
            assert second.get_cached_result('sample_feec_g002', 'src', TESTS, mutant_timeout=30) == ZAPPED


@pytest.mark.medium
class DescribeXdistCacheKeyPart:
    def it_leaves_an_ordinary_sessions_key_without_the_xdist_part(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / 'cache') as ordinary:
            key = ordinary._build_cache_key('g001', 'src_hash', TESTS)

        assert XDIST_KEY_PART not in key
        assert key.endswith(f':v={ordinary._versions_hash}:{RUNNER_FIDELITY_VERSION}')

    def it_adds_the_xdist_part_before_the_fidelity_marker(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / 'cache', xdist_loader_loaded=lambda: True) as loaded:
            key = loaded._build_cache_key('g001', 'src_hash', TESTS)

        assert key.endswith(f':v={loaded._versions_hash}:{XDIST_KEY_PART}:{RUNNER_FIDELITY_VERSION}')

    def it_keeps_the_pytester_part_position_when_both_parts_apply(self, tmp_path: Path) -> None:
        with IncrementalCache(
            tmp_path / 'cache', pytester_loaded=lambda: True, xdist_loader_loaded=lambda: True
        ) as both:
            key = both._build_cache_key('g001', 'src_hash', TESTS)

        assert key.endswith(f':v={both._versions_hash}:pytester-615:{XDIST_KEY_PART}:{RUNNER_FIDELITY_VERSION}')
