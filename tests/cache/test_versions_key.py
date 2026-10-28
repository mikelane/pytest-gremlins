"""A cached verdict is only valid for the pytest-gremlins and operator-package versions that produced it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache import incremental
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.versions import installed_versions_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}


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
    """Upgrading pytest-gremlins or an operator package retires cached verdicts."""

    def it_misses_after_pytest_gremlins_changes_version(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        monkeypatch.setattr('pytest_gremlins.cache.versions.__version__', '1.0.0')
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, {'status': 'zapped'})  # type: ignore[arg-type]

        monkeypatch.setattr('pytest_gremlins.cache.versions.__version__', '1.0.1')
        with IncrementalCache(cache_dir) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_misses_after_pytest_gremlins_is_downgraded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        monkeypatch.setattr('pytest_gremlins.cache.versions.__version__', '1.0.1')
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, {'status': 'zapped'})  # type: ignore[arg-type]

        monkeypatch.setattr('pytest_gremlins.cache.versions.__version__', '1.0.0')
        with IncrementalCache(cache_dir) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_hits_when_no_version_changed(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, {'status': 'zapped'})  # type: ignore[arg-type]

        with IncrementalCache(cache_dir) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == {'status': 'zapped'}

    def it_ends_the_key_with_the_runner_fidelity_version(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)

        assert key.endswith(f':{incremental.RUNNER_FIDELITY_VERSION}')


@pytest.mark.medium
class DescribeInstalledVersionsFingerprint:
    """The fingerprint covers pytest-gremlins and every distribution that supplies an operator."""

    def it_changes_when_an_operator_package_changes_version(self, operator_site: Path) -> None:
        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')
        before = installed_versions_fingerprint()

        _install_operator_dist(operator_site, 'gremlin_ep_dist', '2.0')
        # both dist-infos now exist; remove the old one to model an upgrade
        for old in operator_site.glob('gremlin_ep_dist-1.0.dist-info/*'):
            old.unlink()
        (operator_site / 'gremlin_ep_dist-1.0.dist-info').rmdir()

        assert installed_versions_fingerprint() != before

    def it_changes_when_an_operator_package_is_installed(self, operator_site: Path) -> None:
        before = installed_versions_fingerprint()

        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')

        assert installed_versions_fingerprint() != before

    def it_is_stable_when_nothing_changed(self, operator_site: Path) -> None:
        _install_operator_dist(operator_site, 'gremlin_ep_dist', '1.0')

        assert installed_versions_fingerprint() == installed_versions_fingerprint()
