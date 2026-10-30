"""A run with an operator no installed distribution owns writes nothing to the cache (#893).

Such an operator puts a fresh random token in every cache key, so no later run can read what this run writes.
Writing it anyway would grow ``results.db`` by one row per cached gremlin on every run.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from typing import (
    TYPE_CHECKING,
    cast,
)

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.versions import versions_fingerprint
from pytest_gremlins.operators.comparison import ComparisonOperator

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.operators.protocol import GremlinOperator

UNOWNED_OPERATOR_SOURCE = 'class HelperOperator:\n    name = "helper"\n    description = "x"\n'


def _unowned_operator(project_root: Path, module_name: str = 'path_loaded_unowned_helper') -> GremlinOperator:
    path = project_root / 'gremlin_ops.py'
    path.write_text(UNOWNED_OPERATOR_SOURCE)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast('GremlinOperator', module.HelperOperator())


def _row_count(cache_dir: Path) -> int:
    with sqlite3.connect(cache_dir / 'results.db') as conn:
        (count,) = conn.execute('SELECT COUNT(*) FROM results').fetchone()
    conn.close()
    return int(count)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / 'project'
    root.mkdir()
    return root


@pytest.mark.medium
class DescribeCacheWritesWithAnUnownedOperator:
    def it_reports_the_fingerprint_as_unreadable(self, project_root: Path) -> None:
        assert versions_fingerprint([_unowned_operator(project_root)], project_root).writes_are_readable is False

    def it_adds_no_row_through_cache_result(self, tmp_path: Path, project_root: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir, [_unowned_operator(project_root)], project_root) as cache:
            cache.cache_result('g001', 'src', {'test_a': 'h'}, {'status': 'zapped'})

        assert _row_count(cache_dir) == 0

    def it_adds_no_row_through_cache_result_deferred_and_flush(self, tmp_path: Path, project_root: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir, [_unowned_operator(project_root)], project_root) as cache:
            cache.cache_result_deferred('g001', 'src', {'test_a': 'h'}, {'status': 'zapped'})
            cache.cache_result_deferred('g002', 'src', {'test_a': 'h'}, {'status': 'survived'})
            cache.flush()

        assert _row_count(cache_dir) == 0

    def it_still_misses_on_lookup(self, tmp_path: Path, project_root: Path) -> None:
        operators = [_unowned_operator(project_root)]
        with IncrementalCache(tmp_path / '.gremlins_cache', operators, project_root) as cache:
            cache.cache_result('g001', 'src', {'test_a': 'h'}, {'status': 'zapped'})

            assert cache.get_cached_result('g001', 'src', {'test_a': 'h'}) is None


@pytest.mark.medium
class DescribeCacheWritesWithOnlyInstalledOperators:
    def it_reports_the_fingerprint_as_readable(self, project_root: Path) -> None:
        assert versions_fingerprint([ComparisonOperator()], project_root).writes_are_readable is True

    def it_writes_through_cache_result_and_hits_on_the_next_run(self, tmp_path: Path, project_root: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir, [ComparisonOperator()], project_root) as cache:
            cache.cache_result('g001', 'src', {'test_a': 'h'}, {'status': 'zapped'})

        with IncrementalCache(cache_dir, [ComparisonOperator()], project_root) as cache:
            assert cache.get_cached_result('g001', 'src', {'test_a': 'h'}) == {'status': 'zapped'}
        assert _row_count(cache_dir) == 1

    def it_writes_through_cache_result_deferred_and_hits_on_the_next_run(
        self, tmp_path: Path, project_root: Path
    ) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir, [ComparisonOperator()], project_root) as cache:
            cache.cache_result_deferred('g001', 'src', {'test_a': 'h'}, {'status': 'zapped'})
            cache.flush()

        with IncrementalCache(cache_dir, [ComparisonOperator()], project_root) as cache:
            assert cache.get_cached_result('g001', 'src', {'test_a': 'h'}) == {'status': 'zapped'}
        assert _row_count(cache_dir) == 1


@pytest.mark.medium
class DescribeCacheWritesWithAnUnownedOperatorWhoseModuleNameHoldsTheSeparator:
    def it_reports_the_fingerprint_as_unreadable(self, project_root: Path) -> None:
        operator = _unowned_operator(project_root, 'ops|helper')

        assert versions_fingerprint([operator], project_root).writes_are_readable is False

    def it_adds_no_row_through_cache_result(self, tmp_path: Path, project_root: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'

        with IncrementalCache(cache_dir, [_unowned_operator(project_root, 'ops|helper')], project_root) as cache:
            cache.cache_result('g001', 'src', {'test_a': 'h'}, {'status': 'zapped'})

        assert _row_count(cache_dir) == 0
