"""Fingerprint of the installed code that decides what a cached verdict means."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import (
    Distribution,
    distributions,
    entry_points,
)
import importlib.util
import json
from pathlib import Path
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


def _module_location(top_level_module: str) -> Path | None:
    """Return the file (or package directory) a top-level module was loaded from, if it has one."""
    loaded = sys.modules.get(top_level_module)
    origin = getattr(loaded, '__file__', None)
    if origin is None:
        try:
            spec = importlib.util.find_spec(top_level_module)
        except (ImportError, ValueError):
            return None
        origin = spec.origin if spec is not None else None
    if origin is None or not Path(origin).is_absolute():
        return None
    return Path(origin).resolve()


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
    modules: frozenset[str]
    editable_project: Path | None


def _index_distribution(dist: Distribution) -> _IndexedDistribution | None:
    """Read a distribution's metadata once; pytest-gremlins and any with unreadable metadata are skipped."""
    try:
        if _is_own_distribution(dist):
            return None
        return _IndexedDistribution(
            label=_distribution_label(dist),
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


def _is_editable_owner(entry: _IndexedDistribution, location: Path) -> bool:
    """Whether a PEP 610 editable install (``direct_url.json`` with ``dir_info.editable``) put ``location`` on the path.

    Editable installs recorded only through a ``.pth`` file, or through a setuptools import finder, leave no
    ``direct_url.json`` marker and are not recognized.
    """
    return entry.editable_project is not None and location.is_relative_to(entry.editable_project)


def _operator_owner_labels(operators: Iterable[GremlinOperator], project_root: Path | None) -> set[str]:
    """Label the installed distributions that own the modules of the given operators.

    pytest-gremlins itself is skipped: its version is deliberately covered by ``CACHE_VERSION`` instead.
    An operator whose module is project-local (under ``project_root``) or in no installed distribution
    contributes nothing.
    """
    candidates = {
        type(operator).__module__.partition('.')[0]
        for operator in operators
        if type(operator).__module__.partition('.')[0] != 'pytest_gremlins'
    }
    locations = {module: _module_location(module) for module in candidates}
    wanted = {
        module
        for module, location in locations.items()
        if location is None or not _is_project_local(location, project_root)
    }
    if not wanted:
        return set()
    installed = _index_distributions()
    labels: set[str] = set()
    unowned = set(wanted)
    for entry in installed:
        owned = entry.modules & wanted
        if owned:
            labels.add(entry.label)
            unowned -= owned
    for module in unowned:
        location = locations[module]
        if location is not None:
            labels |= {entry.label for entry in installed if _is_editable_owner(entry, location)}
    return labels


def _class_source_file(operator_class: type) -> str | None:
    """Return the file of a class's first plain method, for a module that is not in ``sys.modules``.

    A conftest that loads its helper with ``spec_from_file_location`` never registers it, and ``inspect`` can
    only find a class's file through ``sys.modules``. A method's code object always records its file.
    """
    for member in vars(operator_class).values():
        code = getattr(member, '__code__', None)
        if code is not None:
            return str(code.co_filename)
    return None


def _local_helper_file(operator: GremlinOperator, project_root: Path | None) -> Path | None:
    """Return the file of a project-local helper module that defines ``operator``, or None if it needs no hash.

    Built-in operators, operators from installed distributions (outside ``project_root`` or in site-packages) and
    operators defined in a ``conftest.py`` return None: the first two are covered by ``CACHE_VERSION`` and the
    distribution label, and conftest files are already hashed with the tests they cover.
    """
    module_name = type(operator).__module__
    if module_name.partition('.')[0] == 'pytest_gremlins':
        return None
    origin = getattr(sys.modules.get(module_name), '__file__', None) or _class_source_file(type(operator))
    if origin is None:
        return Path(f'<no-file:{module_name}>')
    location = Path(origin).resolve()
    if location.name == 'conftest.py' or not _is_project_local(location, project_root):
        return None
    return location


def _local_helper_fingerprints(operators: Iterable[GremlinOperator], project_root: Path | None) -> set[str]:
    """Return ``local-operator=<path>:<hash>`` entries for operators defined in project-local helper modules.

    Only the helper file's own content is hashed; modules it imports are not tracked. A helper whose file cannot
    be found or read gets a fresh random token, so the key never matches and its verdicts are recomputed.
    """
    if project_root is None:
        return set()
    hasher = ContentHasher()
    entries: set[str] = set()
    for operator in operators:
        helper = _local_helper_file(operator, project_root)
        if helper is None:
            continue
        try:
            relative = helper.relative_to(project_root.resolve()).as_posix()
            entries.add(f'local-operator={relative}:{hasher.hash_file(helper)}')
        except (OSError, ValueError):
            entries.add(f'local-operator={type(operator).__module__}:unreadable-{uuid.uuid4().hex}')
    return entries


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
        project_root: The pytest rootdir. An operator module under it is project code and adds nothing, even
            when the project under test is itself installed editable.

    Raising ``CACHE_VERSION`` or any upgrade, downgrade, install or removal of an operator distribution
    changes the string, so verdicts cached under an older string are never reused. A pytest-gremlins
    release that leaves ``CACHE_VERSION`` alone keeps the cache. Old entries stop matching rather than
    one operator's verdicts being retired: the cache key does not record which operator produced a gremlin.

    Returns:
        A deterministic fingerprint, independent of entry-point discovery order.
    """
    suppliers = {
        _distribution_label(entry_point.dist)
        for entry_point in entry_points(group=ENTRY_POINT_GROUP)
        if entry_point.dist is not None
    }
    suppliers |= _operator_owner_labels(operators, project_root)
    suppliers |= _local_helper_fingerprints(operators, project_root)
    return '|'.join([f'cache-version={CACHE_VERSION}', *sorted(suppliers)])
