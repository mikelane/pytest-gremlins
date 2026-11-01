"""Fingerprint of the installed code that decides what a cached verdict means."""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass
from functools import cached_property
from importlib.metadata import (
    Distribution,
    PackagePath,
    distributions,
    entry_points,
)
import inspect
import json
from pathlib import Path
import posixpath
import re
import sys
import sysconfig
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.request import url2pathname
import uuid

from pytest_gremlins.cache.hasher import ContentHasher
from pytest_gremlins.operators.entry_points import ENTRY_POINT_GROUP

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pytest_gremlins.operators.protocol import GremlinOperator

_OWN_DISTRIBUTION = 'pytest-gremlins'
_OWN_PACKAGE = 'pytest_gremlins'

# A distribution with unreadable or malformed metadata is skipped; it must never break pytest_configure.
# UnicodeDecodeError and json.JSONDecodeError are ValueErrors; importlib.metadata raises TypeError for a RECORD row
# with too many fields; csv.Error is a RECORD field over the csv size limit. Shape problems in direct_url.json are
# checked explicitly in _editable_project_directory, so a bad editable marker never costs a distribution its label.
_UNREADABLE_METADATA = (OSError, ValueError, TypeError, csv.Error)

# Raise this on any change that could alter a verdict, or which gremlins exist, for the same source and tests.
# tests/cache/test_cache_version_guard.py fails until you decide. It guards every .py file in the package except a
# reviewed exclusion list, so a new file is covered without editing a list. CACHE_VERSION covers what gets mutated;
# RUNNER_FIDELITY_VERSION in incremental.py covers test execution and outcome-to-verdict mapping.
CACHE_VERSION = 1

_LOCAL_OPERATOR_PREFIX = 'local-operator='
_UNREADABLE_MARKER = ':unreadable-'
_CONFTEST_OPERATORS_PREFIX = 'conftest-operators='
_CONFTEST_FILE_NAME = 'conftest.py'


def _metadata_field(dist: Distribution, field: str) -> str | None:
    values = dist.metadata.get_all(field)
    return values[0] if values else None


def _distribution_label(dist: Distribution) -> str:
    """Name a distribution without touching ``dist.name``, which warns on metadata lacking a Name field."""
    location = getattr(dist, '_path', None)
    name = _metadata_field(dist, 'Name') or (location.name if location is not None else '<unknown>')
    version = _metadata_field(dist, 'Version') or '<unknown>'
    return f'{name}=={version}'


def _normalized(name: str) -> str:
    """Return a distribution name in PEP 503 canonical form, so ``Foo_Bar`` and ``foo-bar`` compare equal."""
    return re.sub(r'[-_.]+', '-', name).lower()


def _is_own_distribution(dist: Distribution) -> bool:
    name = _metadata_field(dist, 'Name')
    return name is not None and _normalized(name) == _OWN_DISTRIBUTION


def _is_editable_stub(name: str) -> bool:
    """Whether a top-level RECORD entry is a PEP 660 ``.pth`` or ``__editable__`` finder file, not a module."""
    return name.endswith('.pth') or name.startswith('__editable__')


def _top_level_modules_from_record(files: Iterable[PackagePath]) -> set[str]:
    modules: set[str] = set()
    for file in files:
        root = file.parts[0] if file.parts else ''
        if _is_editable_stub(root):
            continue
        modules.add(root.split('.')[0] if len(file.parts) == 1 else root)
    return modules


