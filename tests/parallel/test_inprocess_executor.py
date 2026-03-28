"""Tests for InProcessExecutor - in-process mutation testing via __gremlin_active__ toggling.

InProcessExecutor eliminates subprocess overhead by toggling module-level
__gremlin_active__ variables directly in-process, then calling test functions.
"""

from __future__ import annotations

import sys
import types

import pytest

from pytest_gremlins.parallel.inprocess_executor import InProcessExecutor
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

    # This is safe: we are compiling our own test fixture code, not user input.
    code = """
def is_positive(x):
    if __gremlin_active__ == 'g001':
        return x >= 0  # mutated: > becomes >=
    return x > 0  # original
"""
    exec(compile(code, module_name, 'exec'), module.__dict__)  # noqa: S102
    sys.modules[module_name] = module
    return module


def _make_test_module(module_name: str, target_module_name: str) -> types.ModuleType:
    """Create a test module that catches the g001 boundary mutation.

    The test calls ``is_positive(0)`` and asserts it returns False.
    Under g001 mutation, ``is_positive(0)`` returns True, so the test fails.
    """
    test_module = types.ModuleType(module_name)

    # This is safe: we are compiling our own test fixture code, not user input.
    code = f"""
import sys

def test_zero_is_not_positive():
    target = sys.modules['{target_module_name}']
    assert target.is_positive(0) is False
"""
    exec(compile(code, module_name, 'exec'), test_module.__dict__)  # noqa: S102
    sys.modules[module_name] = test_module
    return test_module


@pytest.fixture
def instrumented_module() -> types.ModuleType:
    """Provide a fake instrumented module, cleaned up after test."""
    mod_name = '_test_gremlins_target'
    module = _make_instrumented_module(mod_name)
    yield module  # type: ignore[misc]
    sys.modules.pop(mod_name, None)


@pytest.fixture
def test_module(instrumented_module: types.ModuleType) -> types.ModuleType:
    """Provide a test module that exercises the instrumented module."""
    mod_name = '_test_gremlins_tests'
    module = _make_test_module(mod_name, instrumented_module.__name__)
    yield module  # type: ignore[misc]
    sys.modules.pop(mod_name, None)


@pytest.mark.small
class DescribeInProcessExecutorCreation:
    """Tests for InProcessExecutor instantiation."""

    def it_creates_with_default_timeout(self) -> None:
        executor = InProcessExecutor()
        assert executor.timeout == 30

    def it_creates_with_custom_timeout(self) -> None:
        executor = InProcessExecutor(timeout=60)
        assert executor.timeout == 60


@pytest.mark.small
class DescribeInProcessExecutorExecution:
    """Tests for InProcessExecutor.execute() with __gremlin_active__ toggling."""

    def it_returns_worker_result_for_each_gremlin(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        executor = InProcessExecutor()
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

    def it_detects_mutation_as_zapped(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        executor = InProcessExecutor()
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert results[0].status == GremlinResultStatus.ZAPPED

    def it_returns_empty_list_for_empty_gremlin_ids(self) -> None:
        executor = InProcessExecutor()
        results = executor.execute(
            gremlin_ids=[],
            gremlin_module_map={},
            test_specs=[],
        )
        assert results == []

    def it_reports_survived_when_no_test_catches_mutation(
        self,
        instrumented_module: types.ModuleType,
    ) -> None:
        """A gremlin with no matching test specs survives."""
        passing_mod = types.ModuleType('_test_gremlins_passing')
        # This is safe: we are compiling our own test fixture code, not user input.
        code = 'def test_always_passes():\n    assert True\n'
        exec(compile(code, '_test_gremlins_passing', 'exec'), passing_mod.__dict__)  # noqa: S102
        sys.modules['_test_gremlins_passing'] = passing_mod

        try:
            executor = InProcessExecutor()
            gremlin_module_map = {'g001': instrumented_module.__name__}
            test_specs = ['_test_gremlins_passing::test_always_passes']

            results = executor.execute(
                gremlin_ids=['g001'],
                gremlin_module_map=gremlin_module_map,
                test_specs=test_specs,
            )

            assert results[0].status == GremlinResultStatus.SURVIVED
        finally:
            sys.modules.pop('_test_gremlins_passing', None)

    def it_resets_gremlin_active_after_each_gremlin(
        self,
        instrumented_module: types.ModuleType,
        test_module: types.ModuleType,
    ) -> None:
        executor = InProcessExecutor()
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert instrumented_module.__gremlin_active__ is None  # type: ignore[attr-defined]
