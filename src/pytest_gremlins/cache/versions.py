"""Fingerprint of the installed code that decides what a cached verdict means."""

from __future__ import annotations

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
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from urllib.request import url2pathname

from pytest_gremlins.operators.entry_points import ENTRY_POINT_GROUP

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pytest_gremlins.operators.protocol import GremlinOperator

_OWN_DISTRIBUTION = 'pytest-gremlins'

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


def _pth_directories(dist: Distribution) -> set[Path]:
    """Return the directories the distribution's ``.pth`` files add to ``sys.path``."""
    directories: set[Path] = set()
    for file in dist.files or ():
        if file.suffix != '.pth':
            continue
        for line in file.read_text().splitlines():
            entry = line.strip()
            if entry and not entry.startswith(('#', 'import')):
                directories.add(Path(entry).resolve())
    return directories


def _editable_project_directory(dist: Distribution) -> Path | None:
    """Return the project directory of a PEP 610 editable install (``direct_url.json``), if it is one."""
    raw = dist.read_text('direct_url.json')
    if raw is None:
        return None
    try:
        direct_url = json.loads(raw)
        if not direct_url['dir_info']['editable']:
            return None
        return Path(url2pathname(urlparse(direct_url['url']).path)).resolve()
    except (ValueError, KeyError, TypeError):
        return None


def _is_editable_owner(dist: Distribution, location: Path) -> bool:
    """Whether an editable install of ``dist`` puts ``location`` on the import path.

    Recognizes ``.pth`` path entries and PEP 610 ``direct_url.json`` project directories. Editable installs that map
    modules through a setuptools import finder record neither, so they are not recognized.
    """
    project = _editable_project_directory(dist)
    if project is not None and location.is_relative_to(project):
        return True
    return location.parent in _pth_directories(dist)


def _operator_owner_labels(operators: Iterable[GremlinOperator]) -> set[str]:
    """Label the installed distributions that own the modules of the given operators.

    pytest-gremlins itself is skipped: its version is deliberately covered by ``CACHE_VERSION`` instead.
    An operator whose module is in no installed distribution (project-local code) contributes nothing.
    """
    wanted = {
        type(operator).__module__.partition('.')[0]
        for operator in operators
        if not type(operator).__module__.startswith('pytest_gremlins.')
    }
    if not wanted:
        return set()
    installed = [dist for dist in distributions() if not _is_own_distribution(dist)]
    labels: set[str] = set()
    unowned = set(wanted)
    for dist in installed:
        owned = _declared_top_level_modules(dist) & wanted
        if owned:
            labels.add(_distribution_label(dist))
            unowned -= owned
    for module in unowned:
        location = _module_location(module)
        if location is not None:
            labels |= {_distribution_label(dist) for dist in installed if _is_editable_owner(dist, location)}
    return labels


def installed_versions_fingerprint(operators: Iterable[GremlinOperator] = ()) -> str:
    """Return a string naming the cache version and each distribution that supplies operators.

    A distribution counts when it provides a ``pytest_gremlins.operators`` entry point, or when it owns the module
    of an operator in ``operators`` (the operators registered for the run, including those a ``conftest.py``
    registers). pytest-gremlins' own operators never add its version.

    Args:
        operators: The operators registered for this run.

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
    suppliers |= _operator_owner_labels(operators)
    return '|'.join([f'cache-version={CACHE_VERSION}', *sorted(suppliers)])
