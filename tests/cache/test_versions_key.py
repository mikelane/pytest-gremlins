"""A cached verdict is only valid for the cache version and operator-package versions that produced it."""

from __future__ import annotations

import ast
import importlib
import shutil
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.versions import (
    CACHE_VERSION,
    installed_versions_fingerprint,
)
from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.operators.arithmetic import ArithmeticOperator
from pytest_gremlins.operators.boundary import BoundaryOperator
from pytest_gremlins.operators.comparison import ComparisonOperator
from pytest_gremlins.operators.registry import OperatorRegistry

if TYPE_CHECKING:
    from collections.abc import Callable
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

    def it_keeps_cached_verdicts_separate_when_a_constructor_fails_then_recovers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unavailable(_self: ComparisonOperator) -> None:
            raise ImportError('optional dependency unavailable')

        registry = OperatorRegistry()
        registry.register(ComparisonOperator)
        registry.register(BoundaryOperator)
        source = 'def less(a):\n    return a < 10\n'
        cache_dir = tmp_path / '.gremlins_cache'
        healthy = registry.get_all()
        healthy_gremlins, _ = transform_source(source, 'target.py', operators=healthy)
        gremlin_id = healthy_gremlins[0].gremlin_id
        with IncrementalCache(cache_dir, operators=healthy) as cache:
            cache.cache_result(gremlin_id, 'same_source', TEST_HASHES, ZAPPED)

        with monkeypatch.context() as patch:
            patch.setattr(ComparisonOperator, '__init__', unavailable)
            with pytest.warns(UserWarning, match='comparison.*ImportError'):
                surviving = registry.get_all()
            surviving_gremlins, _ = transform_source(source, 'target.py', operators=surviving)
            assert surviving_gremlins[0].gremlin_id == gremlin_id
            assert surviving_gremlins[0].operator_name != healthy_gremlins[0].operator_name
            assert ast.dump(surviving_gremlins[0].mutated_node) != ast.dump(healthy_gremlins[0].mutated_node)
            assert installed_versions_fingerprint(surviving) == installed_versions_fingerprint(healthy)
            with IncrementalCache(cache_dir, operators=surviving) as cache:
                assert cache.get_cached_result(gremlin_id, 'same_source', TEST_HASHES) is None
                cache.cache_result(gremlin_id, 'same_source', TEST_HASHES, {'status': 'survived'})

        recovered = registry.get_all()
        assert installed_versions_fingerprint(recovered) == installed_versions_fingerprint(healthy)
        with IncrementalCache(cache_dir, operators=recovered) as cache:
            assert cache.get_cached_result(gremlin_id, 'same_source', TEST_HASHES) == ZAPPED

    def it_misses_when_active_operator_order_changes(self, tmp_path: Path) -> None:
        operators = [ComparisonOperator(), ArithmeticOperator()]
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir, operators=operators) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        with IncrementalCache(cache_dir, operators=reversed(operators)) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_misses_when_active_operator_multiplicity_changes(self, tmp_path: Path) -> None:
        comparison = ComparisonOperator()
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir, operators=[comparison]) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        with IncrementalCache(cache_dir, operators=[comparison, comparison]) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_misses_for_a_different_operator_class_with_the_same_name(
        self, tmp_path: Path, install_entry_point_dist: Callable[..., Path]
    ) -> None:
        site = install_entry_point_dist(
            {
                'first': 'gremlin_same_name_ops:FirstComparison',
                'alternate': 'gremlin_same_name_ops:AlternateComparison',
            },
            {
                'gremlin_same_name_ops': (
                    'from pytest_gremlins.operators.comparison import ComparisonOperator\n'
                    'class FirstComparison(ComparisonOperator):\n'
                    '    pass\n'
                    'class AlternateComparison(ComparisonOperator):\n'
                    '    pass\n'
                ),
            },
            dist_name='gremlin_same_name_ops_dist',
        )
        (site / 'gremlin_same_name_ops_dist-1.0.dist-info' / 'top_level.txt').write_text('gremlin_same_name_ops\n')
        module = importlib.import_module('gremlin_same_name_ops')
        first = module.FirstComparison()
        alternate = module.AlternateComparison()
        assert first.name == alternate.name
        assert type(first) is not type(alternate)
        fingerprint = installed_versions_fingerprint([first])
        assert 'gremlin_same_name_ops_dist==1.0' in fingerprint
        assert installed_versions_fingerprint([alternate]) == fingerprint

        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir, operators=[first]) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        with IncrementalCache(cache_dir, operators=[module.FirstComparison()]) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == ZAPPED

        with IncrementalCache(cache_dir, operators=[alternate]) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None

    def it_hits_with_an_iterator_of_fresh_instances_of_the_same_operators(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / '.gremlins_cache'
        with IncrementalCache(cache_dir, operators=[ComparisonOperator(), ArithmeticOperator()]) as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED)

        with IncrementalCache(cache_dir, operators=iter([ComparisonOperator(), ArithmeticOperator()])) as cache:
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
