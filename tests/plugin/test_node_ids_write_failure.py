"""A failed disk write while launching gremlins scores ERROR instead of aborting the session (issue #625)."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest

from pytest_gremlins import plugin as plugin_module
from pytest_gremlins.control_run import (
    ControlRunOutcome,
    run_control,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.plugin import (
    GremlinSession,
    _run_batch_mutation_testing,
    _run_mutation_testing,
    _run_parallel_mutation_testing,
    _verify_suite_loads_unmutated,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

DISK_FULL = 'No space left on device'
FAILING_NODE_ID = 't.py::test_bad'
NODE_IDS = {'test_bad': FAILING_NODE_ID, 'test_ok': 't.py::test_ok'}


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


def _statuses(results: list[GremlinResult]) -> dict[str, GremlinResultStatus]:
    return {result.gremlin.gremlin_id: result.status for result in results}


@pytest.fixture
def session(tmp_path: Path) -> GremlinSession:
    return GremlinSession(
        enabled=True,
        instrumented_dir=tmp_path,
        gremlins=[_gremlin('g_bad'), _gremlin('g_ok')],
        test_node_ids=dict(NODE_IDS),
    )


@pytest.fixture(autouse=True)
def stubbed_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    selections = {'g_bad': ['test_bad'], 'g_ok': ['test_ok']}
    monkeypatch.setattr(plugin_module, '_get_rootdir', lambda _config: tmp_path)
    monkeypatch.setattr(plugin_module, '_build_test_command', lambda *_a, **_kw: ['pytest'])
    monkeypatch.setattr(
        plugin_module, '_select_tests_for_gremlin_prioritized', lambda gremlin, _s: selections[gremlin.gremlin_id]
    )
    monkeypatch.setattr(plugin_module, '_check_cache_for_gremlin', lambda *_a, **_kw: None)
    monkeypatch.setattr(plugin_module, '_confirm_kill', lambda result, *_a, **_kw: result)
    monkeypatch.setattr(plugin_module, '_confirm_pooled_result', lambda result, *_a, **_kw: result)


def _fail_node_ids_write_when_selecting(monkeypatch: pytest.MonkeyPatch, failing: str) -> None:
    def write_or_fail(command: Sequence[str], node_ids: Sequence[str], _directory: Path | None) -> list[str]:
        if failing in node_ids:
            raise OSError(28, DISK_FULL)
        return [*command, *node_ids]

    monkeypatch.setattr(plugin_module, 'command_with_node_ids_file', write_or_fail)


@pytest.mark.small
class DescribeSequentialNodeIdsWriteFailure:
    def it_scores_the_gremlin_error_and_still_runs_the_others(
        self, session: GremlinSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fail_node_ids_write_when_selecting(monkeypatch, FAILING_NODE_ID)
        ran: list[str] = []

        def survive(gremlin: Gremlin, *_a: object, **_kw: object) -> GremlinResult:
            ran.append(gremlin.gremlin_id)
            return GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED)

        monkeypatch.setattr(plugin_module, '_test_gremlin', survive)

        results = _run_mutation_testing(MagicMock(spec=pytest.Session), session)

        assert _statuses(results) == {
            'g_bad': GremlinResultStatus.ERROR,
            'g_ok': GremlinResultStatus.SURVIVED,
        }
        assert ran == ['g_ok']

    def it_explains_the_failure_in_the_error_output(
        self, session: GremlinSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fail_node_ids_write_when_selecting(monkeypatch, FAILING_NODE_ID)
        monkeypatch.setattr(
            plugin_module,
            '_test_gremlin',
            lambda gremlin, *_a, **_kw: GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED),
        )

        results = _run_mutation_testing(MagicMock(spec=pytest.Session), session)

        errored = next(result for result in results if result.gremlin.gremlin_id == 'g_bad')
        assert 'node ids' in errored.error_output
        assert DISK_FULL in errored.error_output


class _ImmediatePool:
    """Stands in for WorkerPool: every submitted gremlin survives at once."""

    def __init__(self, **_kwargs: object) -> None:
        self.submitted: list[str] = []

    def __enter__(self) -> _ImmediatePool:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def submit(self, *, gremlin_id: str, **_kwargs: Any) -> Future[WorkerResult]:
        self.submitted.append(gremlin_id)
        future: Future[WorkerResult] = Future()
        future.set_result(WorkerResult(gremlin_id=gremlin_id, status=GremlinResultStatus.SURVIVED))
        return future


@pytest.mark.small
class DescribeParallelNodeIdsWriteFailure:
    def it_scores_the_gremlin_error_and_still_runs_the_others(
        self, session: GremlinSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fail_node_ids_write_when_selecting(monkeypatch, FAILING_NODE_ID)
        monkeypatch.setattr(plugin_module, 'WorkerPool', _ImmediatePool)

        results = _run_parallel_mutation_testing(MagicMock(spec=pytest.Session), session)

        assert _statuses(results) == {
            'g_bad': GremlinResultStatus.ERROR,
            'g_ok': GremlinResultStatus.SURVIVED,
        }

    def it_explains_the_failure_in_the_error_output(
        self, session: GremlinSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fail_node_ids_write_when_selecting(monkeypatch, FAILING_NODE_ID)
        monkeypatch.setattr(plugin_module, 'WorkerPool', _ImmediatePool)

        results = _run_parallel_mutation_testing(MagicMock(spec=pytest.Session), session)

        errored = next(result for result in results if result.gremlin.gremlin_id == 'g_bad')
        assert DISK_FULL in errored.error_output


class _ExplodingBatchExecutor:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def execute(self, **_kwargs: object) -> list[WorkerResult]:
        raise AssertionError('a batch with no command must not be executed')


@pytest.mark.small
class DescribeBatchNodeIdsWriteFailure:
    def it_reports_every_uncached_gremlin_as_error_instead_of_raising(
        self, session: GremlinSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fail_node_ids_write_when_selecting(monkeypatch, FAILING_NODE_ID)
        monkeypatch.setattr(plugin_module, 'BatchExecutor', _ExplodingBatchExecutor)
        session.batch_size = 2

        results = _run_batch_mutation_testing(MagicMock(spec=pytest.Session), session)

        assert _statuses(results) == {
            'g_bad': GremlinResultStatus.ERROR,
            'g_ok': GremlinResultStatus.ERROR,
        }
        assert all(DISK_FULL in result.error_output for result in results)


@pytest.mark.small
class DescribeUnattributableMarkerWriteFailure:
    def it_warns_instead_of_raising_when_the_marker_cannot_be_written(
        self, session: GremlinSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            plugin_module,
            'run_control',
            create_autospec(
                run_control, return_value=ControlRunOutcome(loads_cleanly=False, output='ImportError', seconds=0.1)
            ),
        )

        def refuse_write(_self: Path, *_a: object, **_kw: object) -> int:
            raise OSError(28, DISK_FULL)

        monkeypatch.setattr(Path, 'write_text', refuse_write)

        _verify_suite_loads_unmutated(SimpleNamespace(config=None), session)  # type: ignore[arg-type]

        assert session.load_failures_attributable is False
        assert DISK_FULL in capsys.readouterr().err
