"""A distribution supplying a conftest-registered operator is part of the cache key (#873)."""

from __future__ import annotations

import importlib
import shutil
import sys
from typing import (
    TYPE_CHECKING,
    Any,
)

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.versions import (
    CACHE_VERSION,
    installed_versions_fingerprint,
)
from pytest_gremlins.operators import ComparisonOperator

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest_gremlins.cache.types import CachedGremlinResult

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}
ZAPPED: CachedGremlinResult = {'status': 'zapped', 'killing_test': 'tests/test_x.py::test_a', 'execution_time_ms': 1.0}
OPERATOR_SOURCE = 'class SuppliedOperator:\n    name = "supplied"\n'


def _install_package(site: Path, dist_name: str, version: str, module: str) -> None:
    dist_info = site / f'{dist_name}-{version}.dist-info'
    dist_info.mkdir(parents=True)
    (dist_info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {dist_name}\nVersion: {version}\n')
    (dist_info / 'top_level.txt').write_text(f'{module}\n')
    (site / f'{module}.py').write_text(OPERATOR_SOURCE)
    importlib.invalidate_caches()


def _uninstall_package(site: Path, dist_name: str, version: str) -> None:
    shutil.rmtree(site / f'{dist_name}-{version}.dist-info')
    importlib.invalidate_caches()


def _supplied_operator() -> Any:
    return importlib.import_module('supplied_ops').SuppliedOperator()


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / 'site'
    path.mkdir()
    monkeypatch.syspath_prepend(str(path))
    yield path
    sys.modules.pop('supplied_ops', None)


class LocalOperator:
    name = 'local'


@pytest.mark.medium
class DescribeFingerprintNamesOperatorOwners:
    def it_names_the_distribution_that_owns_a_registered_operator(self, site: Path) -> None:
        _install_package(site, 'supplied_dist', '1.0', 'supplied_ops')

        fingerprint = installed_versions_fingerprint([_supplied_operator()])

        assert fingerprint == f'cache-version={CACHE_VERSION}|supplied_dist==1.0'

    def it_changes_when_the_owning_distribution_is_upgraded(self, site: Path) -> None:
        _install_package(site, 'supplied_dist', '1.0', 'supplied_ops')
        operator = _supplied_operator()
        before = installed_versions_fingerprint([operator])

        _uninstall_package(site, 'supplied_dist', '1.0')
        _install_package(site, 'supplied_dist', '2.0', 'supplied_ops')

        assert installed_versions_fingerprint([operator]) != before

    def it_changes_when_the_owning_distribution_is_downgraded(self, site: Path) -> None:
        _install_package(site, 'supplied_dist', '2.0', 'supplied_ops')
        operator = _supplied_operator()
        before = installed_versions_fingerprint([operator])

        _uninstall_package(site, 'supplied_dist', '2.0')
        _install_package(site, 'supplied_dist', '1.0', 'supplied_ops')

        assert installed_versions_fingerprint([operator]) != before

    def it_ignores_an_operator_defined_in_no_installed_distribution(self) -> None:
        assert installed_versions_fingerprint([LocalOperator()]) == installed_versions_fingerprint()

    def it_ignores_the_built_in_operators(self) -> None:
        assert installed_versions_fingerprint([ComparisonOperator()]) == installed_versions_fingerprint()

    def it_ignores_a_distribution_whose_operator_is_not_registered(self, site: Path) -> None:
        before = installed_versions_fingerprint()

        _install_package(site, 'supplied_dist', '1.0', 'supplied_ops')

        assert installed_versions_fingerprint() == before


@pytest.mark.medium
class DescribeCacheKeyFollowsOperatorOwners:
    def it_misses_after_the_owning_distribution_is_upgraded(self, tmp_path: Path, site: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        _install_package(site, 'supplied_dist', '1.0', 'supplied_ops')
        operators = [_supplied_operator()]
        with IncrementalCache(cache_dir, operators=operators) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        _uninstall_package(site, 'supplied_dist', '1.0')
        _install_package(site, 'supplied_dist', '2.0', 'supplied_ops')
        with IncrementalCache(cache_dir, operators=operators) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_hits_when_nothing_changed(self, tmp_path: Path, site: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        _install_package(site, 'supplied_dist', '1.0', 'supplied_ops')
        operators = [_supplied_operator()]
        with IncrementalCache(cache_dir, operators=operators) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        with IncrementalCache(cache_dir, operators=operators) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == ZAPPED

    def it_hits_for_a_project_local_operator_whatever_else_is_installed(self, tmp_path: Path, site: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        operators = [LocalOperator()]
        with IncrementalCache(cache_dir, operators=operators) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        _install_package(site, 'unrelated_dist', '1.0', 'unrelated_ops')
        with IncrementalCache(cache_dir, operators=operators) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == ZAPPED
