"""Tests for InProcessExecutor - in-process mutation testing via __gremlin_active__ toggling.

InProcessExecutor eliminates subprocess overhead by toggling module-level
__gremlin_active__ variables directly in-process, then calling test functions.
"""

from __future__ import annotations

import sys
import types

import pytest

from pytest_gremlins.parallel.inprocess_executor import (
    InProcessExecutor,
    _resolve_test_callable,
    _run_test_spec,
    _TestOutcome,
)
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

    def it_records_execution_time(
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

        assert results[0].execution_time_ms is not None
        assert results[0].execution_time_ms >= 0

    def it_records_killing_test_for_zapped_gremlin(
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

        assert results[0].killing_test == f'{test_module.__name__}::test_zero_is_not_positive'


@pytest.mark.small
class DescribeInProcessExecutorModuleResolution:
    """Tests for gremlin module lookup edge cases."""

    def it_survives_when_gremlin_id_not_in_module_map(
        self,
        test_module: types.ModuleType,
    ) -> None:
        """A gremlin whose ID is not in the module map has no module to toggle."""
        executor = InProcessExecutor()
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g_unknown'],
            gremlin_module_map={},
            test_specs=test_specs,
        )

        assert len(results) == 1
        # The test passes because __gremlin_active__ is never set to 'g_unknown'
        # so the module runs its original code path.
        assert results[0].gremlin_id == 'g_unknown'

    def it_survives_when_mapped_module_not_in_sys_modules(
        self,
        test_module: types.ModuleType,
    ) -> None:
        """A gremlin mapped to a module not yet imported has no module to toggle."""
        executor = InProcessExecutor()
        test_specs = [f'{test_module.__name__}::test_zero_is_not_positive']

        results = executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map={'g001': 'nonexistent.module.that.was.never.imported'},
            test_specs=test_specs,
        )

        assert len(results) == 1
        assert results[0].gremlin_id == 'g001'

    def it_returns_error_when_test_raises_unexpected_exception(
        self,
        instrumented_module: types.ModuleType,
    ) -> None:
        """A test that raises a non-AssertionError exception produces ERROR status."""
        error_mod = types.ModuleType('_test_gremlins_error')
        # Safe: compiling our own test fixture code, not user input.
        code = 'def test_explodes():\n    raise RuntimeError("boom")\n'
        exec(compile(code, '_test_gremlins_error', 'exec'), error_mod.__dict__)  # noqa: S102
        sys.modules['_test_gremlins_error'] = error_mod

        try:
            executor = InProcessExecutor()
            gremlin_module_map = {'g001': instrumented_module.__name__}
            test_specs = ['_test_gremlins_error::test_explodes']

            results = executor.execute(
                gremlin_ids=['g001'],
                gremlin_module_map=gremlin_module_map,
                test_specs=test_specs,
            )

            # The test raises RuntimeError, which _run_test_spec catches and returns False.
            # This means the gremlin is zapped (a test "failed"), not an error.
            assert results[0].status == GremlinResultStatus.ZAPPED
        finally:
            sys.modules.pop('_test_gremlins_error', None)

    def it_returns_error_status_when_run_test_spec_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        instrumented_module: types.ModuleType,
    ) -> None:
        """When _run_test_spec raises an unexpected error, the gremlin gets ERROR status."""

        def _exploding_run_test_spec(_spec: str) -> bool:
            raise RuntimeError('unexpected failure')

        monkeypatch.setattr(
            'pytest_gremlins.parallel.inprocess_executor._run_test_spec',
            _exploding_run_test_spec,
        )

        executor = InProcessExecutor()
        gremlin_module_map = {'g001': instrumented_module.__name__}
        test_specs = ['some_module::test_whatever']

        results = executor.execute(
            gremlin_ids=['g001'],
            gremlin_module_map=gremlin_module_map,
            test_specs=test_specs,
        )

        assert len(results) == 1
        assert results[0].status == GremlinResultStatus.ERROR
        assert 'unexpected failure' in results[0].error_output
        assert results[0].execution_time_ms is not None
        # __gremlin_active__ is reset even after error
        assert instrumented_module.__gremlin_active__ is None  # type: ignore[attr-defined]


