"""Fingerprint of the installed code that decides what a cached verdict means."""

from __future__ import annotations

from importlib.metadata import (
    Distribution,
    entry_points,
)

from pytest_gremlins.operators.entry_points import ENTRY_POINT_GROUP

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


def installed_versions_fingerprint() -> str:
    """Return a string naming the cache version and each operator entry-point distribution.

    A distribution counts when it provides a ``pytest_gremlins.operators`` entry point.

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
    return '|'.join([f'cache-version={CACHE_VERSION}', *sorted(suppliers)])
