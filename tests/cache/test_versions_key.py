"""A cached verdict is only valid for the cache version and operator-package versions that produced it."""

from __future__ import annotations

import importlib
import shutil
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.versions import (
    CACHE_VERSION,
    installed_versions_fingerprint,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.cache.types import CachedGremlinResult

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}
ZAPPED: CachedGremlinResult = {'status': 'zapped', 'killing_test': 'tests/test_x.py::test_a', 'execution_time_ms': 1.0}


def _install_operator_dist(
    site: Path, dist_name: str, version: str, entry_point_names: tuple[str, ...] = ('ep',)
) -> None:
    dist_info = site / f'{dist_name}-{version}.dist-info'
    dist_info.mkdir(parents=True)
    (dist_info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {dist_name}\nVersion: {version}\n')
    declarations = ''.join(f'{name} = ep_mod:{name}\n' for name in entry_point_names)
    (dist_info / 'entry_points.txt').write_text(f'[pytest_gremlins.operators]\n{declarations}')
    importlib.invalidate_caches()


def _uninstall_operator_dist(site: Path, dist_name: str, version: str) -> None:
    shutil.rmtree(site / f'{dist_name}-{version}.dist-info')
    importlib.invalidate_caches()


@pytest.fixture
def operator_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    site = tmp_path / 'site'
    site.mkdir()
    monkeypatch.syspath_prepend(str(site))
    return site


@pytest.mark.medium
class DescribeVersionsInCacheKey:
    """Raising the cache version or changing an operator package retires cached verdicts."""

    def it_hits_after_pytest_gremlins_changes_version(self, tmp_path: Path, operator_site: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        dist_info = operator_site / 'pytest_gremlins-99.0.0.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: pytest-gremlins\nVersion: 99.0.0\n')
        importlib.invalidate_caches()
        with IncrementalCache(cache_dir) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == ZAPPED

    def it_misses_after_the_cache_version_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        monkeypatch.setattr('pytest_gremlins.cache.versions.CACHE_VERSION', 1)
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        monkeypatch.setattr('pytest_gremlins.cache.versions.CACHE_VERSION', 2)
        with IncrementalCache(cache_dir) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_misses_after_an_operator_package_is_installed(self, tmp_path: Path, operator_site: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')
        with IncrementalCache(cache_dir) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_misses_after_an_operator_package_is_removed(self, tmp_path: Path, operator_site: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        _uninstall_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')
        with IncrementalCache(cache_dir) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_hits_when_no_version_changed(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        with IncrementalCache(cache_dir) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == ZAPPED


@pytest.mark.medium
class DescribeInstalledVersionsFingerprint:
    """The fingerprint covers the cache version and every distribution that supplies an operator."""

    def it_changes_when_an_operator_package_changes_version(self, operator_site: Path) -> None:
        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')
        before = installed_versions_fingerprint()

        _uninstall_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')
        _install_operator_dist(operator_site, 'gremlin_ep_dist', '2.0')

        assert installed_versions_fingerprint() != before

    def it_changes_when_an_operator_package_is_installed(self, operator_site: Path) -> None:
        before = installed_versions_fingerprint()

        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')

        assert installed_versions_fingerprint() != before

    def it_names_the_cache_version_and_each_operator_distribution_with_its_version(self, operator_site: Path) -> None:
        _install_operator_dist(operator_site, 'zeta_ops', '1.0')
        _install_operator_dist(operator_site, 'alpha_ops', '1.0')

        assert installed_versions_fingerprint() == f'cache-version={CACHE_VERSION}|alpha_ops==1.0|zeta_ops==1.0'

    def it_names_a_distribution_once_when_it_declares_two_entry_points(self, operator_site: Path) -> None:
        _install_operator_dist(operator_site, 'alpha_ops', '1.0', entry_point_names=('first', 'second'))

        assert installed_versions_fingerprint() == f'cache-version={CACHE_VERSION}|alpha_ops==1.0'

    def it_fingerprints_an_operator_dist_whose_metadata_lacks_name_and_version(self, operator_site: Path) -> None:
        dist_info = operator_site / 'broken_ops-1.0.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\n')
        (dist_info / 'entry_points.txt').write_text('[pytest_gremlins.operators]\nep = ep_mod:ep\n')
        importlib.invalidate_caches()

        assert 'broken_ops' in installed_versions_fingerprint()
