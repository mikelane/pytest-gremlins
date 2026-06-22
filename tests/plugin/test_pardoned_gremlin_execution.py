"""Tests that pardoned gremlins are handled without running tests.

Critical regression guard: pardoned gremlins must NEVER have subprocess tests
run against them. The plugin must short-circuit to PARDONED status immediately.
"""

from __future__ import annotations

import ast
from unittest.mock import MagicMock

import pytest

from pytest_gremlins import plugin as plugin_module
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _immediate_result_if_pardoned,
    _run_batch_mutation_testing,
    _run_mutation_testing,
    _run_parallel_mutation_testing,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)


def _make_pardoned_gremlin() -> Gremlin:
    node = ast.parse('a // b', mode='eval').body
    return Gremlin(
        gremlin_id='g_pardon_001',
        file_path='example.py',
        line_number=5,
        original_node=node,
        mutated_node=node,
        operator_name='arithmetic',
        description='// to /',
        pardoned=True,
        pardon_reason='equivalent: floor division is integer arithmetic',
    )


def _make_unpardoned_gremlin() -> Gremlin:
    node = ast.parse('a < b', mode='eval').body
    return Gremlin(
        gremlin_id='g_active_001',
        file_path='example.py',
        line_number=7,
        original_node=node,
        mutated_node=node,
        operator_name='comparison',
        description='< to <=',
    )


@pytest.mark.small
class DescribePardonedGremlinNeverRunsSubprocess:
    """Guard: subprocess tests are NEVER run for pardoned gremlins.

    Tests the wiring between the execution loop and the pardon short-circuit.
    A correct helper that is never called by the loop would still break the feature.
    """

    def it_run_mutation_testing_never_calls_test_gremlin_for_pardoned_gremlin(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        calls: list[Gremlin] = []

        def fake_test_gremlin(gremlin: Gremlin, *_args: object, **_kwargs: object) -> GremlinResult:
            calls.append(gremlin)
            return GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED)

        monkeypatch.setattr(plugin_module, '_test_gremlin', fake_test_gremlin)
        monkeypatch.setattr(plugin_module, '_get_rootdir', lambda _: tmp_path)
        monkeypatch.setattr(plugin_module, '_build_test_command', lambda *_: ['pytest'])
        monkeypatch.setattr(plugin_module, '_select_tests_for_gremlin_prioritized', lambda _g, _: [])
        monkeypatch.setattr(plugin_module, '_check_cache_for_gremlin', lambda *_a, **_kw: None)

        pardoned = _make_pardoned_gremlin()
        mock_session = MagicMock(spec=pytest.Session)
        gremlin_session = GremlinSession(gremlins=[pardoned])

        results = _run_mutation_testing(mock_session, gremlin_session)

        assert len(results) == 1
        assert results[0].status == GremlinResultStatus.PARDONED
        assert len(calls) == 0, '_test_gremlin was called for a pardoned gremlin'

    def it_run_batch_mutation_testing_returns_pardoned_without_spawning_subprocess(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        # Patch BatchExecutor to fail loudly if instantiated — proves it's never reached
        def fail_if_batch_executor_instantiated(*_args: object, **_kwargs: object) -> None:
            raise AssertionError('BatchExecutor was instantiated for a pardoned gremlin')

        monkeypatch.setattr(plugin_module, 'BatchExecutor', fail_if_batch_executor_instantiated)
        monkeypatch.setattr(plugin_module, '_get_rootdir', lambda _: tmp_path)
        monkeypatch.setattr(plugin_module, '_build_test_command', lambda *_: ['pytest'])
        monkeypatch.setattr(plugin_module, '_select_tests_for_gremlin_prioritized', lambda _g, _: [])
        monkeypatch.setattr(plugin_module, '_check_cache_for_gremlin', lambda *_a, **_kw: None)

        pardoned = _make_pardoned_gremlin()
        mock_session = MagicMock(spec=pytest.Session)
        gremlin_session = GremlinSession(gremlins=[pardoned])

        results = _run_batch_mutation_testing(mock_session, gremlin_session)

        assert len(results) == 1
        assert results[0].status == GremlinResultStatus.PARDONED

    def it_run_parallel_mutation_testing_returns_pardoned_without_spawning_subprocess(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        # Patch WorkerPool to fail loudly if instantiated — proves it's never reached
        def fail_if_worker_pool_instantiated(*_args: object, **_kwargs: object) -> None:
            raise AssertionError('WorkerPool was instantiated for a pardoned gremlin')

        monkeypatch.setattr(plugin_module, 'WorkerPool', fail_if_worker_pool_instantiated)
        monkeypatch.setattr(plugin_module, '_get_rootdir', lambda _: tmp_path)
        monkeypatch.setattr(plugin_module, '_build_test_command', lambda *_: ['pytest'])
        monkeypatch.setattr(plugin_module, '_select_tests_for_gremlin_prioritized', lambda _g, _: [])
        monkeypatch.setattr(plugin_module, '_check_cache_for_gremlin', lambda *_a, **_kw: None)

        pardoned = _make_pardoned_gremlin()
        mock_session = MagicMock(spec=pytest.Session)
        gremlin_session = GremlinSession(gremlins=[pardoned])

        results = _run_parallel_mutation_testing(mock_session, gremlin_session)

        assert len(results) == 1
        assert results[0].status == GremlinResultStatus.PARDONED


@pytest.mark.small
class DescribeImmediateResultIfPardoned:
    """Tests for _immediate_result_if_pardoned short-circuit logic."""

    def it_returns_pardoned_result_for_pardoned_gremlin(self) -> None:
        gremlin = _make_pardoned_gremlin()
        result = _immediate_result_if_pardoned(gremlin)

        assert result is not None
        assert result.status == GremlinResultStatus.PARDONED
        assert result.gremlin is gremlin

    def it_returns_none_for_unpardoned_gremlin(self) -> None:
        gremlin = _make_unpardoned_gremlin()
        result = _immediate_result_if_pardoned(gremlin)

        assert result is None

    def it_pardoned_result_has_no_killing_test(self) -> None:
        gremlin = _make_pardoned_gremlin()
        result = _immediate_result_if_pardoned(gremlin)

        assert result is not None
        assert result.killing_test is None

    def it_pardoned_result_has_no_execution_time(self) -> None:
        gremlin = _make_pardoned_gremlin()
        result = _immediate_result_if_pardoned(gremlin)

        assert result is not None
        assert result.execution_time_ms is None
