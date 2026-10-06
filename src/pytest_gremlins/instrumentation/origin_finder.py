"""Import hook that serves instrumented source for the file the import system resolves to (#597).

The finder never decides what a module is called. It asks the rest of ``sys.meta_path`` what would be
loaded for a name, and when the answer is a file that was instrumented it swaps in a loader that runs the
instrumented source. Names, ``sys.path`` precedence, packages, editable installs and the working directory
therefore behave exactly as they do without gremlins, in every execution mode.

This file is copied verbatim into the generated bootstrap script, which cannot import pytest-gremlins and
must start fast. Keep it standard-library only and free of ``from __future__`` imports.
"""

from collections.abc import Sequence
import importlib.abc
import importlib.machinery
import os
import sys
from types import ModuleType

InstrumentedSources = dict[str, dict[str, str]]


def normalize_origin(path: str) -> str:
    """Return the one spelling of ``path`` that both sides of ``sources.json`` agree on."""
    return os.path.normcase(os.path.realpath(path))


class GremlinLoader(importlib.abc.Loader):
    """Execute instrumented source in the namespace of the module being imported."""

    def __init__(self, source: str, module_name: str) -> None:
        self._source = source
        self._module_name = module_name

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:  # noqa: ARG002, D102
        return None

    def exec_module(self, module: ModuleType) -> None:  # noqa: D102
        # The source is our own AST transformation of the user's file, not untrusted input.
        code = compile(self._source, self._module_name, 'exec')
        exec(code, module.__dict__)  # noqa: S102


class GremlinFinder(importlib.abc.MetaPathFinder):
    """Swap the loader of any spec whose origin is an instrumented file."""

    is_gremlin_finder = True

    def __init__(self, instrumented_sources: InstrumentedSources) -> None:
        self._instrumented_sources = instrumented_sources
        self._resolving: set[str] = set()

    def find_spec(  # noqa: D102
        self, fullname: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname in self._resolving:
            return None
        self._resolving.add(fullname)
        try:
            spec = self._spec_from_other_finders(fullname, path, target)
        except Exception:
            # Let the import system reach the failing finder itself and raise what it would have raised.
            return None
        finally:
            self._resolving.discard(fullname)
        entry = self._instrumented_entry(spec)
        if spec is None or entry is None:
            return None
        spec.loader = GremlinLoader(entry['source'], fullname)
        spec.cached = None
        return spec

    def _spec_from_other_finders(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None
    ) -> importlib.machinery.ModuleSpec | None:
        finders = list(sys.meta_path)
        start = finders.index(self) + 1 if self in finders else 0
        for finder in finders[start:]:
            if getattr(finder, 'is_gremlin_finder', False):
                continue
            find_spec = getattr(finder, 'find_spec', None)
            if find_spec is None:
                continue
            spec: importlib.machinery.ModuleSpec | None = find_spec(fullname, path, target)
            if spec is not None:
                return spec
        return None

    def _instrumented_entry(self, spec: importlib.machinery.ModuleSpec | None) -> dict[str, str] | None:
        if spec is None or not spec.origin or not spec.has_location:
            return None
        return self._instrumented_sources.get(normalize_origin(spec.origin))


def install(instrumented_sources: InstrumentedSources) -> GremlinFinder:
    """Register a finder for ``instrumented_sources`` ahead of every other finder and return it."""
    finder = GremlinFinder(instrumented_sources)
    sys.meta_path.insert(0, finder)
    return finder
