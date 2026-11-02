"""Verdicts cached while gremlin runs ignored ``-c`` are retired once those runs read the config file (#951).

Before #951 a gremlin run under ``-c`` read an auto-discovered config file, not the ``-c`` file, so its verdicts can
differ from the ones the runs now reach.  Only sessions that forward ``-c`` add ``CONFIG_FILE_KEY_PART``, so every
other session keeps the key it had.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.cache.incremental import (
    CONFIG_FILE_KEY_PART,
    RUNNER_FIDELITY_VERSION,
    IncrementalCache,
)
from pytest_gremlins.cache.types import CachedGremlinResult

TESTS = {'test_sample.py::test_weak': 'h'}
ZAPPED = CachedGremlinResult(status='zapped', killing_test='test_sample.py::test_weak', execution_time_ms=5.0)


@pytest.mark.medium
class DescribeVerdictsCachedBeforeGremlinRunsReadTheConfigFile:
    def it_does_not_serve_a_verdict_cached_without_the_config_file_to_a_session_that_forwards_it(
        self, tmp_path: Path
    ) -> None:
        with IncrementalCache(tmp_path / 'cache') as ordinary:
            ordinary.cache_result('sample_feec_g002', 'src', TESTS, ZAPPED, mutant_timeout=30)

        with IncrementalCache(tmp_path / 'cache', config_file_forwarded=True) as forwarding:
            assert forwarding.get_cached_result('sample_feec_g002', 'src', TESTS, mutant_timeout=30) is None

    def it_serves_a_verdict_cached_by_an_earlier_session_that_forwarded_the_config_file(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / 'cache', config_file_forwarded=True) as first:
            first.cache_result('sample_feec_g002', 'src', TESTS, ZAPPED, mutant_timeout=30)

        with IncrementalCache(tmp_path / 'cache', config_file_forwarded=True) as second:
            assert second.get_cached_result('sample_feec_g002', 'src', TESTS, mutant_timeout=30) == ZAPPED

    def it_still_serves_a_cached_verdict_to_a_session_without_dash_c(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / 'cache') as first:
            first.cache_result('sample_feec_g002', 'src', TESTS, ZAPPED, mutant_timeout=30)

        with IncrementalCache(tmp_path / 'cache') as second:
            assert second.get_cached_result('sample_feec_g002', 'src', TESTS, mutant_timeout=30) == ZAPPED


@pytest.mark.medium
class DescribeConfigFileCacheKeyPart:
    def it_leaves_a_session_without_dash_c_with_its_existing_key(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / 'cache') as ordinary:
            key = ordinary._build_cache_key('g001', 'src_hash', TESTS)

        assert CONFIG_FILE_KEY_PART not in key
        assert key.endswith(f':v={ordinary._versions_hash}:{RUNNER_FIDELITY_VERSION}')

    def it_adds_the_part_before_the_fidelity_marker(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / 'cache', config_file_forwarded=True) as forwarding:
            key = forwarding._build_cache_key('g001', 'src_hash', TESTS)

        assert key.endswith(f':v={forwarding._versions_hash}:{CONFIG_FILE_KEY_PART}:{RUNNER_FIDELITY_VERSION}')

    def it_orders_the_part_after_the_pytester_and_xdist_parts(self, tmp_path: Path) -> None:
        with IncrementalCache(
            tmp_path / 'cache',
            pytester_loaded=lambda: True,
            xdist_loader_loaded=lambda: True,
            config_file_forwarded=True,
        ) as all_parts:
            key = all_parts._build_cache_key('g001', 'src_hash', TESTS)

        expected_tail = f':pytester-615:xdist-668:{CONFIG_FILE_KEY_PART}:{RUNNER_FIDELITY_VERSION}'
        assert key.endswith(expected_tail)
