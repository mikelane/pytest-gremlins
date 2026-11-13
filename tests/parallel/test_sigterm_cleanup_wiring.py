"""The worker pools and the mutation run install the SIGTERM cleanup of live test commands (#975)."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from types import SimpleNamespace
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

import pytest

from pytest_gremlins import (
    plugin,
    process_tree,
    verdicts,
)
from pytest_gremlins.parallel import (
    persistent_pool,
    pool,
)
from pytest_gremlins.parallel.exit_codes import COLLECTION_KILLING_TEST
from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool
from pytest_gremlins.parallel.pool import WorkerPool
from pytest_gremlins.parallel.pool_config import PoolConfig
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingExecutor(ProcessPoolExecutor):
    created_with: dict[str, Any] = {}  # noqa: RUF012 - read back by the tests

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).created_with = kwargs
        super().__init__(*args, **kwargs)


@pytest.mark.medium
class DescribeWorkerPoolsInstallSigtermCleanup:
    def it_gives_the_worker_pool_workers_the_sigterm_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_RecordingExecutor, 'created_with', {})  # no stale value from another test
        monkeypatch.setattr(pool, 'ProcessPoolExecutor', _RecordingExecutor)

        with WorkerPool(max_workers=1):
            pass

        assert _RecordingExecutor.created_with['initializer'] is pool._init_worker

    def it_keeps_the_sigterm_cleanup_when_the_worker_also_reports_its_starts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(process_tree, 'install_worker_sigterm_cleanup', lambda: calls.append('sigterm cleanup'))
        monkeypatch.setattr(pool, '_start_reports', None)
        reports = object()

        pool._init_worker(cast('Any', reports))

        assert (calls, pool._start_reports is reports) == (['sigterm cleanup'], True)

    def it_gives_the_persistent_pool_workers_the_sigterm_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_RecordingExecutor, 'created_with', {})  # no stale value from another test
        monkeypatch.setattr(persistent_pool, 'ProcessPoolExecutor', _RecordingExecutor)

        with PersistentWorkerPool.from_config(PoolConfig(max_workers=1, warmup=False)):
            pass

        assert _RecordingExecutor.created_with['initializer'] is process_tree.install_worker_sigterm_cleanup


@pytest.mark.small
class DescribeConfirmationThreadPoolInterrupt:
    def it_kills_the_live_commands_when_the_confirmation_pool_is_interrupted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        was_killed: list[bool] = []

        def interrupted(*_args: object) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(verdicts, '_collect_unmutated', interrupted)
        monkeypatch.setattr(process_tree, 'kill_live_commands', lambda: was_killed.append(True))
        collection_kill = cast(
            'GremlinResult',
            SimpleNamespace(status=GremlinResultStatus.ZAPPED, killing_test=COLLECTION_KILLING_TEST),
        )
        gremlin_session = cast('plugin.GremlinSession', SimpleNamespace(unmutated_load_checks={}, parallel_workers=1))

        with pytest.raises(KeyboardInterrupt):
            verdicts._prefill_collection_kill_confirmations([(collection_kill, ['t.py::t'])], gremlin_session, tmp_path)

        assert was_killed == [True]