class _InstallRecord:
    """A distribution's install record (``RECORD`` or ``installed-files.txt``), read at most once.

    ``SOURCES.txt`` of a source checkout's ``.egg-info`` is not an install record, so it never counts. An empty or
    blank record is no install record either: ``Distribution.files`` would fall back to ``SOURCES.txt`` for it.
    """

    def __init__(self, dist: Distribution) -> None:
        self._dist = dist

    @cached_property
    def files(self) -> tuple[PackagePath, ...]:
        record = self._dist.read_text('RECORD')
        if record is not None and record.strip():
            return tuple(PackagePath(row[0]) for row in csv.reader(record.splitlines()) if row)
        installed_files = self._dist.read_text('installed-files.txt')
        if installed_files is None or not installed_files.strip():
            return ()
        return self._installed_files_entries(installed_files)

    def _installed_files_entries(self, installed_files: str) -> tuple[PackagePath, ...]:
        """Parse ``installed-files.txt``: each line is relative to the ``.egg-info`` directory that holds it."""
        egg_info = getattr(self._dist, '_path', None)
        if egg_info is None:
            return ()
        return tuple(
            PackagePath(posixpath.join(Path(str(egg_info)).name, line))
            for line in installed_files.splitlines()
            if line.strip()
        )

    @cached_property
    def paths(self) -> frozenset[Path]:
        """The resolved location of every listed file; empty when the record cannot be read."""
        try:
            files = self.files
        except _UNREADABLE_METADATA:
            return frozenset()
        return frozenset(path for file in files if (path := self._resolved(file)) is not None)

    def _resolved(self, file: PackagePath) -> Path | None:
        """Resolve one listed file; ``None`` when its location is unreadable or loops (``RuntimeError`` before 3.13)."""
        try:
            return Path(str(self._dist.locate_file(file))).resolve()
        except (*_UNREADABLE_METADATA, RuntimeError):
            return None


def _declared_modules(dist: Distribution, record: _InstallRecord) -> set[str]:
    """Return the top-level modules a distribution installs, from ``top_level.txt`` else from its install record."""
    top_level = dist.read_text('top_level.txt')
    if top_level is not None:
        return set(top_level.split())
    return _top_level_modules_from_record(record.files)


def _editable_project_directory(dist: Distribution) -> Path | None:
    """Return the project directory of a PEP 610 editable install (``direct_url.json``), if it is one.

    PEP 610 makes ``dir_info.editable`` default to false, so a local directory install without the key, a VCS
    install and an archive install are all non-editable. A malformed file is treated as non-editable too.
    """
    try:
        raw = dist.read_text('direct_url.json')
        direct_url = json.loads(raw) if raw is not None else None
        if not isinstance(direct_url, dict):
            return None
        dir_info = direct_url.get('dir_info')
        url = direct_url.get('url')
        if not isinstance(dir_info, dict) or dir_info.get('editable') is not True or not isinstance(url, str):
            return None
        return Path(url2pathname(urlparse(url).path)).resolve()
    except (*_UNREADABLE_METADATA, RecursionError):
        return None


@dataclass(frozen=True)
class _IndexedDistribution:
    """What the owner lookup needs to know about one installed distribution."""

    label: str
    root: Path
    modules: frozenset[str]
    editable_project: Path | None
    record: _InstallRecord


def _index_distribution(dist: Distribution) -> _IndexedDistribution | None:
    """Read a distribution's metadata once; pytest-gremlins and any with unreadable metadata are skipped."""
    try:
        if _is_own_distribution(dist):
            return None
        record = _InstallRecord(dist)
        editable_project = _editable_project_directory(dist)
        modules = _declared_modules(dist, record)
        return _IndexedDistribution(
            label=_distribution_label(dist),
            root=Path(str(dist.locate_file(''))).resolve(),
            modules=frozenset(modules),
            editable_project=editable_project,
            record=record,
        )
    except _UNREADABLE_METADATA:
        return None


def _index_distributions() -> list[_IndexedDistribution]:
    """Index every installed distribution except pytest-gremlins, reading each one's metadata exactly once."""
    indexed = (_index_distribution(dist) for dist in distributions())
    return [entry for entry in indexed if entry is not None]


def _site_directories() -> list[Path]:
    paths = sysconfig.get_paths()
    return [Path(paths[key]).resolve() for key in ('purelib', 'platlib') if key in paths]


