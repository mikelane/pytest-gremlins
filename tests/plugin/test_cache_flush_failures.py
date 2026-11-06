"""A cache flush that fails mid-run must not abort the mutation run or hide why it stopped (issue #974)."""

from __future__ import annotations

import ast
from concurrent.futures import Future
import sqlite3
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
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.plugin import (
    GremlinSession,
    _collect_pooled_results,
    _run_mutation_testing,
)
from pytest_gremlins.reporting.results import GremlinResultStatus


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


def _finished(gremlin_id: str) -> Future[WorkerResult]:
    future: Future[WorkerResult] = Future()
    future.set_result(WorkerResult(gremlin_id, GremlinResultStatus.SURVIVED))
    return future


def _disk_full() -> None:
    raise sqlite3.OperationalError('database or disk is full')


@pytest.fixture
def gremlin_session() -> GremlinSession:
    session: GremlinSession = create_autospec(GremlinSession, instance=True)
    session.cache = create_autospec(IncrementalCache, instance=True)
    session.cache_enabled = True
    return session


def _pending_flusher_that_fails() -> PeriodicFlusher:
    flusher = PeriodicFlusher(_disk_full)
    flusher.note_result()
    return flusher


@pytest.mark.small
class DescribeCacheFlushFailureDuringPooledCollection:
    def it_keeps_collecting_results_when_a_periodic_flush_fails(self, gremlin_session: GremlinSession) -> None:
        aggregator = ResultAggregator(total_gremlins=2)
        first, second = _finished('g1'), _finished('g2')
        flusher = PeriodicFlusher(_disk_full, every_results=1)
        outcomes = iter([({first}, {second}), ({second}, set())])

        with (
            patch.object(plugin, 'wait', side_effect=lambda *_, **__: next(outcomes)),
            patch.object(plugin, '_cache_gremlin_result'),
            patch.object(plugin, '_cache_flusher_for', return_value=flusher),
        ):
            _collect_pooled_results(
                {first: 'g1', second: 'g2'},
                aggregator,
                {'g1': _gremlin('g1'), 'g2': _gremlin('g2')},
                {'g1': [], 'g2': []},
                gremlin_session,
            )

        assert sorted(result.gremlin_id for result in aggregator.get_results()) == ['g1', 'g2']

    def it_reports_the_interrupt_when_the_final_flush_fails(self, gremlin_session: GremlinSession) -> None:
        stuck: Future[WorkerResult] = Future()

        with (
            patch.object(plugin, 'wait', side_effect=KeyboardInterrupt),
            patch.object(plugin, '_cache_flusher_for', return_value=_pending_flusher_that_fails()),
            pytest.raises(KeyboardInterrupt),
        ):
            _collect_pooled_results(
                {stuck: 'g1'}, ResultAggregator(total_gremlins=1), {'g1': _gremlin('g1')}, {'g1': []}, gremlin_session
            )


@pytest.mark.small
class DescribeCacheFlushFailureDuringSequentialRun:
    def it_reports_the_interrupt_when_the_final_flush_fails(self, gremlin_session: GremlinSession) -> None:
        session = create_autospec(pytest.Session, instance=True)

        with (
            patch.object(plugin, '_run_gremlins_one_by_one', side_effect=KeyboardInterrupt),
            patch.object(plugin, '_cache_flusher_for', return_value=_pending_flusher_that_fails()),
            pytest.raises(KeyboardInterrupt),
        ):
            _run_mutation_testing(session, gremlin_session)
