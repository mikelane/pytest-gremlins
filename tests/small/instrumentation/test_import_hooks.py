"""Tests for the import hooks used in mutation switching.

These tests verify that GremlinFinder and GremlinLoader correctly intercept
module imports and inject instrumented code during mutation testing.
"""

from __future__ import annotations

import ast
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
import sys
import types
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.instrumentation.import_hooks import (
    GremlinFinder,
    GremlinLoader,
    register_import_hooks,
    unregister_import_hooks,
)
from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR


if TYPE_CHECKING:
    from collections.abc import Generator


class TestGremlinFinder:
    """Tests for GremlinFinder - the import hook finder."""

    def test_implements_meta_path_finder_protocol(self):
        finder = GremlinFinder(instrumented_modules={})

        assert isinstance(finder, MetaPathFinder)

    def test_find_spec_returns_none_for_non_instrumented_module(self):
        finder = GremlinFinder(instrumented_modules={})

        result = finder.find_spec('some_module', None)

        assert result is None

    def test_find_spec_returns_module_spec_for_instrumented_module(self):
        tree = ast.parse('x = 1')
        instrumented_modules = {'my_module': tree}
        finder = GremlinFinder(instrumented_modules=instrumented_modules)

        result = finder.find_spec('my_module', None)

        assert result is not None
        assert isinstance(result, ModuleSpec)
        assert result.name == 'my_module'

    def test_find_spec_returns_none_for_submodule_when_only_parent_instrumented(self):
        tree = ast.parse('x = 1')
        instrumented_modules = {'my_package': tree}
        finder = GremlinFinder(instrumented_modules=instrumented_modules)

        result = finder.find_spec('my_package.submodule', None)

        assert result is None


class TestGremlinLoader:
    """Tests for GremlinLoader - the import hook loader."""

    def test_implements_loader_protocol(self):
        tree = ast.parse('x = 1')
        loader = GremlinLoader(tree, module_name='test_module')

        assert isinstance(loader, Loader)

    def test_create_module_returns_none_to_use_default(self):
        tree = ast.parse('x = 1')
        loader = GremlinLoader(tree, module_name='test_module')
        spec = ModuleSpec('test_module', loader)

        result = loader.create_module(spec)

        # Returning None tells Python to use default module creation
        assert result is None

    def test_exec_module_executes_instrumented_ast(self):
        source = 'result = 42'
        tree = ast.parse(source)
        ast.fix_missing_locations(tree)
        loader = GremlinLoader(tree, module_name='test_module')

        module = types.ModuleType('test_module')
        loader.exec_module(module)

        assert module.result == 42  # type: ignore[attr-defined]

    def test_exec_module_injects_gremlin_active_variable(self):
        source = 'value = __gremlin_active__'
        tree = ast.parse(source)
        ast.fix_missing_locations(tree)
        loader = GremlinLoader(tree, module_name='test_module')

        module = types.ModuleType('test_module')
        loader.exec_module(module)

        # The loader should inject __gremlin_active__ from environment
        assert hasattr(module, '__gremlin_active__')

    def test_exec_module_reads_active_gremlin_from_environment(self, monkeypatch):
        monkeypatch.setenv(ACTIVE_GREMLIN_ENV_VAR, 'g001')

        source = 'active_id = __gremlin_active__'
        tree = ast.parse(source)
        ast.fix_missing_locations(tree)
        loader = GremlinLoader(tree, module_name='test_module')

        module = types.ModuleType('test_module')
        loader.exec_module(module)

        assert module.active_id == 'g001'  # type: ignore[attr-defined]


class TestImportHookRegistration:
    """Tests for registering and unregistering import hooks."""

    @pytest.fixture
    def clean_meta_path(self) -> Generator[None, None, None]:
        """Ensure sys.meta_path is cleaned up after tests."""
        original_meta_path = sys.meta_path.copy()
        yield
        sys.meta_path[:] = original_meta_path

    def test_register_hooks_adds_finder_to_meta_path(self, clean_meta_path):  # noqa: ARG002
        register_import_hooks(instrumented_modules={})

        finder_types = [type(f) for f in sys.meta_path]
        assert GremlinFinder in finder_types

    def test_unregister_hooks_removes_finder_from_meta_path(self, clean_meta_path):  # noqa: ARG002
        register_import_hooks(instrumented_modules={})
        unregister_import_hooks()

        finder_types = [type(f) for f in sys.meta_path]
        assert GremlinFinder not in finder_types

    def test_unregister_hooks_is_safe_when_not_registered(self, clean_meta_path):  # noqa: ARG002
        # Should not raise
        unregister_import_hooks()


class TestImportHookIntegration:
    """Integration tests for import hooks with actual module imports."""

    @pytest.fixture
    def clean_meta_path(self) -> Generator[None, None, None]:
        """Ensure sys.meta_path is cleaned up after tests."""
        original_meta_path = sys.meta_path.copy()
        yield
        sys.meta_path[:] = original_meta_path

    @pytest.fixture
    def clean_modules(self) -> Generator[None, None, None]:
        """Ensure test modules are removed from sys.modules."""
        test_module_name = '_gremlin_test_module'
        original_modules = sys.modules.copy()
        yield
        if test_module_name in sys.modules:
            del sys.modules[test_module_name]
        # Restore original state
        for key in list(sys.modules.keys()):
            if key not in original_modules:
                del sys.modules[key]

    def test_import_hook_intercepts_instrumented_module_import(
        self,
        clean_meta_path,  # noqa: ARG002
        clean_modules,  # noqa: ARG002
    ):
        # Create an instrumented AST
        source = 'test_value = "instrumented"'
        tree = ast.parse(source)
        ast.fix_missing_locations(tree)

        instrumented_modules = {'_gremlin_test_module': tree}
        register_import_hooks(instrumented_modules)

        try:
            import _gremlin_test_module  # noqa: PLC0415

            assert _gremlin_test_module.test_value == 'instrumented'
        finally:
            unregister_import_hooks()