def _is_project_local(location: Path, project_root: Path | None) -> bool:
    """Whether ``location`` is project code: under the pytest rootdir and not in an installed-packages directory."""
    if project_root is None:
        return False
    roots = (project_root, project_root.resolve())
    if not any(location.is_relative_to(root) for root in roots):
        return False
    sites = _site_directories()
    return not any(location.is_relative_to(site) for site in sites)


def _is_installed_module_file(entry: _IndexedDistribution, top_level: str, location: Path) -> bool:
    """Whether ``location`` is a file the distribution installed: in the ``top_level`` module and its install record."""
    if top_level not in entry.modules or not location.is_relative_to(entry.root):
        return False
    if location.relative_to(entry.root).parts[0].partition('.')[0] != top_level:
        return False
    return location in entry.record.paths


def _is_editable_owner(entry: _IndexedDistribution, top_level: str, location: Path) -> bool:
    """Whether a PEP 610 editable install (``direct_url.json`` with ``dir_info.editable``) put ``location`` on the path.

    The module's top-level name must also belong to the distribution, so a helper elsewhere under the editable
    project directory (a monorepo's ``tools/``) is not claimed. A PEP 660 editable lists a ``.pth`` or finder
    file in its RECORD instead of the package, so those entries are ignored when reading the declared modules.
    An editable without a ``top_level.txt`` (hatchling, uv_build, flit, pdm) declares no names and owns nothing:
    its ``.pth`` directory may hold children the wheel does not ship, and no metadata says which do.

    Editable installs recorded only through a ``.pth`` file, or through a setuptools import finder, leave no
    ``direct_url.json`` marker and are not recognized.
    """
    return (
        entry.editable_project is not None
        and location.is_relative_to(entry.editable_project)
        and top_level in entry.modules
    )


def _is_importable(operator_class: type) -> bool:
    """Whether walking the class's qualified name from its module returns this exact class object.

    A module registered under a colliding name (a stdlib or installed module's name), a namespace package, a class
    nested in a function, and a class a module merely re-exports under another name all fail.
    """
    found: object = sys.modules.get(operator_class.__module__)
    for part in operator_class.__qualname__.split('.'):
        if part == '<locals>':
            return False
        found = getattr(found, part, None)
    return found is operator_class


def _module_file(operator_class: type) -> Path | None:
    origin = getattr(sys.modules.get(operator_class.__module__), '__file__', None)
    return Path(origin).resolve() if origin is not None else None


def _installed_owner_labels(
    operator_class: type, installed: list[_IndexedDistribution], project_root: Path | None
) -> set[str]:
    """Label the installed distributions that own an importable operator class; empty when none is proven."""
    location = _module_file(operator_class)
    if location is None or _is_project_local(location, project_root):
        return set()
    top_level = operator_class.__module__.partition('.')[0]
    declared = {entry.label for entry in installed if _is_installed_module_file(entry, top_level, location)}
    return declared or {entry.label for entry in installed if _is_editable_owner(entry, top_level, location)}


def _is_own_operator(operator_class: type) -> bool:
    return operator_class.__module__.partition('.')[0] == _OWN_PACKAGE


def _has_conftest_module_name(operator_class: type) -> bool:
    module_name = operator_class.__module__
    return module_name == 'conftest' or module_name.endswith('.conftest')


def _member_code_file(member: object) -> str | None:
    """The file a function, ``staticmethod``, ``classmethod`` or ``property`` in a class body was compiled from.

    A ``functools.wraps`` decorator is looked through, so the file named is the decorated function's.
    """
    function = getattr(member, '__func__', None) or getattr(member, 'fget', None) or member
    function = inspect.unwrap(function) if callable(function) else function
    code = getattr(function, '__code__', None)
    return code.co_filename if code is not None else None


def _conftest_function_files(operator_class: type) -> list[Path]:
    files = (_member_code_file(member) for member in vars(operator_class).values())
    return [Path(file) for file in files if file is not None and Path(file).name == _CONFTEST_FILE_NAME]


