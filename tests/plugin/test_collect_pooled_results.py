"""Pooled results reach the cache while the run is still going, and only once their verdict is final (issue #974)."""

from __future__ import annotations

import ast
from collections.abc import (
    Callable,
    Iterator,
)
from concurrent.futures import Future
from unittest.mock import (
    create_autospec,
    patch,
)

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.periodic_flush import PeriodicFlusher
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.aggregator import ResultAggregator
from pytest_gremlins.parallel.exit_codes import COLLECTION_KILLING_TEST
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.plugin import (
    GremlinSession,
    _collect_pooled_results,
    _confirm_and_cache_pooled_results,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)


def _gremlin(gremlin_id: str) -> Gremlin:
    return Gremlin(
        gremlin_id=gremlin_id,
        file_path='/path/to/source.py',
        line_number=1,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


def _finished(worker_result: WorkerResult) -> Future[WorkerResult]:
    future: Future[WorkerResult] = Future()
    future.set_result(worker_result)
    return future


@pytest.fixture
def cache() -> IncrementalCache:
    cache: IncrementalCache = create_autospec(IncrementalCache, instance=True)
    return cache


@pytest.fixture
def gremlin_session(cache: IncrementalCache) -> GremlinSession:
    session: GremlinSession = create_autospec(GremlinSession, instance=True)
    session.cache = cache
    session.cache_enabled = True
    return session


@pytest.fixture
def cache_calls() -> Iterator[list[str]]:
    """Record the gremlin id of every ``_cache_gremlin_result`` call."""
    calls: list[str] = []

    def record(gremlin: Gremlin, *_: object) -> None:
        calls.append(gremlin.gremlin_id)

    with patch.object(plugin, '_cache_gremlin_result', side_effect=record):
        yield calls


def _collect(
    results: list[WorkerResult], gremlin_session: GremlinSession, aggregator: ResultAggregator | None = None
) -> set[str]:
    futures = {_finished(result): result.gremlin_id for result in results}
    return _collect_pooled_results(
        futures,
        aggregator or ResultAggregator(total_gremlins=len(results)),
        {result.gremlin_id: _gremlin(result.gremlin_id) for result in results},
        {result.gremlin_id: [] for result in results},
        gremlin_session,
    )


_WaitOutcome = tuple[set[Future[WorkerResult]], set[Future[WorkerResult]]]


def _scripted_wait(
    *outcomes: _WaitOutcome, on_exhausted: Callable[[], None] = lambda: None
) -> Callable[..., _WaitOutcome]:
    """Stand in for ``wait``: yield ``outcomes`` in turn, then run ``on_exhausted`` and raise KeyboardInterrupt."""
    remaining = iter(outcomes)

    def scripted(*_: object, **__: object) -> _WaitOutcome:
        outcome = next(remaining, None)
        if outcome is None:
            on_exhausted()
            raise KeyboardInterrupt
        return outcome

    return scripted


def _collect_stuck(
    finished: Future[WorkerResult], stuck: Future[WorkerResult], gremlin_session: GremlinSession
) -> None:
    _collect_pooled_results(
        {finished: 'g1', stuck: 'g2'},
        ResultAggregator(total_gremlins=2),
        {'g1': _gremlin('g1'), 'g2': _gremlin('g2')},
        {'g1': [], 'g2': []},
        gremlin_session,
    )


@pytest.mark.small
class DescribeCollectPooledResults:
    def it_caches_final_verdicts_as_they_arrive(self, gremlin_session: GremlinSession, cache_calls: list[str]) -> None:
        cached = _collect(
            [
                WorkerResult('g1', GremlinResultStatus.SURVIVED),
                WorkerResult('g2', GremlinResultStatus.ZAPPED, killing_test='tests/test_a.py::test_a'),
            ],
            gremlin_session,
        )

        assert cached == {'g1', 'g2'}
        assert sorted(cache_calls) == ['g1', 'g2']

    def it_does_not_cache_a_timeout_before_it_is_confirmed(
        self, gremlin_session: GremlinSession, cache_calls: list[str]
    ) -> None:
        cached = _collect([WorkerResult('g1', GremlinResultStatus.TIMEOUT)], gremlin_session)

        assert cached == set()
        assert cache_calls == []

    def it_does_not_cache_a_collection_kill_before_it_is_confirmed(
        self, gremlin_session: GremlinSession, cache_calls: list[str]
    ) -> None:
        cached = _collect(
            [WorkerResult('g1', GremlinResultStatus.ZAPPED, killing_test=COLLECTION_KILLING_TEST)], gremlin_session
        )

        assert cached == set()
        assert cache_calls == []

    def it_flushes_the_cache_when_the_wait_is_interrupted(
        self, gremlin_session: GremlinSession, cache: IncrementalCache, cache_calls: list[str]
    ) -> None:
        finished = _finished(WorkerResult('g1', GremlinResultStatus.SURVIVED))
        stuck: Future[WorkerResult] = Future()

        with patch.object(plugin, 'wait', new=_scripted_wait(({finished}, {stuck}))), pytest.raises(KeyboardInterrupt):
            _collect_stuck(finished, stuck, gremlin_session)

        assert cache_calls == ['g1']
        cache.flush.assert_called_once_with()  # type: ignore[attr-defined]

    def it_flushes_on_the_interval_while_a_stuck_gremlin_keeps_the_wait_open(
        self, gremlin_session: GremlinSession, cache: IncrementalCache
    ) -> None:
        finished = _finished(WorkerResult('g1', GremlinResultStatus.SURVIVED))
        stuck: Future[WorkerResult] = Future()
        flushes_before_second_wait: list[int] = []

        def on_second_wait() -> None:
            flushes_before_second_wait.append(cache.flush.call_count)  # type: ignore[attr-defined]

        flusher = PeriodicFlusher(cache.flush, every_results=100, every_seconds=0.0)
        with (
            patch.object(plugin, 'wait', new=_scripted_wait(({finished}, {stuck}), on_exhausted=on_second_wait)),
            patch.object(plugin, '_cache_flusher_for', return_value=flusher),
            pytest.raises(KeyboardInterrupt),
        ):
            _collect_stuck(finished, stuck, gremlin_session)

        assert flushes_before_second_wait == [1]


@pytest.mark.small
class DescribeConfirmAndCachePooledResults:
    def it_skips_results_that_were_cached_when_they_arrived(
        self, gremlin_session: GremlinSession, cache_calls: list[str]
    ) -> None:
        results = [
            GremlinResult(gremlin=_gremlin('g1'), status=GremlinResultStatus.SURVIVED),
            GremlinResult(gremlin=_gremlin('g2'), status=GremlinResultStatus.ZAPPED, killing_test='t::t'),
        ]
        test_commands: dict[str, list[str]] = {'g1': [], 'g2': []}

        _confirm_and_cache_pooled_results(results, test_commands, gremlin_session, rootdir=None, already_cached={'g1'})  # type: ignore[arg-type]

        assert cache_calls == ['g2']
