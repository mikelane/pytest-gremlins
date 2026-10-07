"""Import hook that serves instrumented source for the file the import system resolves to (#597).

The finder never decides what a module is called. It asks the rest of ``sys.meta_path`` what would be
loaded for a name, and when the answer is a file that was instrumented it swaps in a loader that runs the
instrumented source. Names, ``sys.path`` precedence, packages, editable installs and the working directory
therefore behave exactly as they do without gremlins, in every execution mode.

This file is copied verbatim into the generated bootstrap script, which cannot import pytest-gremlins and
must start fast. Keep it standard-library only and free of ``from __future__`` imports.
"""

import base64
from collections.abc import Sequence
import importlib.abc
import importlib.machinery
import os
import pickle  # nosec B403 - only the parent's own temp-dir data is unpickled
import sys
import threading
from types import (
    CodeType,
    ModuleType,
)
from typing import Any

# Entries are decoded from sources.json and mix str, str | None and list[str] values.
InstrumentedEntry = dict[str, Any]
InstrumentedSources = dict[str, InstrumentedEntry]


def normalize_origin(path: str) -> str:
    """Return the one spelling of ``path`` that both sides of ``sources.json`` agree on."""
    return os.path.normcase(os.path.realpath(path))


def file_identity(path: str) -> str | None:
    """Return a spelling-independent identity of the file at ``path``, or ``None`` when it has none.

    Two paths that name one file on disk (a symlink, a hard link, a differently cased spelling on a
    case-insensitive filesystem) share an identity. Some Windows filesystems (ReFS, network drives)
    report an inode of 0 or reuse inodes, so a zero inode is no identity at all and is never matched.
    """
    try:
        status = os.stat(path)  # noqa: PTH116 - this file ships without pathlib to stay cheap to import
    except OSError:
        return None
    return None if status.st_ino == 0 else f'{status.st_dev}:{status.st_ino}'


class GremlinLoader(importlib.abc.Loader):
    """Compile the shipped instrumented tree, or its source when the tree is too deep, and execute it.

    The tree is compiled under the real file, so ``inspect.getsource``, linecache and tracebacks stay aligned
    with the file on disk. A tree nested deeper than this process's stack can handle (a long ``elif`` chain on
    Python 3.11/3.12) raises ``RecursionError`` when unpickled or compiled, and the interpreter's C recursion
    limit cannot be raised. The loader then compiles ``source``, the unparsed instrumented text, exactly as the
    releases before #563 did: the import never fails because of AST depth, but that file's line numbers are the
    reflowed ones of the unparsed text. A parent that could not pickle the tree ships no tree at all.
    """

    def __init__(self, encoded_tree: str | None, original_loader: object = None, source: str | None = None) -> None:
        # The parent ships the instrumented tree, never code: this interpreter's own -O / PYTHONOPTIMIZE and
        # warning filters apply, exactly as when it imports an unmodified file.
        self._encoded_tree = encoded_tree
        self._original_loader = original_loader
        self._source = source

    def get_resource_reader(self, fullname: str) -> object:  # noqa: D102
        # Package data (importlib.resources) is found through the loader that located the file.
        get_reader = getattr(self._original_loader, 'get_resource_reader', None)
        return None if get_reader is None else get_reader(fullname)

    def get_data(self, path: str) -> bytes:  # noqa: D102
        # pkgutil.get_data reads package data through the loader and gives up when it has no get_data.
        return self._original_loader.get_data(path)  # type: ignore[attr-defined, no-any-return]

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> None:  # noqa: ARG002, D102
        return None

    def exec_module(self, module: ModuleType) -> None:  # noqa: D102
        code = self._compile_tree(module)
        if code is None:
            # The source is our own AST transformation of the user's file, not untrusted input.
            code = compile(self._source, module.__name__, 'exec')  # type: ignore[arg-type]
        exec(code, module.__dict__)  # noqa: S102

    def _compile_tree(self, module: ModuleType) -> CodeType | None:
        """Return the shipped tree compiled under the real file, or ``None`` when it is absent or too deep."""
        if self._encoded_tree is None:
            return None
        try:
            # The parent wrote this tree into its own temp directory from our own transformation of the user's
            # file; it is not untrusted input.
            tree = pickle.loads(base64.b64decode(self._encoded_tree))  # noqa: S301  # nosec B301
            return compile(tree, module.__spec__.origin, 'exec', dont_inherit=True)  # type: ignore[union-attr, arg-type]
        except RecursionError:
            return None