def _resolved(paths: Iterable[Path]) -> set[Path]:
    return {path.resolve() for path in paths}


def _is_module_defined_in(operator_class: type, loaded: set[Path]) -> bool:
    """Whether the class's module is named like a conftest and its file is one of the loaded conftests."""
    module_file = _module_file(operator_class)
    return _has_conftest_module_name(operator_class) and module_file is not None and module_file in loaded


def _is_conftest_defined(operator_class: type, loaded: set[Path]) -> bool:
    """Whether the class is defined in a loaded ``conftest.py``, or a function in its body comes from one (#899).

    The module name and the functions' ``co_filename`` only nominate candidates: an operator from an installed
    package whose module happens to be called ``conftest`` is not a conftest operator, so the file must be one
    of the conftests registered as plugins.
    """
    return _is_module_defined_in(operator_class, loaded) or bool(
        _resolved(_conftest_function_files(operator_class)) & loaded
    )


def _conftest_name(conftest: Path, project_root: Path | None) -> str:
    resolved = conftest.resolve()
    if project_root is not None and resolved.is_relative_to(project_root.resolve()):
        return resolved.relative_to(project_root.resolve()).as_posix()
    return resolved.as_posix()


def _relative_import_candidates(importer: Path, node: ast.ImportFrom) -> list[Path]:
    base = importer.parent
    for _ in range(node.level - 1):
        base = base.parent
    stem = base.joinpath(*node.module.split('.')) if node.module else base
    names = [alias.name for alias in node.names]
    paths = [stem.with_suffix('.py'), stem / '__init__.py'] if node.module else [stem / '__init__.py']
    paths += [path for name in names for path in (stem / f'{name}.py', stem / name / '__init__.py')]
    return [*paths, *_parent_package_inits(base, node.module)]


def _parent_package_inits(base: Path, dotted_module: str | None) -> list[Path]:
    """``from .sub.deep import z`` runs ``base/__init__.py`` and ``base/sub/__init__.py`` before ``sub/deep.py``."""
    parts = dotted_module.split('.') if dotted_module else []
    return [base.joinpath(*parts[:depth]) / '__init__.py' for depth in range(len(parts))]


def _dotted_prefixes(dotted_name: str) -> list[str]:
    """``pkg.sub.mod`` -> ``pkg``, ``pkg.sub``, ``pkg.sub.mod``: importing a module runs every parent package."""
    parts = dotted_name.split('.')
    return ['.'.join(parts[: end + 1]) for end in range(len(parts))]


def _absolute_import_module_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [prefix for alias in node.names for prefix in _dotted_prefixes(alias.name)]
    module = node.module or ''
    return [*_dotted_prefixes(module), *(f'{module}.{alias.name}' for alias in node.names)]


def _imported_files(importer: Path, tree: ast.AST) -> set[Path]:
    """The files of the modules ``tree`` imports statically; an absolute import never loaded names no file."""
    files: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            files |= {path for path in _relative_import_candidates(importer, node) if path.is_file()}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            origins = (getattr(sys.modules.get(name), '__file__', None) for name in _absolute_import_module_names(node))
            files |= {Path(origin) for origin in origins if origin is not None}
    return {file for file in files if file.suffix == '.py'}


def _local_modules_imported_by(conftests: Iterable[Path], project_root: Path | None) -> set[Path]:
    """Every project-local ``.py`` module the conftests import, followed transitively (#924).

    Raises:
        OSError: A module in the chain cannot be read.
        SyntaxError: A module in the chain cannot be parsed.
        MemoryError: A module in the chain is too deeply nested for the parser.
        RecursionError: A module in the chain is too deeply nested for the compiler.
        RuntimeError: A module path loops through symlinks (``Path.resolve`` before Python 3.13).
    """
    pending = [conftest.resolve() for conftest in conftests]
    seen = set(pending)
    local: set[Path] = set()
    while pending:
        importer = pending.pop()
        tree = ast.parse(importer.read_bytes(), filename=str(importer))
        for imported in _imported_files(importer, tree):
            if imported.resolve() in seen or not _is_project_local(imported, project_root):
                continue
            seen.add(imported.resolve())
            local.add(imported)
            pending.append(imported)
    return local


