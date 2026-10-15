"""A verdict reached under one rerun budget must not be served under another (#671)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _check_cache_for_gremlin,
)

if TYPE_CHECKING:
    from pathlib import Path

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}
SAME_EFFECTIVE_TIMEOUT = 60


@pytest.mark.medium
class DescribeRerunBudgetCacheKey:
    """The cache key carries the rerun budget, not only the timeout scaled from it."""

    def it_misses_a_result_cached_under_another_budget_with_the_same_timeout(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(  # type: ignore[arg-type]
                'g001',
                'src_hash',
                TEST_HASHES,
                {'status': 'zapped'},
                SAME_EFFECTIVE_TIMEOUT,
                rerun_budget=(0, 0.0),
            )

            assert (
                cache.get_cached_result('g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, 0.0))
                is None
            )

    def it_hits_a_result_cached_under_the_same_budget(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(  # type: ignore[arg-type]
                'g001', 'src_hash', TEST_HASHES, {'status': 'survived'}, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, 0.5)
            )

            assert cache.get_cached_result(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, 0.5)
            ) == {'status': 'survived'}

    def it_misses_when_only_the_delay_changes(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            assert cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(2, 1.0)
            ) != cache._build_cache_key('g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(2, 2.0))

    def it_misses_when_only_the_count_changes(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            assert cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(2, 1.0)
            ) != cache._build_cache_key('g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(3, 1.0))

    def it_misses_a_deferred_result_cached_under_another_budget(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result_deferred(  # type: ignore[arg-type]
                'g001', 'src_hash', TEST_HASHES, {'status': 'zapped'}, rerun_budget=(0, 0.0)
            )
            cache.flush()

            assert cache.get_cached_result('g001', 'src_hash', TEST_HASHES, rerun_budget=(2, 0.0)) is None


@pytest.mark.medium
class DescribeEquivalentRerunBudgetsShareAKey:
    """Budgets that run the same reruns the same way key identically, however they were spelled."""

    @pytest.mark.parametrize(
        ('spelling', 'equivalent_spelling'),
        [
            pytest.param((2, 1), (2, 1.0), id='integer-delay-equals-float-delay'),
            pytest.param((1, -0.0), (1, 0.0), id='negative-zero-delay-equals-zero-delay'),
            pytest.param((1, -2.5), (1, 0.0), id='negative-delay-is-no-delay'),
            pytest.param((0, 3.0), (0, 0.0), id='delay-without-reruns-is-no-delay'),
            pytest.param((-1, 0.0), (0, 0.0), id='negative-count-is-no-reruns'),
        ],
    )
    def it_builds_one_key_for_equivalent_budgets(
        self, tmp_path: Path, spelling: tuple[int, float], equivalent_spelling: tuple[int, float]
    ) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            assert cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=spelling
            ) == cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=equivalent_spelling
            )


@pytest.mark.medium
class DescribePluginCacheLookupUnderRerunBudget:
    """The plugin looks up verdicts under the rerun budget of the session."""

    def it_misses_when_the_session_rerun_budget_differs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cached_under = GremlinSession(enabled=True, cache_enabled=True, cache=cache, mutant_timeout=60)
            looked_up_under = GremlinSession(
                enabled=True, cache_enabled=True, cache=cache, mutant_timeout=60, rerun_budget=(1, 0.0)
            )
            for session in (cached_under, looked_up_under):
                session.source_hashes = {'src/x.py': 'src_hash'}
            gremlin = Gremlin.__new__(Gremlin)
            object.__setattr__(gremlin, 'gremlin_id', 'g001')
            object.__setattr__(gremlin, 'file_path', 'src/x.py')
            monkeypatch.setattr(
                'pytest_gremlins.plugin._build_test_hashes_for_gremlin', lambda _tests, _session: TEST_HASHES
            )
            monkeypatch.delenv('PYTHONOPTIMIZE', raising=False)
            cache.cache_result(  # type: ignore[arg-type]
                'g001', 'src_hash', TEST_HASHES, {'status': 'zapped'}, 60, rerun_budget=cached_under.rerun_budget
            )

            assert _check_cache_for_gremlin(gremlin, [], cached_under) is not None
            assert _check_cache_for_gremlin(gremlin, [], looked_up_under) is None


def _configured_rerun_budget(pytester: pytest.Pytester, *args: str) -> tuple[int, float]:
    pytester.makepyfile(sample='def one():\n    return 1\n')
    pytester.parseconfigure('--gremlins', '--gremlin-targets=sample.py', *args)
    session = plugin._get_session()
    assert session is not None
    return session.rerun_budget


@pytest.mark.medium
class DescribeRerunBudgetThroughTheRealEntryPoint:
    """The session records the budget from the options pytest parsed."""

    def it_records_the_command_line_count_and_delay(self, pytester: pytest.Pytester) -> None:
        assert _configured_rerun_budget(pytester, '--reruns', '2', '--reruns-delay', '1.5') == (2, 1.5)

    def it_records_the_forced_count(self, pytester: pytest.Pytester) -> None:
        assert _configured_rerun_budget(pytester, '--force-reruns', '3', '--reruns', '1') == (3, 0.0)

    def it_records_no_reruns_when_pytest_rerunfailures_is_not_loaded(self, pytester: pytest.Pytester) -> None:
        pytester.makeini('[pytest]\nreruns = 2\n')

        assert _configured_rerun_budget(pytester, '-p', 'no:rerunfailures') == (0, 0.0)
