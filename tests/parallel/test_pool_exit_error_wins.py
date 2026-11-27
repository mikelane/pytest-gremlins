"""Leaving the pool on an error reports that error even when abandoning the workers fails (issue #976)."""

from __future__ import annotations

import logging
import os

import pytest

from pytest_gremlins.parallel import pool as pool_module
from pytest_gremlins.parallel import worker_kill
from pytest_gremlins.parallel.pool import WorkerPool


class DescribeLeavingThePoolOnAnErrorWhenAbandoningFails:
    @pytest.mark.small
    def it_lets_the_original_error_propagate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_abandon(_pool: WorkerPool) -> None:
            msg = 'cannot list the workers'
            raise RuntimeError(msg)

        monkeypatch.setattr(WorkerPool, '_abandon_workers', failing_abandon)

        with pytest.raises(KeyError, match='original'), WorkerPool(max_workers=1):
            raise KeyError('original')

    @pytest.mark.small
    def it_still_shuts_the_pool_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def failing_abandon(_pool: WorkerPool) -> None:
            msg = 'cannot list the workers'
            raise RuntimeError(msg)

        monkeypatch.setattr(WorkerPool, '_abandon_workers', failing_abandon)
        pool = WorkerPool(max_workers=1)

        with pytest.raises(KeyError), pool:
            raise KeyError('original')

        assert pool._shutdown_called
        assert pool._executor is None

    @pytest.mark.small
    def it_logs_a_warning_that_names_the_abandon_failure(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def failing_abandon(_pool: WorkerPool) -> None:
            msg = 'cannot list the workers'
            raise RuntimeError(msg)

        monkeypatch.setattr(WorkerPool, '_abandon_workers', failing_abandon)

        with pytest.raises(KeyError), WorkerPool(max_workers=1):
            raise KeyError('original')

        assert [record.levelno for record in caplog.records] == [logging.WARNING]
        assert 'cannot list the workers' in caplog.text


class _RecordingExecutor:
    def __init__(self, worker_pids: list[int]) -> None:
        self._processes = dict.fromkeys(worker_pids)
        self.shutdowns: list[tuple[bool, bool]] = []

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        self.shutdowns.append((wait, cancel_futures))


@pytest.mark.small
class DescribeAbandoningTheWorkersWhenTheTreeKillFails:
    def it_kills_each_workers_children_and_then_the_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        killed: list[int] = []

        def failing_kill(_pids: object) -> None:
            msg = 'the process table is unreadable'
            raise RuntimeError(msg)

        monkeypatch.setattr(pool_module, 'kill_process_trees', failing_kill)
        monkeypatch.setattr(worker_kill, 'descendants_of', lambda worker_pid: [worker_pid + 1])
        monkeypatch.setattr(os, 'kill', lambda pid, _signal: killed.append(pid))
        pool = WorkerPool(max_workers=1)
        executor = _RecordingExecutor([100])
        pool._executor = executor  # type: ignore[assignment]

        pool._abandon_workers()

        assert killed == [101, 100]
        assert executor.shutdowns == [(False, True)]
        assert pool._executor is None

    def it_still_kills_the_worker_when_its_children_cannot_be_listed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        killed: list[int] = []

        def failing(_pid: object) -> list[int]:
            msg = 'the process table is unreadable'
            raise RuntimeError(msg)

        monkeypatch.setattr(pool_module, 'kill_process_trees', failing)
        monkeypatch.setattr(worker_kill, 'descendants_of', failing)
        monkeypatch.setattr(os, 'kill', lambda pid, _signal: killed.append(pid))
        pool = WorkerPool(max_workers=1)
        pool._executor = _RecordingExecutor([100])  # type: ignore[assignment]

        pool._abandon_workers()

        assert killed == [100]

    def it_does_nothing_on_a_second_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[object] = []
        monkeypatch.setattr(pool_module, 'kill_process_trees', calls.append)
        monkeypatch.setattr(os, 'kill', lambda pid, _signal: calls.append(pid))
        pool = WorkerPool(max_workers=1)
        pool._executor = _RecordingExecutor([100])  # type: ignore[assignment]
        pool._abandon_workers()
        calls.clear()

        pool._abandon_workers()

        assert calls == []


@pytest.mark.small
class DescribeAbandoningTheWorkersWhenASecondInterruptArrives:
    """A second Ctrl-C during the tree kill must still cancel the queue, or interpreter exit drains it (#980)."""

    @pytest.mark.parametrize('interrupted_helper', ['kill_process_trees', 'sigkill_pids'])
    def it_cancels_the_queued_gremlins(self, monkeypatch: pytest.MonkeyPatch, interrupted_helper: str) -> None:
        def interrupted_kill(_pids: object) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(pool_module, 'kill_process_trees', lambda _pids: None)
        monkeypatch.setattr(pool_module, 'sigkill_pids', lambda _pids: None)
        monkeypatch.setattr(pool_module, interrupted_helper, interrupted_kill)
        pool = WorkerPool(max_workers=1)
        executor = _RecordingExecutor([100])
        pool._executor = executor  # type: ignore[assignment]

        with pytest.raises(KeyboardInterrupt):
            pool._abandon_workers()

        assert executor.shutdowns == [(False, True)]

    def it_still_kills_the_workers_when_the_tree_kill_is_interrupted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def interrupted_kill(_pids: object) -> None:
            raise KeyboardInterrupt

        killed: list[int] = []
        monkeypatch.setattr(pool_module, 'kill_process_trees', interrupted_kill)
        monkeypatch.setattr(pool_module, 'sigkill_pids', killed.extend)
        pool = WorkerPool(max_workers=1)
        executor = _RecordingExecutor([100, 200])
        pool._executor = executor  # type: ignore[assignment]

        with pytest.raises(KeyboardInterrupt):
            pool._abandon_workers()

        assert (sorted(killed), executor.shutdowns) == ([100, 200], [(False, True)])


@pytest.mark.small
class DescribeAbandoningTheWorkersWhenInterruptedBeforeTheKills:
    """A Ctrl-C while the workers are listed or the warning is logged must still cancel the queue (#980)."""

    def it_cancels_the_queue_when_listing_the_worker_pids_is_interrupted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def interrupted(_pool: WorkerPool, _executor: object) -> set[int]:
            raise KeyboardInterrupt

        monkeypatch.setattr(WorkerPool, '_worker_pids', interrupted)
        pool = WorkerPool(max_workers=1)
        executor = _RecordingExecutor([100])
        pool._executor = executor  # type: ignore[assignment]

        with pytest.raises(KeyboardInterrupt):
            pool._abandon_workers()

        assert executor.shutdowns == [(False, True)]

    def it_cancels_the_queue_when_the_abandon_warning_is_interrupted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def interrupted(*_args: object, **_kwargs: object) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(pool_module.logger, 'warning', interrupted)
        monkeypatch.setattr(pool_module, 'kill_process_trees', lambda _pids: None)
        monkeypatch.setattr(pool_module, 'sigkill_pids', lambda _pids: None)
        pool = WorkerPool(max_workers=1)
        executor = _RecordingExecutor([100])
        pool._executor = executor  # type: ignore[assignment]

        with pytest.raises(KeyboardInterrupt):
            pool._abandon_workers()

        assert executor.shutdowns == [(False, True)]

    def it_still_kills_the_workers_when_the_abandon_warning_is_interrupted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def interrupted(*_args: object, **_kwargs: object) -> None:
            raise KeyboardInterrupt

        killed: list[int] = []
        monkeypatch.setattr(pool_module.logger, 'warning', interrupted)
        monkeypatch.setattr(pool_module, 'kill_process_trees', lambda _pids: None)
        monkeypatch.setattr(pool_module, 'sigkill_pids', killed.extend)
        pool = WorkerPool(max_workers=1)
        executor = _RecordingExecutor([100, 200])
        pool._executor = executor  # type: ignore[assignment]

        with pytest.raises(KeyboardInterrupt):
            pool._abandon_workers()

        assert (sorted(killed), executor.shutdowns) == ([100, 200], [(False, True)])


@pytest.mark.small
class DescribeAbandoningTheWorkersWhenADirectKillIsInterrupted:
    """A Ctrl-C while one worker is killed must not spare the workers after it (#980)."""

    def it_still_kills_the_remaining_workers_when_the_first_kill_is_interrupted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        signalled: list[int] = []

        def interrupted_on_first(pid: int, _signal: int) -> None:
            signalled.append(pid)
            if len(signalled) == 1:
                raise KeyboardInterrupt

        monkeypatch.setattr(pool_module, 'kill_process_trees', lambda _pids: None)
        monkeypatch.setattr(os, 'kill', interrupted_on_first)
        pool = WorkerPool(max_workers=2)
        pool._executor = _RecordingExecutor([100, 200])  # type: ignore[assignment]

        with pytest.raises(KeyboardInterrupt):
            pool._abandon_workers()

        assert sorted(signalled) == [100, 200]

    def it_re_raises_the_first_interrupt_when_every_kill_is_interrupted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raised: list[BaseException] = []

        def interrupted_every_time(_pid: int, _signal: int) -> None:
            error = KeyboardInterrupt(len(raised))
            raised.append(error)
            raise error

        monkeypatch.setattr(pool_module, 'kill_process_trees', lambda _pids: None)
        monkeypatch.setattr(os, 'kill', interrupted_every_time)
        pool = WorkerPool(max_workers=2)
        pool._executor = _RecordingExecutor([100, 200])  # type: ignore[assignment]

        with pytest.raises(KeyboardInterrupt) as excinfo:
            pool._abandon_workers()

        assert (len(raised), excinfo.value is raised[0]) == (2, True)
