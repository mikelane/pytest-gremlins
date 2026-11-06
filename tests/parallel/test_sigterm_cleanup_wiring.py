"""The worker pools and the mutation run install the SIGTERM cleanup of live test commands (#975)."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import signal
import sys
from typing import Any

import pytest

from pytest_gremlins import process_tree
from pytest_gremlins.parallel import (
    persistent_pool,
    pool,
)
from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool
from pytest_gremlins.parallel.pool import WorkerPool
from pytest_gremlins.parallel.pool_config import PoolConfig


class _RecordingExecutor(ProcessPoolExecutor):
    created_with: dict[str, Any] = {}  # noqa: RUF012 - read back by the tests

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).created_with = kwargs
        super().__init__(*args, **kwargs)


@pytest.mark.medium
class DescribeWorkerPoolsInstallSigtermCleanup:
    def it_gives_the_worker_pool_workers_the_sigterm_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pool, 'ProcessPoolExecutor', _RecordingExecutor)

        with WorkerPool(max_workers=1):
            pass

        assert _RecordingExecutor.created_with['initializer'] is process_tree.install_sigterm_cleanup

    def it_gives_the_persistent_pool_workers_the_sigterm_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(persistent_pool, 'ProcessPoolExecutor', _RecordingExecutor)

        with PersistentWorkerPool.from_config(PoolConfig(max_workers=1, warmup=False)):
            pass

        assert _RecordingExecutor.created_with['initializer'] is process_tree.install_sigterm_cleanup


@pytest.mark.small
@pytest.mark.skipif(sys.platform == 'win32', reason='SIGTERM handlers are POSIX')
class DescribeMutationRunSigtermCleanup:
    def it_runs_the_dispatched_mutation_run_under_the_sigterm_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pytest_gremlins import plugin  # noqa: PLC0415 - patched below, only needed here

        seen: list[object] = []
        before = signal.getsignal(signal.SIGTERM)

        def fake_run(*_args: object) -> list[object]:
            seen.append(signal.getsignal(signal.SIGTERM))
            return []

        monkeypatch.setattr(plugin, '_run_mutation_testing', fake_run)
        session = type('S', (), {'batch_enabled': False, 'parallel_enabled': False})()

        plugin._dispatch_mutation_run(None, session)  # type: ignore[arg-type]

        assert (seen[0] is not before, signal.getsignal(signal.SIGTERM)) == (True, before)
