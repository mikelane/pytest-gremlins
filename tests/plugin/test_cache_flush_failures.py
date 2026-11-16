"""A cache flush that fails mid-run must not abort the mutation run or hide why it stopped (issue #974)."""

from __future__ import annotations

import ast
from concurrent.futures import Future
from pathlib import Path
import sqlite3
from unittest.mock import (
    create_autospec,
    patch,
)

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.cache.periodic_flush import PeriodicFlusher
from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.aggregator import ResultAggregator
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.plugin import (
    GremlinSession,
    _collect_pooled_results,
    _run_mutation_testing,
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
    # Real values: autospec only exposes default_factory dataclass fields on Python 3.14 and later.
    session.source_hashes = {}
    session.terminal_notices = []
    session.load_failures_attributable = True
    return session


class FlushAttempts:
    """A flush that records every attempt and, when told to, fails like a full disk."""

    def __init__(self, *, should_fail: bool) -> None:
        self.should_fail = should_fail
        self.attempts = 0

    def __call__(self) -> None:
        self.attempts += 1
        if self.should_fail:
            _disk_full()


def _pending_flusher(flush: FlushAttempts) -> PeriodicFlusher:
    flusher = PeriodicFlusher(flush)
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

    def it_still_raises_the_interrupt_when_the_final_flush_fails(self, gremlin_session: GremlinSession) -> None:
        stuck: Future[WorkerResult] = Future()
        flush = FlushAttempts(should_fail=True)

        with (
            patch.object(plugin, 'wait', side_effect=KeyboardInterrupt),
            patch.object(plugin, '_cache_flusher_for', return_value=_pending_flusher(flush)),
            pytest.raises(KeyboardInterrupt),
        ):
            _collect_pooled_results(
                {stuck: 'g1'}, ResultAggregator(total_gremlins=1), {'g1': _gremlin('g1')}, {'g1': []}, gremlin_session
            )

        assert flush.attempts == 1


@pytest.mark.small
class DescribeCacheFlushFailureDuringSequentialRun:
    def it_still_raises_the_interrupt_when_the_final_flush_fails(self, gremlin_session: GremlinSession) -> None:
        session = create_autospec(pytest.Session, instance=True)
        flush = FlushAttempts(should_fail=True)

        with (
            patch.object(plugin, '_run_gremlins_one_by_one', side_effect=KeyboardInterrupt),
            patch.object(plugin, '_cache_flusher_for', return_value=_pending_flusher(flush)),
            pytest.raises(KeyboardInterrupt),
        ):
            _run_mutation_testing(session, gremlin_session)

        assert flush.attempts == 1


MAPPED = 'tests/test_m.py::test_mapped'


def _sequential_session(gremlin_ids: list[str]) -> GremlinSession:
    selector = create_autospec(PrioritizedSelector, instance=True)
    selector.select_tests_prioritized.return_value = [MAPPED]
    return GremlinSession(
        enabled=True,
        gremlins=[_gremlin(gremlin_id) for gremlin_id in gremlin_ids],
        prioritized_selector=selector,
        test_node_ids={MAPPED: MAPPED},
    )


def _survived(gremlin: Gremlin, *_: object, **__: object) -> GremlinResult:
    return GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED)


def _run_sequentially(gremlin_session: GremlinSession, flusher: PeriodicFlusher) -> list[GremlinResult]:
    with (
        patch.object(plugin, '_get_rootdir', return_value=Path()),
        patch.object(plugin, '_build_test_command', return_value=['pytest']),
        patch.object(plugin, '_check_cache_for_gremlin', return_value=None),
        patch.object(plugin, '_build_filtered_test_command', return_value=['pytest', MAPPED]),
        patch.object(plugin, '_test_gremlin', side_effect=_survived),
        patch.object(plugin, '_confirm_kill', side_effect=lambda result, *_, **__: result),
        patch.object(plugin, '_cache_gremlin_result'),
        patch.object(plugin, '_cache_flusher_for', return_value=flusher),
    ):
        return _run_mutation_testing(create_autospec(pytest.Session, instance=True), gremlin_session)


@pytest.mark.small
class DescribeSequentialRunFlushing:
    def it_flushes_after_each_gremlin_once_the_count_is_reached(self) -> None:
        flush = FlushAttempts(should_fail=False)

        _run_sequentially(_sequential_session(['g1', 'g2', 'g3']), PeriodicFlusher(flush, every_results=1))

        assert flush.attempts == 3

    def it_flushes_what_is_pending_when_the_run_finishes(self) -> None:
        flush = FlushAttempts(should_fail=False)

        results = _run_sequentially(_sequential_session(['g1', 'g2']), PeriodicFlusher(flush, every_results=100))

        assert flush.attempts == 1
        assert [(r.gremlin.gremlin_id, r.status) for r in results] == [
            ('g1', GremlinResultStatus.SURVIVED),
            ('g2', GremlinResultStatus.SURVIVED),
        ]


@pytest.mark.small
class DescribeCacheFlushFailureNotice:
    """The warning has to reach the terminal summary: pytest swallows log records during session finish."""

    def it_queues_one_terminal_notice_naming_the_error(self) -> None:
        cache = create_autospec(IncrementalCache, instance=True)
        cache.flush.side_effect = sqlite3.OperationalError('database or disk is full')
        session: GremlinSession = create_autospec(GremlinSession, instance=True)
        session.cache_enabled = True
        session.cache = cache
        session.terminal_notices = []
        flusher = plugin._cache_flusher_for(session)
        flusher.note_result()

        flusher.flush()
        flusher.flush()

        assert session.terminal_notices == [
            'pytest-gremlins: warning: could not write finished results to the cache '
            '(OperationalError: database or disk is full). The run continues and retries the writes; '
            'the cache retries them again when it closes.'
        ]
