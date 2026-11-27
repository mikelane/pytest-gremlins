"""Leaving a PersistentWorkerPool on an error ends its workers instead of draining the queue (issue #1092)."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import (
    MagicMock,
    create_autospec,
    patch,
)

import pytest

from pytest_gremlins.parallel import persistent_pool
from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool

WORKER_PIDS = {4101, 4102}


@pytest.fixture
def executor() -> MagicMock:
    stand_in: MagicMock = create_autospec(ProcessPoolExecutor, instance=True)
    stand_in._processes = dict.fromkeys(WORKER_PIDS)
    return stand_in


@pytest.fixture
def pool(executor: MagicMock) -> PersistentWorkerPool:
    pool = PersistentWorkerPool(max_workers=2)
    pool._executor = executor
    pool._running = True
    return pool


@pytest.fixture
def kills() -> Iterator[dict[str, MagicMock]]:
    with (
        patch.object(persistent_pool, 'kill_process_trees') as trees,
        patch.object(persistent_pool, 'sigkill_pids') as pids,
    ):
        yield {'trees': trees, 'pids': pids}


@pytest.mark.small
class DescribeLeavingThePoolOnAnError:
    @pytest.mark.usefixtures('kills')
    def it_cancels_queued_work_without_waiting(self, pool: PersistentWorkerPool, executor: MagicMock) -> None:
        pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)

    def it_kills_every_worker_and_its_test_commands(
        self, pool: PersistentWorkerPool, kills: dict[str, MagicMock]
    ) -> None:
        pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert set(kills['trees'].call_args.args[0]) == WORKER_PIDS

    def it_kills_the_workers_directly_if_the_tree_kill_fails(
        self, pool: PersistentWorkerPool, kills: dict[str, MagicMock]
    ) -> None:
        kills['trees'].side_effect = OSError('ps failed')

        pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert set(kills['pids'].call_args.args[0]) == WORKER_PIDS

    @pytest.mark.usefixtures('kills')
    def it_marks_the_pool_as_stopped(self, pool: PersistentWorkerPool) -> None:
        pool.__exit__(GeneratorExit, GeneratorExit(), None)

        assert pool.is_running is False


@pytest.mark.small
class DescribeLeavingThePoolNormally:
    def it_waits_for_the_workers_and_kills_nothing(
        self, pool: PersistentWorkerPool, executor: MagicMock, kills: dict[str, MagicMock]
    ) -> None:
        pool.__exit__(None, None, None)

        executor.shutdown.assert_called_once_with(wait=True)
        kills['trees'].assert_not_called()
