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
