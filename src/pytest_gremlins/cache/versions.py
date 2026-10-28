"""Fingerprint of the installed code that decides what a cached verdict means."""

from __future__ import annotations

from importlib.metadata import entry_points

from pytest_gremlins.operators.entry_points import ENTRY_POINT_GROUP

# Raise this on any change that could alter a verdict for the same source and tests: operators,
# instrumentation, or how verdicts are decided. tests/cache/test_cache_version_guard.py fails until you do.
CACHE_VERSION = 1


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
        f'{entry_point.dist.name}=={entry_point.dist.version}'
        for entry_point in entry_points(group=ENTRY_POINT_GROUP)
        if entry_point.dist is not None
    }
    return '|'.join([f'cache-version={CACHE_VERSION}', *sorted(suppliers)])
