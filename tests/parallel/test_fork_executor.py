"""Tests for ForkExecutor - fork-per-batch isolation for mutation testing.

ForkExecutor forks per batch, runs InProcessExecutor in the child process,
and pipes results back via JSON through os.pipe(). This provides process
isolation without the overhead of full subprocess startup.
"""

from __future__ import annotations

import sys
import types

import pytest

from pytest_gremlins.parallel.fork_executor import ForkExecutor
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import GremlinResultStatus


def _make_instrumented_module(module_name: str) -> types.ModuleType:
    """Create a fake instrumented module with __gremlin_active__ switching.

    The module has a function ``is_positive(x)`` that checks ``x > 0``.
    When ``__gremlin_active__ == 'g001'``, the comparison flips to ``x >= 0``
    (boundary mutation), so ``is_positive(0)`` returns True instead of False.
    """
    module = types.ModuleType(module_name)
    module.__gremlin_active__ = None  # type: ignore[attr-defined]

    # Safe: compiling our own test fixture code, not user input.
    exec(  # noqa: S102
        compile(
            """
def is_positive(x):
    if __gremlin_active__ == 'g001':
        return x >= 0  # mutated: > becomes >=
    return x > 0  # original
""",
            module_name,
            'exec',
        ),
        module.__dict__,
    )
    sys.modules[module_name] = module
    return module


def _make_test_module(module_name: str, target_module_name: str) -> types.ModuleType:
    """Create a test module that catches the g001 boundary mutation."""
    test_module = types.ModuleType(module_name)

    # Safe: compiling our own test fixture code, not user input.
    exec(  # noqa: S102
        compile(
            f"""
import sys

def test_zero_is_not_positive():
    target = sys.modules['{target_module_name}']
    assert target.is_positive(0) is False
""",
            module_name,
            'exec',
        ),
        test_module.__dict__,
    )
    sys.modules[module_name] = test_module
    return test_module


@pytest.fixture
def instrumented_module() -> types.ModuleType:
    """Provide a fake instrumented module, cleaned up after test."""
    mod_name = '_test_fork_gremlins_target'
    module = _make_instrumented_module(mod_name)
    yield module  # type: ignore[misc]
    sys.modules.pop(mod_name, None)


@pytest.fixture
def test_module(instrumented_module: types.ModuleType) -> types.ModuleType:
    """Provide a test module that exercises the instrumented module."""
    mod_name = '_test_fork_gremlins_tests'
    module = _make_test_module(mod_name, instrumented_module.__name__)
    yield module  # type: ignore[misc]
    sys.modules.pop(mod_name, None)


@pytest.mark.small
class DescribeForkExecutorCreation:
    """Tests for ForkExecutor instantiation."""

    def it_creates_with_default_values(self) -> None:
        executor = ForkExecutor()
        assert executor.batch_size == 50
        assert executor.timeout == 30

    def it_creates_with_custom_batch_size(self) -> None:
        executor = ForkExecutor(batch_size=10)
        assert executor.batch_size == 10

    def it_creates_with_custom_timeout(self) -> None:
        executor = ForkExecutor(timeout=60)
        assert executor.timeout == 60