class GremlinFinder(importlib.abc.MetaPathFinder):
    """Swap the loader of any spec whose origin is an instrumented file.

    Resolution proceeds in two paths: (1) path-based (normalize_origin) for direct matches,
    and (2) identity-based (inode) for differently-named aliases (symlinks, hard links).
    """

    def __init__(self, instrumented_sources: InstrumentedSources) -> None:
        self._instrumented_sources = instrumented_sources
        # Only a file named like an instrumented one is worth a realpath: most imports are not.
        # This is an optimization to avoid normalize_origin on unrelated imports.
        self._file_names = frozenset(
            name.lower()
            for entry in instrumented_sources.values()
            for name in entry.get('file_names') or [os.path.basename(entry['origin'])]  # noqa: PTH119
        )
        # A path spelling the string key does not know still names a file on disk, and the disk is the authority.
        # Used as a fallback when the path-based lookup misses (e.g., differently-named symlinks).
        self._keys_by_identity = {
            entry['identity']: key for key, entry in instrumented_sources.items() if entry.get('identity')
        }
        self._resolving: set[tuple[int, str]] = set()

    def find_spec(  # noqa: D102
        self, fullname: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        # Re-entry is per thread: another thread resolving the same name is not a loop.
        in_flight_lookup = (threading.get_ident(), fullname)
        if in_flight_lookup in self._resolving:
            return None
        self._resolving.add(in_flight_lookup)
        try:
            spec = self._spec_from_other_finders(fullname, path, target)
        except Exception:
            # Let the import system reach the failing finder itself and raise what it would have raised.
            return None
        finally:
            self._resolving.discard(in_flight_lookup)
        entry = self._instrumented_entry(spec)
        if spec is None or entry is None:
            # Hand back what the later finders answered: the import system would reach the same answer
            # by walking on, and walking on would ask each of them a second time.
            return spec
        spec.loader = GremlinLoader(entry.get('tree'), spec.loader, entry.get('source'))
        spec.cached = None
        return spec

    def _spec_from_other_finders(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None
    ) -> importlib.machinery.ModuleSpec | None:
        finders = list(sys.meta_path)
        start = finders.index(self) + 1 if self in finders else 0
        for finder in finders[start:]:
            if finder is self:
                continue
            find_spec = getattr(finder, 'find_spec', None)
            if find_spec is None:
                continue
            spec: importlib.machinery.ModuleSpec | None = find_spec(fullname, path, target)
            if spec is not None:
                return spec
        return None

    def _instrumented_entry(self, spec: importlib.machinery.ModuleSpec | None) -> InstrumentedEntry | None:
        if spec is None or not spec.origin or not spec.has_location:
            return None
        basename_hit = os.path.basename(spec.origin).lower() in self._file_names  # noqa: PTH119
        if basename_hit:
            # Try normalized origin (expensive path-based lookup) when basename matches
            entry = self._instrumented_sources.get(normalize_origin(spec.origin))
            if entry is not None:
                return entry
        # Try identity-based lookup (one stat call) for differently-named symlinks/hard links.
        # Also reaches basename hits that normalize_origin missed (e.g., case-insensitive mismatches).
        identity = file_identity(spec.origin)
        if identity:
            return self._instrumented_sources.get(self._keys_by_identity.get(identity, ''))
        return None


def install(instrumented_sources: InstrumentedSources) -> GremlinFinder:
    """Register a finder for ``instrumented_sources`` ahead of every other finder and return it."""
    finder = GremlinFinder(instrumented_sources)
    sys.meta_path.insert(0, finder)
    return finder