def _conftest_operators_label(loaded_conftests: Iterable[Path], project_root: Path | None) -> str | None:
    """Label the content of every loaded ``conftest.py`` and the local modules they import; ``None`` if unreadable.

    The test key hashes only the conftests on the path from the rootdir to a covering test, so an operator in
    ``a/conftest.py`` never reaches the key of a gremlin covered only by tests under ``b/`` (#899). Which
    conftest defines the operator is not worked out: its code can come from another conftest, a decorator or a
    base class. Hashing them all makes an edit to any loaded conftest a miss for every gremlin.

    A module a conftest imports (a helper beside it, or in another directory) can supply the operator's behavior
    without being registered as a plugin, so the project-local modules the conftests import, transitively, are
    hashed too (#924). Modules outside the rootdir and installed packages are not: installed operators are keyed
    by version. A conftest with no local import yields the same label as before.
    """
    hasher = ContentHasher()
    conftests = list(loaded_conftests)
    try:
        modules = {*conftests, *_local_modules_imported_by(conftests, project_root)}
        entries = sorted({(_conftest_name(module, project_root), hasher.hash_file(module)) for module in modules})
    except (OSError, SyntaxError, ValueError, MemoryError, RecursionError, RuntimeError):
        return None
    return f'{_CONFTEST_OPERATORS_PREFIX}{hasher.hash_string("|".join(f"{name}:{digest}" for name, digest in entries))}'


@dataclass(frozen=True)
class _SupplierLabels:
    """The operator supplier labels, and whether any of them is an always-miss token."""

    labels: set[str]
    has_always_miss_token: bool


def _operator_supplier_labels(
    operators: Iterable[GremlinOperator],
    project_root: Path | None,
    loaded_conftests: Iterable[Path] = (),
) -> _SupplierLabels:
    """Label each operator by the installed distribution that provably owns it, else by an always-miss token.

    An operator class keeps a stable key only when it is importable (see ``_is_importable``) and an installed
    distribution owns its module's file. Any other operator contributes ``local-operator=<module>:unreadable-<random>``,
    which differs on every run, so its verdicts are recomputed and never served stale. A helper's file is never
    hashed: what it defines can come from other files, so no hash proves the class unchanged. Restoring cache
    hits for such operators is tracked in #887.

    An operator defined in a ``conftest.py`` (see ``_is_conftest_defined``) adds one label hashing every loaded
    ``conftest.py`` (#899). A class whose module is a loaded conftest is covered by that label alone, unless an
    installed distribution owns that conftest (a plugin registered with ``-p pkg.conftest``): its version label is
    kept too, since the package can change outside ``conftest.py``. A class that merely borrows a conftest function
    is still classified by its own module as well.
    """
    classes_in_use = {type(operator) for operator in operators if not _is_own_operator(type(operator))}
    loaded_conftests = list(loaded_conftests)
    loaded = _resolved(loaded_conftests)
    conftest_defined = {cls for cls in classes_in_use if _is_conftest_defined(cls, loaded)}
    classes = {cls for cls in classes_in_use if not _is_module_defined_in(cls, loaded)}
    importable = {cls for cls in classes if _is_importable(cls)}
    installed = _index_distributions() if importable or conftest_defined else []
    labels: set[str] = set()
    unproven = classes - importable
    if conftest_defined:
        conftest_label = _conftest_operators_label(loaded_conftests, project_root)
        if conftest_label is None:
            unproven.add(min(conftest_defined, key=lambda cls: cls.__module__))
        else:
            labels.add(conftest_label)
        for conftest_class in conftest_defined:
            if _is_importable(conftest_class):
                labels |= _installed_owner_labels(conftest_class, installed, project_root)
    for operator_class in importable:
        owners = _installed_owner_labels(operator_class, installed, project_root)
        labels |= owners
        if not owners:
            unproven.add(operator_class)
    always_miss_tokens = {
        f'{_LOCAL_OPERATOR_PREFIX}{cls.__module__}{_UNREADABLE_MARKER}{uuid.uuid4().hex}' for cls in unproven
    }
    return _SupplierLabels(labels | always_miss_tokens, has_always_miss_token=bool(always_miss_tokens))