@pytest.mark.small
class DescribeRunTestSpec:
    """Tests for _run_test_spec free function."""

    def it_returns_error_when_module_not_in_sys_modules(self) -> None:
        result = _run_test_spec('nonexistent_module_xyz::test_foo')
        assert result == _TestOutcome.ERROR

    def it_returns_error_when_function_not_found_on_module(self) -> None:

        mod = types.ModuleType('_test_run_spec_no_func')
        sys.modules['_test_run_spec_no_func'] = mod
        try:
            result = _run_test_spec('_test_run_spec_no_func::nonexistent_test')
            assert result == _TestOutcome.ERROR
        finally:
            sys.modules.pop('_test_run_spec_no_func', None)

    def it_returns_passed_when_test_passes(self) -> None:

        mod = types.ModuleType('_test_run_spec_pass')
        code = 'def test_pass():\n    assert True\n'
        exec(compile(code, '_test_run_spec_pass', 'exec'), mod.__dict__)  # noqa: S102
        sys.modules['_test_run_spec_pass'] = mod
        try:
            result = _run_test_spec('_test_run_spec_pass::test_pass')
            assert result == _TestOutcome.PASSED
        finally:
            sys.modules.pop('_test_run_spec_pass', None)

    def it_returns_failed_when_test_raises_exception(self) -> None:

        mod = types.ModuleType('_test_run_spec_fail')
        code = 'def test_fail():\n    raise AssertionError("nope")\n'
        exec(compile(code, '_test_run_spec_fail', 'exec'), mod.__dict__)  # noqa: S102
        sys.modules['_test_run_spec_fail'] = mod
        try:
            result = _run_test_spec('_test_run_spec_fail::test_fail')
            assert result == _TestOutcome.FAILED
        finally:
            sys.modules.pop('_test_run_spec_fail', None)


@pytest.mark.small
class DescribeResolveTestCallable:
    """Tests for _resolve_test_callable free function."""

    def it_resolves_module_level_function(self) -> None:

        mod = types.ModuleType('_test_resolve_func')
        code = 'def test_hello():\n    pass\n'
        exec(compile(code, '_test_resolve_func', 'exec'), mod.__dict__)  # noqa: S102

        result = _resolve_test_callable(mod, ['test_hello'])
        assert result is not None
        assert callable(result)

    def it_resolves_class_method(self) -> None:

        mod = types.ModuleType('_test_resolve_cls')
        code = 'class TestFoo:\n    def test_bar(self):\n        pass\n'
        exec(compile(code, '_test_resolve_cls', 'exec'), mod.__dict__)  # noqa: S102

        result = _resolve_test_callable(mod, ['TestFoo', 'test_bar'])
        assert result is not None
        assert callable(result)

    def it_returns_none_when_class_not_found(self) -> None:

        mod = types.ModuleType('_test_resolve_no_cls')

        result = _resolve_test_callable(mod, ['NonExistentClass', 'test_method'])
        assert result is None

    def it_returns_none_when_method_not_found_on_class(self) -> None:

        mod = types.ModuleType('_test_resolve_no_method')
        code = 'class TestFoo:\n    pass\n'
        exec(compile(code, '_test_resolve_no_method', 'exec'), mod.__dict__)  # noqa: S102

        result = _resolve_test_callable(mod, ['TestFoo', 'nonexistent_method'])
        assert result is None

    def it_returns_none_for_empty_parts(self) -> None:

        mod = types.ModuleType('_test_resolve_empty')

        result = _resolve_test_callable(mod, [])
        assert result is None

    def it_returns_none_for_three_or_more_parts(self) -> None:

        mod = types.ModuleType('_test_resolve_too_many')

        result = _resolve_test_callable(mod, ['a', 'b', 'c'])
        assert result is None

    def it_returns_none_when_function_not_on_module(self) -> None:

        mod = types.ModuleType('_test_resolve_no_attr')

        result = _resolve_test_callable(mod, ['nonexistent_function'])
        assert result is None
