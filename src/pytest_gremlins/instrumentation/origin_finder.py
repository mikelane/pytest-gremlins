"""Import hook that serves instrumented source for the file the import system resolves to (#597).

The finder never decides what a module is called. It asks the rest of ``sys.meta_path`` what would be
loaded for a name, and when the answer is a file that was instrumented it swaps in a loader that runs the
instrumented source. Names, ``sys.path`` precedence, packages, editable installs and the working directory
therefore behave exactly as they do without gremlins, in every execution mode.

This file is copied verbatim into the generated bootstrap script, which cannot import pytest-gremlins and
must start fast. Keep it standard-library only and free of ``from __future__`` imports. The one exception is
``_pytest.assertion.rewrite`` (and ``pathlib`` with it), imported lazily inside the loader and only when pytest's
assertion-rewrite hook served the module; they are never imported at module level.
"""

import ast
import base64
from collections.abc import Sequence
import copy
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


def _switch_gremlin_id(node: ast.AST) -> str | None:
    """Return the gremlin id of a ``mutated if __gremlin_active__ == 'id' else original`` switch, else ``None``."""
    if not (isinstance(node, ast.IfExp) and isinstance(node.test, ast.Compare)):
        return None
    test = node.test
    is_active_check = (
        isinstance(test.left, ast.Name)
        and test.left.id == '__gremlin_active__'
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
    )
    comparator = test.comparators[0] if is_active_check else None
    return str(comparator.value) if isinstance(comparator, ast.Constant) else None


class _SwitchIds(ast.NodeVisitor):
    """Collect the ids of every gremlin switch below a node, in source order."""

    def __init__(self) -> None:
        self.ids: list[str] = []

    def generic_visit(self, node: ast.AST) -> None:
        gremlin_id = _switch_gremlin_id(node)
        if gremlin_id is not None and gremlin_id not in self.ids:
            self.ids.append(gremlin_id)
        super().generic_visit(node)


class _ResolveSwitches(ast.NodeTransformer):
    """Replace every gremlin switch below a node by the branch one gremlin id (or none) selects."""

    def __init__(self, active_id: str | None) -> None:
        self._active_id = active_id

    def generic_visit(self, node: ast.AST) -> ast.AST:
        gremlin_id = _switch_gremlin_id(node)
        if gremlin_id is not None:
            chosen = node.body if gremlin_id == self._active_id else node.orelse  # type: ignore[attr-defined]
            return self.visit(chosen)  # type: ignore[no-any-return]
        return super().generic_visit(node)


def _specialize_assert(node: ast.Assert) -> ast.stmt:
    """Return ``node``, or when its condition holds gremlin switches, one plain assert per gremlin.

    pytest explains a failed assert by walking its condition, and a ``mutated if active == 'id' else original``
    switch is opaque to that walk: the message would lose every operand. Choosing the branch with an ``if``
    statement around ordinary asserts lets pytest's rewriter explain each of them as it does without gremlins.
    """
    collector = _SwitchIds()
    collector.visit(node.test)
    if node.msg is not None:
        collector.visit(node.msg)
    if not collector.ids:
        return node
    fallthrough: list[ast.stmt] = [_resolve_assert(node, None)]
    for gremlin_id in reversed(collector.ids):
        check = ast.Compare(
            left=ast.Name(id='__gremlin_active__', ctx=ast.Load()),
            ops=[ast.Eq()],
            comparators=[ast.Constant(value=gremlin_id)],
        )
        fallthrough = [ast.If(test=check, body=[_resolve_assert(node, gremlin_id)], orelse=fallthrough)]
    dispatch: ast.stmt = ast.copy_location(fallthrough[0], node)
    return ast.fix_missing_locations(dispatch)


def _resolve_assert(node: ast.Assert, active_id: str | None) -> ast.Assert:
    return _ResolveSwitches(active_id).visit(copy.deepcopy(node))  # type: ignore[no-any-return]


def _nested_statement_lists(node: ast.stmt) -> list[list[ast.stmt]]:
    """Return the statement lists directly inside ``node``: bodies, else-branches, handlers and match cases."""
    nested: list[list[ast.stmt]] = []
    for _, value in ast.iter_fields(node):
        if not isinstance(value, list):
            continue
        if value and all(isinstance(item, ast.stmt) for item in value):
            nested.append(value)
        else:
            nested.extend(item.body for item in value if isinstance(item, (ast.ExceptHandler, ast.match_case)))
    return nested


def _specialize_asserts(tree: ast.Module) -> ast.Module:
    """Specialize every assert in ``tree`` in place, walking statements with an explicit stack.

    A module the parent could instrument is nested as deep as a few hundred ``elif`` branches, which a recursive
    walk over the whole module cannot always survive. Only the one assert's own expression is walked
    recursively, and an assert that still overflows the stack is left as it is: it then runs with the
    switch in its condition, its message unexplained, but the module keeps every other rewritten assert.
    """
    pending: list[list[ast.stmt]] = [tree.body]
    while pending:
        statements = pending.pop()
        for index, statement in enumerate(statements):
            if isinstance(statement, ast.Assert):
                try:
                    statements[index] = _specialize_assert(statement)
                except RecursionError:
                    continue
            else:
                pending.extend(_nested_statement_lists(statement))
    return tree


