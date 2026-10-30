"""Fingerprint of the installed code that decides what a cached verdict means."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import (
    Distribution,
    distributions,
    entry_points,
)
import json
from pathlib import Path
import re
import sys
import sysconfig
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.request import url2pathname
import uuid

from pytest_gremlins.operators.entry_points import ENTRY_POINT_GROUP

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pytest_gremlins.operators.protocol import GremlinOperator

_OWN_DISTRIBUTION = 'pytest-gremlins'
_OWN_PACKAGE = 'pytest_gremlins'

# A distribution with unreadable or malformed metadata is skipped; it must never break pytest_configure.
# UnicodeDecodeError and json.JSONDecodeError are ValueErrors; importlib.metadata raises TypeError for a RECORD row
# with too many fields. Shape problems in direct_url.json are checked
# explicitly in _editable_project_directory, so a bad editable marker never costs a distribution its label.
_UNREADABLE_METADATA = (OSError, ValueError, TypeError)

# Raise this on any change that could alter a verdict, or which gremlins exist, for the same source and tests.
# tests/cache/test_cache_version_guard.py fails until you decide. It guards every .py file in the package except a
# reviewed exclusion list, so a new file is covered without editing a list. CACHE_VERSION covers what gets mutated;
# RUNNER_FIDELITY_VERSION in incremental.py covers test execution and outcome-to-verdict mapping.
CACHE_VERSION = 1

_LOCAL_OPERATOR_PREFIX = 'local-operator='
_UNREADABLE_MARKER = ':unreadable-'


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


def _declared_top_level_modules(dist: Distribution) -> set[str]:
    """Return the top-level modules a distribution installs, from ``top_level.txt`` else its RECORD."""
    top_level = dist.read_text('top_level.txt')
    if top_level is not None:
        return set(top_level.split())
    modules: set[str] = set()
    for file in dist.files or ():
        root = file.parts[0] if file.parts else ''
        modules.add(root.split('.')[0] if len(file.parts) == 1 else root)
    return modules


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


def _index_distribution(dist: Distribution) -> _IndexedDistribution | None:
    """Read a distribution's metadata once; pytest-gremlins and any with unreadable metadata are skipped."""
    try:
        if _is_own_distribution(dist):
            return None
        return _IndexedDistribution(
            label=_distribution_label(dist),
            root=Path(str(dist.locate_file(''))).resolve(),
            modules=frozenset(_declared_top_level_modules(dist)),
            editable_project=_editable_project_directory(dist),
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
    if project_root is None or not location.is_relative_to(project_root.resolve()):
        return False
    return not any(location.is_relative_to(site) for site in _site_directories())


def _is_installed_module_file(entry: _IndexedDistribution, top_level: str, location: Path) -> bool:
    """Whether ``location`` is inside the ``top_level`` package or module the distribution installed."""
    if top_level not in entry.modules or not location.is_relative_to(entry.root):
        return False
    return location.relative_to(entry.root).parts[0].partition('.')[0] == top_level


def _is_editable_owner(entry: _IndexedDistribution, location: Path) -> bool:
    """Whether a PEP 610 editable install (``direct_url.json`` with ``dir_info.editable``) put ``location`` on the path.

    Editable installs recorded only through a ``.pth`` file, or through a setuptools import finder, leave no
    ``direct_url.json`` marker and are not recognized.
    """
    return entry.editable_project is not None and location.is_relative_to(entry.editable_project)


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
    return declared or {entry.label for entry in installed if _is_editable_owner(entry, location)}


def _is_exempt_from_classification(operator_class: type) -> bool:
    """pytest-gremlins' own operators are covered by ``CACHE_VERSION``; a conftest operator by the tests it covers."""
    module_file = _module_file(operator_class)
    return operator_class.__module__.partition('.')[0] == _OWN_PACKAGE or (
        module_file is not None and module_file.name == 'conftest.py'
    )


@dataclass(frozen=True)
class _SupplierLabels:
    """The operator supplier labels, and whether any of them is an always-miss token."""

    labels: set[str]
    has_always_miss_token: bool


def _operator_supplier_labels(operators: Iterable[GremlinOperator], project_root: Path | None) -> _SupplierLabels:
    """Label each operator by the installed distribution that provably owns it, else by an always-miss token.

    An operator class keeps a stable key only when it is importable (see ``_is_importable``) and an installed
    distribution owns its module's file. Any other operator contributes ``local-operator=<module>:unreadable-<random>``,
    which differs on every run, so its verdicts are recomputed and never served stale. A helper's file is never
    hashed: what it defines can come from other files, so no hash proves the class unchanged. Restoring cache
    hits for such operators is tracked in #887.
    """
    classes = {type(operator) for operator in operators if not _is_exempt_from_classification(type(operator))}
    importable = {cls for cls in classes if _is_importable(cls)}
    installed = _index_distributions() if importable else []
    labels: set[str] = set()
    unproven = classes - importable
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
) -> VersionsFingerprint:
    """Return the fingerprint of ``installed_versions_fingerprint`` together with whether writes under it are readable.

    Readability is reported by the code that builds the labels, never re-parsed from the string, so an operator
    module whose name contains the ``|`` separator is still recognized.

    Args:
        operators: The operators registered for this run.
        project_root: The pytest rootdir.

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
    operator_suppliers = _operator_supplier_labels(operators, project_root)
    suppliers |= operator_suppliers.labels
    return VersionsFingerprint(
        text='|'.join([f'cache-version={CACHE_VERSION}', *sorted(suppliers)]),
        writes_are_readable=not operator_suppliers.has_always_miss_token,
    )


def installed_versions_fingerprint(
    operators: Iterable[GremlinOperator] = (),
    project_root: Path | None = None,
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

    Raising ``CACHE_VERSION`` or any upgrade, downgrade, install or removal of an operator distribution
    changes the string, so verdicts cached under an older string are never reused. A pytest-gremlins
    release that leaves ``CACHE_VERSION`` alone keeps the cache. Old entries stop matching rather than
    one operator's verdicts being retired: the cache key does not record which operator produced a gremlin.

    Returns:
        A deterministic fingerprint, independent of entry-point discovery order.
    """
    return versions_fingerprint(operators, project_root).text