@dataclass(frozen=True)
class VersionsFingerprint:
    """The versions part of the cache key, and whether a later run can read what this run writes under it.

    Attributes:
        text: The fingerprint string; see ``installed_versions_fingerprint``.
        writes_are_readable: False when an operator no installed distribution provably owns put a fresh random
            token in ``text``, so no later run can read a result cached under it.
    """

    text: str
    writes_are_readable: bool


def versions_fingerprint(
    operators: Iterable[GremlinOperator] = (),
    project_root: Path | None = None,
    loaded_conftests: Iterable[Path] = (),
) -> VersionsFingerprint:
    """Return the fingerprint of ``installed_versions_fingerprint`` together with whether writes under it are readable.

    Readability is reported by the code that builds the labels, never re-parsed from the string, so an operator
    module whose name contains the ``|`` separator is still recognized.

    Args:
        operators: The operators registered for this run.
        project_root: The pytest rootdir.
        loaded_conftests: The ``conftest.py`` files the session has loaded; hashed into one label when an
            operator is defined in a conftest (#899).

    Returns:
        The fingerprint and its readability.

    Example:
        >>> versions_fingerprint().writes_are_readable
        True
    """
    suppliers = {
        _distribution_label(entry_point.dist)
        for entry_point in entry_points(group=ENTRY_POINT_GROUP)
        if entry_point.dist is not None
    }
    operator_suppliers = _operator_supplier_labels(operators, project_root, loaded_conftests)
    suppliers |= operator_suppliers.labels
    return VersionsFingerprint(
        text='|'.join([f'cache-version={CACHE_VERSION}', *sorted(suppliers)]),
        writes_are_readable=not operator_suppliers.has_always_miss_token,
    )


def installed_versions_fingerprint(
    operators: Iterable[GremlinOperator] = (),
    project_root: Path | None = None,
    loaded_conftests: Iterable[Path] = (),
) -> str:
    """Return a string naming the cache version and each distribution that supplies operators.

    A distribution counts when it provides a ``pytest_gremlins.operators`` entry point, or when it owns the module
    of an operator in ``operators`` (the operators registered for the run, including those a ``conftest.py``
    registers). pytest-gremlins' own operators never add its version.

    Args:
        operators: The operators registered for this run.
        project_root: The pytest rootdir. An operator module under it is project code, not an installed
            distribution. An operator keeps a stable key only when it is importable by its qualified name and an
            installed distribution owns its module; every other operator, a ``conftest.py`` operator excepted,
            makes every run miss the cache (#887 tracks restoring hits).
        loaded_conftests: The ``conftest.py`` files the session has loaded. When an operator is defined in a
            conftest, their paths (rootdir-relative, or absolute outside the rootdir) and contents are hashed
            into one ``conftest-operators=`` label, so an edit to any of them misses for every gremlin (#899).

    Raising ``CACHE_VERSION`` or any upgrade, downgrade, install or removal of an operator distribution
    changes the string, so verdicts cached under an older string are never reused. A pytest-gremlins
    release that leaves ``CACHE_VERSION`` alone keeps the cache. Old entries stop matching rather than
    one operator's verdicts being retired: the cache key does not record which operator produced a gremlin.

    Returns:
        A deterministic fingerprint, independent of entry-point discovery order.
    """
    return versions_fingerprint(operators, project_root, loaded_conftests).text
