"""The default built-in sequence keeps the pre-#789 cache key byte for byte."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.store import ResultStore
from pytest_gremlins.instrumentation.transformer import get_default_registry
from pytest_gremlins.operators.comparison import ComparisonOperator

if TYPE_CHECKING:
    from pathlib import Path

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}
# Fixed SHA-256 digests of the public synthetic test mapping and cache-version=1.
LEGACY_DEFAULT_KEY = (
    'g001:src_hash:'
    '0bba2ec2ece7ff84ddcaf45ee587240f8bfb569f101ff8f671884f83c10c807d'  # pragma: allowlist secret
    ':opt=0:reruns=0x0.0:rr=:v='
    '49744e9db4a64507ab454ee90720aa367c18924eb7aaef14a52bc349707d6cb5'  # pragma: allowlist secret
    ':rf20'
)


@pytest.fixture(autouse=True)
def no_operator_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin supplier metadata so installed third-party plugins cannot change the expected key."""
    monkeypatch.setattr('pytest_gremlins.cache.versions.entry_points', lambda **_kwargs: ())


@pytest.mark.medium
class DescribeDefaultOperatorCacheKey:
    @pytest.mark.parametrize('pytester_loaded', [False, True])
    def it_keeps_the_exact_legacy_key_and_reads_its_verdict(self, tmp_path: Path, pytester_loaded: bool) -> None:
        operators = get_default_registry().get_all()
        assert [operator.name for operator in operators] == [
            'comparison',
            'arithmetic',
            'boolean',
            'boundary',
            'return',
        ]
        expected = LEGACY_DEFAULT_KEY.replace(':rf20', ':pytester-615:rf20') if pytester_loaded else LEGACY_DEFAULT_KEY
        cache_dir = tmp_path / '.gremlins_cache'
        with ResultStore(cache_dir / 'results.db') as store:
            store.put(expected, {'status': 'zapped'})

        with IncrementalCache(cache_dir, iter(operators), pytester_loaded=lambda: pytester_loaded) as cache:
            assert cache._build_cache_key('g001', 'src_hash', TEST_HASHES) == expected
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == {'status': 'zapped'}
            cache.cache_result('g002', 'src_hash', TEST_HASHES, {'status': 'survived'})

        with ResultStore(cache_dir / 'results.db') as store:
            assert store.get(expected.replace('g001:', 'g002:', 1)) == {'status': 'survived', '_mutant_timeout': None}

    def it_separates_a_reordered_sequence_from_the_default(self, tmp_path: Path) -> None:
        operators = get_default_registry().get_all()
        cache_dir = tmp_path / '.gremlins_cache'
        with ResultStore(cache_dir / 'results.db') as store:
            store.put(LEGACY_DEFAULT_KEY, {'status': 'zapped'})

        with IncrementalCache(cache_dir, reversed(operators)) as cache:
            key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) is None
            cache.cache_result('g001', 'src_hash', TEST_HASHES, {'status': 'survived'})

        assert key != LEGACY_DEFAULT_KEY
        assert ':ops=' in key

        with IncrementalCache(cache_dir, reversed(operators)) as cache:
            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES) == {'status': 'survived'}

    def it_separates_a_skipped_constructor_then_restores_the_default_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = get_default_registry()

        def unavailable(_self: ComparisonOperator) -> None:
            raise ImportError('optional dependency unavailable')

        with monkeypatch.context() as patch:
            patch.setattr(ComparisonOperator, '__init__', unavailable)
            with pytest.warns(UserWarning, match='comparison.*ImportError'):
                surviving = registry.get_all()
            with IncrementalCache(tmp_path / '.gremlins_cache', surviving) as cache:
                key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)
            assert key != LEGACY_DEFAULT_KEY
            assert ':ops=' in key

        with IncrementalCache(tmp_path / '.gremlins_cache', registry.get_all()) as cache:
            assert cache._build_cache_key('g001', 'src_hash', TEST_HASHES) == LEGACY_DEFAULT_KEY

    def it_separates_an_empty_sequence_from_the_default(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache', ()) as cache:
            key = cache._build_cache_key('g001', 'src_hash', TEST_HASHES)

        assert key != LEGACY_DEFAULT_KEY
        assert ':ops=' in key
