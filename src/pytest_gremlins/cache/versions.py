"""Fingerprint of the installed code that decides what a cached verdict means."""

from __future__ import annotations

from importlib.metadata import entry_points

from pytest_gremlins import __version__
from pytest_gremlins.operators.entry_points import ENTRY_POINT_GROUP


def installed_versions_fingerprint() -> str:
    """Return a string naming the pytest-gremlins version and each operator entry-point distribution.

    A distribution counts when it provides a ``pytest_gremlins.operators`` entry point.

    Any upgrade, downgrade, install or removal changes the string, so verdicts cached under an older
    string are never reused. The whole cache is invalidated rather than one operator's verdicts: the
    cache key does not record which operator produced a gremlin.

    Returns:
        A deterministic fingerprint, independent of entry-point discovery order.
    """
    suppliers = {
        f'{entry_point.dist.name}=={entry_point.dist.version}'
        for entry_point in entry_points(group=ENTRY_POINT_GROUP)
        if entry_point.dist is not None
    }
    return '|'.join([f'pytest-gremlins=={__version__}', *sorted(suppliers)])
