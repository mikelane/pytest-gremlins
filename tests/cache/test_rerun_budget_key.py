"""A verdict reached under one rerun budget must not be served under another (#671)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest
from rerun_samples import (
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import (
    IncrementalCache,
    RerunBudget,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _check_cache_for_gremlin,
)
from pytest_gremlins.reporting.results import GremlinResultStatus

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.cache.types import CachedGremlinResult

TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}
SAME_EFFECTIVE_TIMEOUT = 60
ZAPPED: CachedGremlinResult = {'status': 'zapped', 'killing_test': 'tests/test_x.py::test_a', 'execution_time_ms': 1.0}
SURVIVED: CachedGremlinResult = {'status': 'survived', 'killing_test': None, 'execution_time_ms': 1.0}

# Zaps every comparison mutant of ``classify`` on the first attempt, so a run that reruns and one that does not
# agree, except that pytest-rerunfailures sleeps the delay before each rerun and ``time.sleep(nan)`` raises.
STEADY_TEST = """
from sample import classify


def test_big():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""


@pytest.mark.medium
class DescribeRerunBudgetCacheKey:
    """The cache key carries the rerun budget, not only the timeout scaled from it."""

    def it_misses_a_result_cached_under_another_budget_with_the_same_timeout(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result(
                'g001',
                'src_hash',
                TEST_HASHES,
                ZAPPED,
                SAME_EFFECTIVE_TIMEOUT,
                rerun_budget=(0, 0.0),
            )

            assert (
                cache.get_cached_result('g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, 0.0))
                is None
            )

    def it_hits_a_result_cached_under_the_same_budget(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result('g001', 'src_hash', TEST_HASHES, SURVIVED, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, 0.5))

            assert (
                cache.get_cached_result('g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, 0.5))
                == SURVIVED
            )

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
            cache.cache_result_deferred('g001', 'src_hash', TEST_HASHES, ZAPPED, rerun_budget=(0, 0.0))
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
        self, tmp_path: Path, spelling: RerunBudget, equivalent_spelling: RerunBudget
    ) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            assert cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=spelling
            ) == cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=equivalent_spelling
            )


@pytest.mark.medium
class DescribeNanRerunDelay:
    """pytest-rerunfailures sleeps a NaN delay, which raises; it does not treat it as no delay."""

    def it_keys_a_nan_delay_apart_from_no_delay(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            assert cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, math.nan)
            ) != cache._build_cache_key('g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, 0.0))

    def it_builds_one_key_for_every_nan_delay(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            assert cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, math.nan)
            ) == cache._build_cache_key(
                'g001', 'src_hash', TEST_HASHES, SAME_EFFECTIVE_TIMEOUT, rerun_budget=(1, -math.nan)
            )

    def it_does_not_serve_a_zero_delay_verdict_to_a_nan_delay_run(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=STEADY_TEST)
        cache_args = ('--gremlin-cache',)

        def run(delay: str, *extra_args: str) -> pytest.RunResult:
            return pytester.runpytest_subprocess(*GREMLIN_ARGS, '--reruns', '1', '--reruns-delay', delay, *extra_args)

        uncached_run = run('nan')
        run('0', *cache_args)
        cached_run = run('nan', *cache_args)

        assert verdicts(cached_run.stdout.str()) == verdicts(uncached_run.stdout.str())


@pytest.mark.medium
class DescribePluginCacheLookupUnderRerunBudget:
    """The plugin looks up verdicts under the rerun budget of the session."""

    def it_misses_when_the_session_rerun_budget_differs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cached_under = GremlinSession(enabled=True, cache_enabled=True, cache=cache, mutant_timeout=60)
            looked_up_under = GremlinSession(
                enabled=True, cache_enabled=True, cache=cache, mutant_timeout=60, rerun_budget=(1, 0.0)
            )
            cached_under.source_hashes = {'src/x.py': 'src_hash'}
            looked_up_under.source_hashes = {'src/x.py': 'src_hash'}
            gremlin = Gremlin.__new__(Gremlin)
            object.__setattr__(gremlin, 'gremlin_id', 'g001')
            object.__setattr__(gremlin, 'file_path', 'src/x.py')
            monkeypatch.setattr(
                'pytest_gremlins.plugin._build_test_hashes_for_gremlin', lambda _tests, _session: TEST_HASHES
            )
            monkeypatch.delenv('PYTHONOPTIMIZE', raising=False)
            cache.cache_result('g001', 'src_hash', TEST_HASHES, ZAPPED, 60, rerun_budget=cached_under.rerun_budget)

            hit = _check_cache_for_gremlin(gremlin, [], cached_under)
            assert hit is not None
            assert hit.status == GremlinResultStatus.ZAPPED
            assert _check_cache_for_gremlin(gremlin, [], looked_up_under) is None


def _configured_rerun_budget(pytester: pytest.Pytester, *args: str) -> RerunBudget:
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
