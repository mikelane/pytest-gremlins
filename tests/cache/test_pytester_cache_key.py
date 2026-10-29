"""Only sessions that load the pytester plugin retire the verdicts #615 made wrong (#891)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.types import CachedGremlinResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}
V1_13_1_FIDELITY_VERSION = 'rf20'
SURVIVED = CachedGremlinResult(status='survived', killing_test=None, execution_time_ms=None)


@pytest.mark.medium
class DescribePytesterTokenInCacheKey:
    def it_keeps_the_v1_13_1_key_shape_for_a_project_without_pytester(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)

            assert key.endswith(f':v={cache._versions_hash}:{V1_13_1_FIDELITY_VERSION}')

    def it_changes_the_key_for_a_project_that_loads_pytester(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as plain:
            plain_key = plain._build_cache_key('g001', 'src_hash', TEST_HASHES)
        with IncrementalCache(tmp_path / '.gremlins_cache_pytester', pytester_loaded=lambda: True) as loaded:
            loaded_key = loaded._build_cache_key('g001', 'src_hash', TEST_HASHES)

        assert loaded_key != plain_key
        assert ':pytester-615:' in loaded_key
        assert loaded_key.endswith(f':{V1_13_1_FIDELITY_VERSION}')

    def it_misses_a_verdict_stored_before_pytester_was_loaded(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir) as plain:
            plain.cache_result('g001', 'src_hash', TEST_HASHES, SURVIVED)

        with IncrementalCache(cache_dir, pytester_loaded=lambda: True) as loaded:
            assert loaded.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_hits_a_verdict_stored_without_pytester_when_pytester_is_still_not_loaded(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir) as first:
            first.cache_result('g001', 'src_hash', TEST_HASHES, SURVIVED)

        with IncrementalCache(cache_dir) as second:
            assert second.get_cached_result('g001', 'src_hash', TEST_HASHES) == SURVIVED

    def it_misses_a_verdict_stored_while_pytester_was_loaded_once_it_is_not(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir, pytester_loaded=lambda: True) as loaded:
            loaded.cache_result('g001', 'src_hash', TEST_HASHES, SURVIVED)

        with IncrementalCache(cache_dir) as plain:
            assert plain.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_asks_whether_pytester_is_loaded_when_the_key_is_built_not_when_the_cache_opens(self, tmp_path: Path) -> None:
        state = {'loaded': False}
        with IncrementalCache(tmp_path / '.gremlins_cache', pytester_loaded=lambda: state['loaded']) as cache:
            state['loaded'] = True

            assert ':pytester-615:' in cache._build_cache_key('g001', 'src_hash', TEST_HASHES)


GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=comparison', '--gremlin-cache')
COLD = 'Cache: 0 hits, 2 misses (0% hit rate)'
WARM = 'Cache: 2 hits, 0 misses (100% hit rate)'
TARGET_WITH_COMPARISON = 'def limit(x):\n    return x > 41\n'
TEST_WITH_COMPARISON = 'from target import limit\n\n\ndef test_limit():\n    assert limit(42)\n'


@pytest.fixture
def project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """Make the child pytest sessions these tests spawn write UTF-8, so Windows cp1252 bullets decode."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    pytester.makepyfile(target=TARGET_WITH_COMPARISON, test_target=TEST_WITH_COMPARISON)
    return pytester


def _enable_with_p_flag(_pytester: pytest.Pytester) -> tuple[str, ...]:
    return ('-p', 'pytester')


def _enable_with_root_conftest(pytester: pytest.Pytester) -> tuple[str, ...]:
    pytester.makeconftest("pytest_plugins = ['pytester']\n")
    return ()


def _enable_with_addopts(pytester: pytest.Pytester) -> tuple[str, ...]:
    pytester.makeini('[pytest]\naddopts = -p pytester\n')
    return ()


ENABLERS = {
    '-p': _enable_with_p_flag,
    'root conftest': _enable_with_root_conftest,
    'addopts': _enable_with_addopts,
}


@pytest.mark.medium
class DescribePytesterSubprocessEncoding:
    @pytest.mark.usefixtures('project')
    def it_writes_child_output_as_utf8(self) -> None:
        assert os.environ.get('PYTHONIOENCODING') == 'utf-8'


@pytest.mark.medium
class DescribePytesterDetectionEndToEnd:
    def it_keeps_a_warm_cache_for_a_project_that_never_loads_pytester(self, project: pytest.Pytester) -> None:
        project.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([COLD])

        project.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([WARM])

    @pytest.mark.parametrize('enabler', ENABLERS.values(), ids=ENABLERS.keys())
    def it_misses_the_cache_once_when_pytester_is_loaded_and_then_hits(
        self, project: pytest.Pytester, enabler: Callable[[pytest.Pytester], tuple[str, ...]]
    ) -> None:
        project.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([COLD])
        extra = enabler(project)

        project.runpytest_subprocess(*GREMLIN_ARGS, *extra).stdout.fnmatch_lines([COLD])

        project.runpytest_subprocess(*GREMLIN_ARGS, *extra).stdout.fnmatch_lines([WARM])