class GremlinLoader(importlib.abc.Loader):
    """Compile the shipped instrumented tree, or its source when the tree is too deep, and execute it.

    The tree is compiled under the real file, so ``inspect.getsource``, linecache and tracebacks stay aligned
    with the file on disk. Unpickling or compiling a tree nested deeper than this process's stack can handle
    (a long ``elif`` chain) raises ``RecursionError``, and the interpreter's C recursion limit cannot be raised.
    The loader then compiles ``source``, the unparsed instrumented text, exactly as the releases before #563
    did: the import never fails because of AST depth, but that file's line numbers are the reflowed ones of
    the unparsed text. A parent that could not pickle the tree ships no tree at all.
    """

    def __init__(self, encoded_tree: str | None, original_loader: object = None, *, source: str) -> None:
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
            code = self._compile_source(module)
        exec(code, module.__dict__)  # noqa: S102

    def _compile_source(self, module: ModuleType) -> CodeType:
        """Compile the shipped source text, asserting like pytest would when pytest's hook served the module."""
        if not self._original_loader_is_rewrite_hook():
            # The source is our own AST transformation of the user's file, not untrusted input.
            return compile(self._source, module.__name__, 'exec')
        try:
            tree = ast.parse(self._source, module.__name__)
            self._rewrite_asserts(tree, self._source.encode(), module)
            return compile(tree, module.__name__, 'exec', dont_inherit=True)
        except RecursionError:
            # A tree too deep to unpickle is too deep to parse and rewrite: the module runs with plain asserts.
            return compile(self._source, module.__name__, 'exec')

    def _original_loader_is_rewrite_hook(self) -> bool:
        """Tell whether pytest's assertion-rewrite hook found this module, without importing pytest.

        The class is recognised by its module alone: the hook is the only loader that module puts on
        ``sys.meta_path``, so a rename of the class cannot silently turn rewriting off.
        """
        return type(self._original_loader).__module__ == '_pytest.assertion.rewrite'

    def _rewrite_asserts(self, tree: ast.Module, source_bytes: bytes, module: ModuleType) -> None:
        """Rewrite the asserts in ``tree`` and record the module as rewritten, as pytest's own loader does.

        The hook answers a spec with itself as the loader only for a module it decided to rewrite, so a module
        served by it keeps rewritten assertion messages even though this loader runs the instrumented tree.
        """
        # Imported here, never at the top: this file is inlined into a bootstrap that must not import pytest.
        from pathlib import Path  # noqa: PLC0415

        from _pytest.assertion.rewrite import rewrite_asserts  # noqa: PLC0415

        hook: Any = self._original_loader
        spec = module.__spec__
        origin: str = spec.origin  # type: ignore[union-attr, assignment]
        hook._rewritten_names[module.__name__] = Path(origin)
        rewrite_asserts(_specialize_asserts(tree), source_bytes, origin, hook.config)

    def _compile_tree(self, module: ModuleType) -> CodeType | None:
        """Return the shipped tree compiled under the real file, or ``None`` when it is absent or too deep."""
        if self._encoded_tree is None:
            return None
        try:
            # The parent wrote this tree into its own temp directory from our own transformation of the user's
            # file; it is not untrusted input.
            tree: ast.Module = pickle.loads(base64.b64decode(self._encoded_tree))  # noqa: S301  # nosec B301
            if self._original_loader_is_rewrite_hook():
                with open(module.__spec__.origin, 'rb') as source_file:  # type: ignore[union-attr, arg-type]  # noqa: PTH123
                    self._rewrite_asserts(tree, source_file.read(), module)
            return compile(tree, module.__spec__.origin, 'exec', dont_inherit=True)  # type: ignore[union-attr, arg-type]
        except RecursionError:
            # Silent on purpose: the loader falls back to the shipped source, as the class docstring explains.
            return None


class GremlinFinder(importlib.abc.MetaPathFinder):
    """Swap the loader of any spec whose origin is an instrumented file.

    Resolution proceeds in two paths: (1) path-based (normalize_origin) for direct matches,
    and (2) identity-based (inode) for differently-named aliases (symlinks, hard links).
    """

    # The bootstrap and the spawn hook (#604) each embed their own copy of this class, so ``isinstance`` cannot
    # tell whether a finder on ``sys.meta_path`` is ours. This marker can.
    is_gremlin_finder = True

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

    def serves(self, instrumented_sources: InstrumentedSources) -> bool:
        """Return whether this finder was built for exactly ``instrumented_sources``."""
        return self._instrumented_sources == instrumented_sources

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
        spec.loader = GremlinLoader(entry.get('tree'), spec.loader, source=entry['source'])
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
    """Register a finder for ``instrumented_sources`` ahead of every other finder and return it.

    Idempotent: the spawn hook (#604) and the bootstrap both call this in the same process, and one finder
    must serve it. A finder already installed for equal sources is moved to the front and returned; one for
    other sources is replaced.
    """
    installed_finders: list[Any] = [finder for finder in sys.meta_path if getattr(finder, 'is_gremlin_finder', False)]
    for installed in installed_finders:
        sys.meta_path.remove(installed)
        if installed.serves(instrumented_sources):
            sys.meta_path.insert(0, installed)
            return installed  # type: ignore[no-any-return]
    finder = GremlinFinder(instrumented_sources)
    sys.meta_path.insert(0, finder)
    return finder