@pytest.mark.medium
class DescribeForkExecutorExecution:
    """Tests for ForkExecutor.execute() with fork-per-batch isolation."""

    def it_returns_results_for_each_gremlin(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        executor = ForkExecutor()
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert len(results) == 1
        assert isinstance(results[0], WorkerResult)
        assert results[0].gremlin_id == 'g001'

    def it_detects_mutations(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        executor = ForkExecutor()
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert results[0].status == GremlinResultStatus.ZAPPED

    def it_handles_empty_list(self) -> None:
        executor = ForkExecutor()
        results = executor.execute(
            gremlin_ids=[],
            gremlin_module_map={},
            test_specs=[],
        )
        assert results == []

    def it_partitions_into_batches(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        """With batch_size=1, each gremlin runs in its own fork."""
        executor = ForkExecutor(batch_size=1)
        gremlin_module_map = {
            'g001': instrumented_module.__name__,
            'g002': instrumented_module.__name__,
        }
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001', 'g002'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert len(results) == 2
        assert results[0].gremlin_id == 'g001'
        assert results[1].gremlin_id == 'g002'


@pytest.mark.medium
class DescribeForkExecutorIsolation:
    """Triangulation tests: fork isolation preserves parent process state."""

    def it_does_not_leak_gremlin_active_to_parent(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        """After forked execution, parent module's __gremlin_active__ stays None."""
        executor = ForkExecutor()
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert instrumented_module.__gremlin_active__ is None  # type: ignore[attr-defined]

    def it_records_execution_time(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        executor = ForkExecutor()
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert results[0].execution_time_ms is not None
        assert results[0].execution_time_ms >= 0


@pytest.mark.small
class DescribeForkExecutorFallback:
    """Tests for ForkExecutor fallback when fork is unavailable."""

    def it_falls_back_without_fork(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When os.fork is unavailable, falls back to InProcessExecutor."""
        monkeypatch.delattr('os.fork', raising=False)

        executor = ForkExecutor()
        results = executor.execute(
            gremlin_ids=[],
            gremlin_module_map={},
            test_specs=[],
        )

        assert results == []

    def it_falls_back_and_still_detects_mutations(
        self,
        monkeypatch: pytest.MonkeyPatch,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        """Fallback path still detects mutations via InProcessExecutor."""
        monkeypatch.delattr('os.fork', raising=False)

        executor = ForkExecutor()
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert len(results) == 1
        assert results[0].status == GremlinResultStatus.ZAPPED

    def it_falls_back_and_reports_survived_for_undetected_mutation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        instrumented_module: types.ModuleType,
    ) -> None:
        """Fallback path reports SURVIVED when no test catches the mutation."""
        monkeypatch.delattr('os.fork', raising=False)

        passing_mod = types.ModuleType('_test_fork_fallback_passing')
        code = 'def test_always_passes():\n    assert True\n'
        exec(compile(code, '_test_fork_fallback_passing', 'exec'), passing_mod.__dict__)  # noqa: S102
        sys.modules['_test_fork_fallback_passing'] = passing_mod

        try:
            executor = ForkExecutor()
            gremlin_module_map = {'g001': instrumented_module.__name__}
            test_specs = ['_test_fork_fallback_passing::test_always_passes']

            results = executor.execute(
                gremlin_ids=['g001'],
                gremlin_module_map=gremlin_module_map,
                test_specs=test_specs,
            )

            assert len(results) == 1
            assert results[0].status == GremlinResultStatus.SURVIVED
        finally:
            sys.modules.pop('_test_fork_fallback_passing', None)


@pytest.mark.medium
class DescribeForkExecutorChildProcess:
    """Tests covering the child process JSON serialization path (pid==0 branch).

    These tests exercise the full fork path including JSON serialization in the
    child and deserialization in the parent. Coverage tools cannot instrument the
    child side of os.fork(), but the parent-side deserialization (lines 114-136)
    and the correctness of the round-trip prove the child code works.
    """

    def it_serializes_survived_status_through_pipe(
        self,
        instrumented_module: types.ModuleType,
    ) -> None:
        """SURVIVED result round-trips correctly through fork+JSON pipe."""
        passing_mod = types.ModuleType('_test_fork_child_passing')
        code = 'def test_always_passes():\n    assert True\n'
        exec(compile(code, '_test_fork_child_passing', 'exec'), passing_mod.__dict__)  # noqa: S102
        sys.modules['_test_fork_child_passing'] = passing_mod

        try:
            executor = ForkExecutor(batch_size=1)
            gremlin_module_map = {'g001': instrumented_module.__name__}
            test_specs = ['_test_fork_child_passing::test_always_passes']

            results = executor.execute(
                gremlin_ids=['g001'],
                gremlin_module_map=gremlin_module_map,
                test_specs=test_specs,
            )

            assert len(results) == 1
            assert results[0].status == GremlinResultStatus.SURVIVED
            assert results[0].gremlin_id == 'g001'
            assert results[0].execution_time_ms is not None
            assert results[0].execution_time_ms >= 0
            assert results[0].killing_test is None
        finally:
            sys.modules.pop('_test_fork_child_passing', None)

    def it_serializes_zapped_status_with_killing_test_through_pipe(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        """ZAPPED result includes killing_test after fork+JSON round-trip."""
        executor = ForkExecutor(batch_size=1)
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert results[0].status == GremlinResultStatus.ZAPPED
        assert results[0].killing_test == f'{test_module.__name__}::test_zero_is_not_positive'

    def it_handles_multiple_gremlins_in_single_batch(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        """Multiple gremlins in one batch all come back through the pipe."""
        executor = ForkExecutor(batch_size=10)
        gremlin_module_map = {
            'g001': instrumented_module.__name__,
            'g002': instrumented_module.__name__,
            'g003': instrumented_module.__name__,
        }
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001', 'g002', 'g003'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert len(results) == 3
        assert all(r.gremlin_id in ('g001', 'g002', 'g003') for r in results)

    def it_serializes_error_output_through_pipe(
        self,
        instrumented_module: types.ModuleType,
    ) -> None:
        """A gremlin that encounters a test error round-trips error_output through the pipe.

        Note: _run_test_spec catches all exceptions and returns False (zapped),
        so the error_output field is only populated when _test_single_gremlin
        itself raises. In normal flow, a failing test produces ZAPPED, not ERROR.
        """
        failing_mod = types.ModuleType('_test_fork_child_error')
        code = 'def test_fails():\n    assert False\n'
        exec(compile(code, '_test_fork_child_error', 'exec'), failing_mod.__dict__)  # noqa: S102
        sys.modules['_test_fork_child_error'] = failing_mod

        try:
            executor = ForkExecutor(batch_size=1)
            gremlin_module_map = {'g001': instrumented_module.__name__}
            test_specs = ['_test_fork_child_error::test_fails']

            results = executor.execute(
                gremlin_ids=['g001'],
                gremlin_module_map=gremlin_module_map,
                test_specs=test_specs,
            )

            assert len(results) == 1
            # Test failure is caught by _run_test_spec, reported as ZAPPED
            assert results[0].status == GremlinResultStatus.ZAPPED
            assert results[0].error_output is not None
        finally:
            sys.modules.pop('_test_fork_child_error', None)
