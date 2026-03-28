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
