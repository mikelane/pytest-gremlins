"""Fingerprint of the installed code that decides what a cached verdict means."""

from __future__ import annotations

from importlib.metadata import (
    Distribution,
    distribution,
    entry_points,
    packages_distributions,
)
import re
from typing import TYPE_CHECKING

from pytest_gremlins.operators.entry_points import ENTRY_POINT_GROUP

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pytest_gremlins.operators.protocol import GremlinOperator

OWN_DISTRIBUTION = 'pytest-gremlins'

# Raise this on any change that could alter a verdict, or which gremlins exist, for the same source and tests.
# tests/cache/test_cache_version_guard.py fails until you decide. It guards every .py file in the package except a
# reviewed exclusion list, so a new file is covered without editing a list. CACHE_VERSION covers what gets mutated;
# RUNNER_FIDELITY_VERSION in incremental.py covers test execution and outcome-to-verdict mapping.
CACHE_VERSION = 1


def _distribution_label(dist: Distribution) -> str:
    """Name a distribution without touching ``dist.name``, which warns on metadata lacking a Name field."""
    location = getattr(dist, '_path', None)
    names = dist.metadata.get_all('Name')
    versions = dist.metadata.get_all('Version')
    name = names[0] if names else (location.name if location is not None else '<unknown>')
    version = versions[0] if versions else '<unknown>'
    return f'{name}=={version}'


def _normalized(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def _operator_owner_labels(operators: Iterable[GremlinOperator]) -> set[str]:
    """Label the installed distributions that own the modules of the given operators.

    pytest-gremlins itself is skipped: its version is deliberately covered by ``CACHE_VERSION`` instead.
    An operator whose module is in no installed distribution (project-local code) contributes nothing.
    """
    top_level_modules = {
        type(operator).__module__.partition('.')[0]
        for operator in operators
        if not type(operator).__module__.startswith('pytest_gremlins.')
    }
    if not top_level_modules:
        return set()
    owners = packages_distributions()
    names = {name for module in top_level_modules for name in owners.get(module, [])}
    return {_distribution_label(distribution(name)) for name in names if _normalized(name) != OWN_DISTRIBUTION}


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
