"""Leaving a PersistentWorkerPool on an error ends its workers instead of draining the queue (issue #1092)."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
import logging
from unittest.mock import (
    MagicMock,
    create_autospec,
    patch,
)

import pytest

from pytest_gremlins.parallel import pool as pool_module
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
        patch.object(pool_module, 'kill_process_trees') as trees,
        patch.object(pool_module, 'sigkill_pids') as pids,
        patch.object(pool_module, 'kill_children_of') as children,
    ):
        yield {'trees': trees, 'pids': pids, 'children': children}


def sigkilled_pids(kills: dict[str, MagicMock]) -> set[int]:
    return {pid for call in kills['pids'].call_args_list for pid in call.args[0]}


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

        assert sigkilled_pids(kills) == WORKER_PIDS

    @pytest.mark.usefixtures('kills')
    def it_marks_the_pool_as_stopped(self, pool: PersistentWorkerPool) -> None:
        pool.__exit__(GeneratorExit, GeneratorExit(), None)

        assert pool.is_running is False

    def it_sigkills_the_workers_after_a_successful_tree_kill(
        self, pool: PersistentWorkerPool, kills: dict[str, MagicMock]
    ) -> None:
        pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert sigkilled_pids(kills) == WORKER_PIDS

    def it_cancels_queued_work_when_the_tree_kill_is_interrupted(
        self, pool: PersistentWorkerPool, executor: MagicMock, kills: dict[str, MagicMock]
    ) -> None:
        kills['trees'].side_effect = KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)

    def it_sigkills_the_workers_when_the_tree_kill_is_interrupted(
        self, pool: PersistentWorkerPool, kills: dict[str, MagicMock]
    ) -> None:
        kills['trees'].side_effect = KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert sigkilled_pids(kills) == WORKER_PIDS

    def it_kills_the_descendants_if_the_tree_kill_fails(
        self, pool: PersistentWorkerPool, kills: dict[str, MagicMock]
    ) -> None:
        kills['trees'].side_effect = OSError('ps failed')

        pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert set(kills['children'].call_args.args[0]) == WORKER_PIDS

    def it_sigkills_the_remaining_workers_when_a_second_interrupt_lands_mid_kill(
        self, pool: PersistentWorkerPool, kills: dict[str, MagicMock]
    ) -> None:
        kills['pids'].side_effect = [KeyboardInterrupt, None]

        with pytest.raises(KeyboardInterrupt):
            pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert sigkilled_pids(kills) == WORKER_PIDS

    @pytest.mark.usefixtures('kills')
    def it_warns_which_workers_it_kills(self, pool: PersistentWorkerPool, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.parallel.persistent_pool'):
            pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        assert 'killing 2 pool worker(s) (pids [4101, 4102])' in caplog.text

    def it_cancels_queued_work_when_no_worker_process_exists_yet(
        self, pool: PersistentWorkerPool, executor: MagicMock, kills: dict[str, MagicMock]
    ) -> None:
        executor._processes = None

        pool.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        kills['trees'].assert_called_once_with(set())
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)

    def it_kills_nothing_when_the_pool_never_started(self, kills: dict[str, MagicMock]) -> None:
        never_started = PersistentWorkerPool(max_workers=2)

        never_started.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None)

        kills['trees'].assert_not_called()


@pytest.mark.small
class DescribeLeavingThePoolNormally:
    def it_waits_for_the_workers_and_kills_nothing(
        self, pool: PersistentWorkerPool, executor: MagicMock, kills: dict[str, MagicMock]
    ) -> None:
        pool.__exit__(None, None, None)

        executor.shutdown.assert_called_once_with(wait=True)
        kills['trees'].assert_not_called()

    def it_does_not_sigkill_the_workers(self, pool: PersistentWorkerPool, kills: dict[str, MagicMock]) -> None:
        pool.__exit__(None, None, None)

        kills['pids'].assert_not_called()
