"""Pooled results reach the cache while the run is still going, and only once their verdict is final (issue #974)."""

from __future__ import annotations

import ast
from collections.abc import (
    Callable,
    Iterator,
)
from concurrent.futures import Future
from pathlib import Path
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
    # Real values: autospec only exposes default_factory dataclass fields on Python 3.14 and later.
    session.source_hashes = {}
    session.terminal_notices = []
    session.load_failures_attributable = True
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
        {result.gremlin_id: _tests_for(result.gremlin_id) for result in results},
        gremlin_session,
    )


def _tests_for(gremlin_id: str) -> list[str]:
    return [f'tests/test_{gremlin_id}.py::test_it']


_WaitOutcome = tuple[set[Future[WorkerResult]], set[Future[WorkerResult]]]


def _scripted_wait(
    *outcomes: _WaitOutcome,
    on_exhausted: Callable[[], None] = lambda: None,
    seen_kwargs: list[dict[str, object]] | None = None,
) -> Callable[..., _WaitOutcome]:
    """Stand in for ``wait``: yield ``outcomes`` in turn, then run ``on_exhausted`` and raise KeyboardInterrupt.

    Each call's keyword arguments are appended to ``seen_kwargs`` when it is given.
    """
    remaining = iter(outcomes)

    def scripted(*_: object, **kwargs: object) -> _WaitOutcome:
        if seen_kwargs is not None:
            seen_kwargs.append(kwargs)
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
    def it_caches_final_verdicts_as_they_arrive(
        self, gremlin_session: GremlinSession, cache: IncrementalCache, cache_calls: list[str]
    ) -> None:
        cached = _collect(
            [
                WorkerResult('g1', GremlinResultStatus.SURVIVED),
                WorkerResult('g2', GremlinResultStatus.ZAPPED, killing_test='tests/test_a.py::test_a'),
            ],
            gremlin_session,
        )

        assert cached == {'g1', 'g2'}
        assert sorted(cache_calls) == ['g1', 'g2']
        cache.flush.assert_called_once_with()  # type: ignore[attr-defined]

    def it_hands_the_cache_the_worker_verdict_and_the_gremlin_selection(self, gremlin_session: GremlinSession) -> None:
        with patch.object(plugin, '_cache_gremlin_result') as cache_result:
            _collect(
                [WorkerResult('g1', GremlinResultStatus.ZAPPED, killing_test='tests/test_a.py::test_a')],
                gremlin_session,
            )

        gremlin, selected_tests, result, session = cache_result.call_args.args
        assert (gremlin.gremlin_id, selected_tests, session) == ('g1', _tests_for('g1'), gremlin_session)
        assert (result.status, result.killing_test) == (GremlinResultStatus.ZAPPED, 'tests/test_a.py::test_a')

    def it_records_a_worker_failure_as_an_error_without_caching_it(
        self, gremlin_session: GremlinSession, cache: IncrementalCache, cache_calls: list[str]
    ) -> None:
        failed: Future[WorkerResult] = Future()
        failed.set_exception(RuntimeError('worker crashed'))
        aggregator = ResultAggregator(total_gremlins=1)

        cached = _collect_pooled_results(
            {failed: 'g1'}, aggregator, {'g1': _gremlin('g1')}, {'g1': []}, gremlin_session
        )

        assert cached == set()
        assert cache_calls == []
        cache.flush.assert_not_called()  # type: ignore[attr-defined]
        assert [(r.gremlin_id, r.status, r.error_output) for r in aggregator.get_results()] == [
            ('g1', GremlinResultStatus.ERROR, 'worker crashed')
        ]

    @pytest.mark.usefixtures('cache_calls')
    def it_does_not_flush_the_cache_when_caching_is_off(
        self, gremlin_session: GremlinSession, cache: IncrementalCache
    ) -> None:
        gremlin_session.cache_enabled = False

        _collect([WorkerResult('g1', GremlinResultStatus.SURVIVED)], gremlin_session)

        cache.flush.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.usefixtures('cache_calls')
    def it_collects_without_a_cache_object(self, gremlin_session: GremlinSession) -> None:
        gremlin_session.cache = None

        cached = _collect([WorkerResult('g1', GremlinResultStatus.SURVIVED)], gremlin_session)

        assert cached == {'g1'}

    def it_does_not_cache_a_timeout_before_it_is_confirmed(
        self, gremlin_session: GremlinSession, cache: IncrementalCache, cache_calls: list[str]
    ) -> None:
        cached = _collect([WorkerResult('g1', GremlinResultStatus.TIMEOUT)], gremlin_session)

        assert cached == set()
        assert cache_calls == []
        cache.flush.assert_not_called()  # type: ignore[attr-defined]

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

    @pytest.mark.usefixtures('cache_calls')
    def it_waits_no_longer_than_the_flush_interval(self, gremlin_session: GremlinSession) -> None:
        stuck: Future[WorkerResult] = Future()
        seen_kwargs: list[dict[str, object]] = []
        flusher = PeriodicFlusher(lambda: None, every_seconds=7.5)

        with (
            patch.object(plugin, 'wait', new=_scripted_wait(seen_kwargs=seen_kwargs)),
            patch.object(plugin, '_cache_flusher_for', return_value=flusher),
            pytest.raises(KeyboardInterrupt),
        ):
            _collect_pooled_results(
                {stuck: 'g1'}, ResultAggregator(total_gremlins=1), {'g1': _gremlin('g1')}, {'g1': []}, gremlin_session
            )

        assert seen_kwargs[0]['timeout'] == pytest.approx(7.5)

    @pytest.mark.usefixtures('cache_calls')
    def it_services_the_watchdog_before_every_wait_and_wakes_up_often_enough_for_it(
        self, gremlin_session: GremlinSession
    ) -> None:
        stuck: Future[WorkerResult] = Future()
        seen_kwargs: list[dict[str, object]] = []
        events: list[str] = []
        flusher = PeriodicFlusher(lambda: None, every_seconds=7.5)

        def service() -> list[str]:
            events.append('service')
            return []

        def scripted_wait(*_: object, **kwargs: object) -> _WaitOutcome:
            events.append('wait')
            seen_kwargs.append(kwargs)
            raise KeyboardInterrupt

        with (
            patch.object(plugin, 'wait', new=scripted_wait),
            patch.object(plugin, '_cache_flusher_for', return_value=flusher),
            pytest.raises(KeyboardInterrupt),
        ):
            _collect_pooled_results(
                {stuck: 'g1'},
                ResultAggregator(total_gremlins=1),
                {'g1': _gremlin('g1')},
                {'g1': []},
                gremlin_session,
                service=service,
            )

        assert events == ['service', 'wait']
        assert seen_kwargs[0]['timeout'] == pytest.approx(plugin.WATCHDOG_TICK_SECONDS)

    @pytest.mark.usefixtures('cache_calls')
    def it_collects_a_verdict_the_watchdog_settles(self, gremlin_session: GremlinSession) -> None:
        hung: Future[WorkerResult] = Future()
        aggregator = ResultAggregator(total_gremlins=1)

        def settle_as_timeout() -> list[str]:
            hung.set_result(WorkerResult('g1', GremlinResultStatus.TIMEOUT))
            return ['g1']

        _collect_pooled_results(
            {hung: 'g1'}, aggregator, {'g1': _gremlin('g1')}, {'g1': []}, gremlin_session, service=settle_as_timeout
        )

        assert [(r.gremlin_id, r.status) for r in aggregator.get_results()] == [('g1', GremlinResultStatus.TIMEOUT)]
        assert any('g1' in notice and 'hung' in notice for notice in gremlin_session.terminal_notices)


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

        confirmed = _confirm_and_cache_pooled_results(
            results, test_commands, gremlin_session, rootdir=Path(), early_cached_ids={'g1'}
        )

        assert cache_calls == ['g2']
        assert [(r.gremlin.gremlin_id, r.status) for r in confirmed] == [
            ('g1', GremlinResultStatus.SURVIVED),
            ('g2', GremlinResultStatus.ZAPPED),
        ]
