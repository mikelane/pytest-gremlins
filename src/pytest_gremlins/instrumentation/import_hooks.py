"""Import hooks for mutation switching.

This module provides the import hooks (sys.meta_path) that intercept module
imports and inject instrumented code during mutation testing. This is the
mechanism that connects the transformed AST to actual code execution.

The import hooks work as follows:
1. GremlinFinder is registered on sys.meta_path
2. When Python imports a module, GremlinFinder.find_spec() is called
3. If the module has instrumented code, return a ModuleSpec with GremlinLoader
4. GremlinLoader.exec_module() compiles and executes the instrumented AST
5. The __gremlin_active__ variable is injected from ACTIVE_GREMLIN env var

Example:
    >>> import ast
    >>> from pytest_gremlins.instrumentation.import_hooks import (
    ...     register_import_hooks,
    ...     unregister_import_hooks,
    ... )
    >>> tree = ast.parse('test_value = 42')
    >>> _ = ast.fix_missing_locations(tree)
    >>> register_import_hooks({'_test_mod': tree})
    >>> # Now importing _test_mod will execute the instrumented AST
    >>> unregister_import_hooks()
"""

from __future__ import annotations

from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
import os
import sys
from typing import TYPE_CHECKING

from pytest_gremlins.instrumentation.switcher import ACTIVE_GREMLIN_ENV_VAR


if TYPE_CHECKING:
    import ast
    from collections.abc import Sequence
    import types


class GremlinLoader(Loader):
    """Loader that executes instrumented AST code.

    This loader compiles and executes a pre-transformed AST instead of
    loading code from disk. It also injects the __gremlin_active__ variable
    from the ACTIVE_GREMLIN environment variable.
    """

    def __init__(self, tree: ast.Module, module_name: str) -> None:
        """Initialize the loader with an instrumented AST.

        Args:
            tree: The instrumented AST to execute.
            module_name: The name of the module being loaded.
        """
        self._tree = tree
        self._module_name = module_name

    def create_module(self, spec: ModuleSpec) -> types.ModuleType | None:  # noqa: ARG002
        """Return None to use default module creation semantics.

        Args:
            spec: The module specification.

        Returns:
            None to use default module creation.
        """
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        """Execute the instrumented AST in the module's namespace.

        This method:
        1. Injects __gremlin_active__ from the ACTIVE_GREMLIN env var
        2. Compiles the instrumented AST
        3. Executes it in the module's namespace

        Args:
            module: The module to execute code in.
        """
        # Inject __gremlin_active__ from environment variable
        module.__gremlin_active__ = os.environ.get(ACTIVE_GREMLIN_ENV_VAR)  # type: ignore[attr-defined]

        # Compile and execute the instrumented AST
        # Note: This exec is intentional - we're executing pre-validated, transformed AST
        # from our own instrumentation process, not arbitrary user input.
        code = compile(self._tree, self._module_name, 'exec')
        exec(code, module.__dict__)  # noqa: S102


class GremlinFinder(MetaPathFinder):
    """Finder that intercepts imports for instrumented modules.

    This finder is registered on sys.meta_path and returns a ModuleSpec
    with GremlinLoader for modules that have instrumented code available.
    """

    def __init__(self, instrumented_modules: dict[str, ast.Module]) -> None:
        """Initialize the finder with instrumented module ASTs.

        Args:
            instrumented_modules: Mapping of module names to their instrumented ASTs.
        """
        self._instrumented_modules = instrumented_modules

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,  # noqa: ARG002
        target: types.ModuleType | None = None,  # noqa: ARG002
    ) -> ModuleSpec | None:
        """Find a module spec for the given module name.

        Args:
            fullname: The fully qualified module name.
            path: The module search path (unused).
            target: The target module (unused).

        Returns:
            ModuleSpec with GremlinLoader if module is instrumented, None otherwise.
        """
        if fullname not in self._instrumented_modules:
            return None

        tree = self._instrumented_modules[fullname]
        loader = GremlinLoader(tree, fullname)
        return ModuleSpec(fullname, loader)


# Global reference to the registered finder (for cleanup)
_registered_finder: GremlinFinder | None = None


def register_import_hooks(instrumented_modules: dict[str, ast.Module]) -> None:
    """Register import hooks for instrumented modules.

    This function adds a GremlinFinder to sys.meta_path that will intercept
    imports for the specified modules and load instrumented code instead.

    Args:
        instrumented_modules: Mapping of module names to their instrumented ASTs.
    """
    global _registered_finder  # noqa: PLW0603
    unregister_import_hooks()  # Clean up any existing registration

    _registered_finder = GremlinFinder(instrumented_modules)
    sys.meta_path.insert(0, _registered_finder)


def unregister_import_hooks() -> None:
    """Unregister import hooks from sys.meta_path.

    This function removes any previously registered GremlinFinder from
    sys.meta_path. It is safe to call even if no hooks are registered.
    """
    global _registered_finder  # noqa: PLW0603

    if _registered_finder is not None and _registered_finder in sys.meta_path:
        sys.meta_path.remove(_registered_finder)

    _registered_finder = None

    # Also remove any GremlinFinder instances that might have been added
    # by other means (defensive cleanup)
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, GremlinFinder)]
