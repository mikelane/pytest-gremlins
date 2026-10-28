"""A cached verdict is only valid for the cache version and operator-package versions that produced it."""

from __future__ import annotations

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


def _install_operator_dist(site: Path, dist_name: str, version: str) -> None:
    dist_info = site / f'{dist_name}-{version}.dist-info'
    dist_info.mkdir(parents=True)
    (dist_info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {dist_name}\nVersion: {version}\n')
    (dist_info / 'entry_points.txt').write_text('[pytest_gremlins.operators]\nep = ep_mod:register\n')


@pytest.fixture
def operator_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    site = tmp_path / 'site'
    site.mkdir()
    monkeypatch.syspath_prepend(str(site))
    return site


@pytest.mark.medium
class DescribeVersionsInCacheKey:
    """Raising the cache version or changing an operator package retires cached verdicts."""

    @pytest.mark.parametrize(
        ('cached_under', 'read_under'),
        [
            pytest.param('1.0.0', '1.0.1', id='upgrade'),
            pytest.param('1.0.1', '1.0.0', id='downgrade'),
        ],
    )
    def it_hits_after_pytest_gremlins_changes_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cached_under: str, read_under: str
    ) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        monkeypatch.setattr('pytest_gremlins.__version__', cached_under)
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        monkeypatch.setattr('pytest_gremlins.__version__', read_under)
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

        shutil.rmtree(operator_site / 'gremlin_ep_dist-1.0.dist-info')
        _install_operator_dist(operator_site, 'gremlin_ep_dist', '2.0')

        assert installed_versions_fingerprint() != before

    def it_changes_when_an_operator_package_is_installed(self, operator_site: Path) -> None:
        before = installed_versions_fingerprint()

        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')

        assert installed_versions_fingerprint() != before

    def it_names_the_cache_version_and_each_operator_distribution_with_its_version(self, operator_site: Path) -> None:
        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')

        fingerprint = installed_versions_fingerprint()

        assert fingerprint.split('|')[0] == f'cache-version={CACHE_VERSION}'
        assert 'gremlin_ep_dist==1.0' in fingerprint.split('|')

    def it_is_stable_when_nothing_changed(self, operator_site: Path) -> None:
        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')

        assert installed_versions_fingerprint() == installed_versions_fingerprint()
