"""Decide which collected tests the lightweight runner can judge faithfully.

The lightweight runner imports a test module and calls the test callable with
no arguments. That matches what pytest does only for a plain, synchronous,
fixture-free, unparametrized test. Anything else must go through the full
pytest bootstrap, so the runner is used only when every selected test passes
:func:`is_lightweight_safe`.
"""

from __future__ import annotations

import inspect

import pytest

MAX_NODE_ID_SEGMENTS = 3
"""``file::func`` and ``file::Class::method`` are the only shapes the runner resolves."""

_SKIP_SEMANTIC_MARKERS = ('skip', 'skipif', 'xfail')


def is_lightweight_safe(item: pytest.Item) -> bool:
    """Return whether the lightweight runner can run ``item`` as pytest would.

    ``fixturenames`` already includes autouse, conftest and xunit ``setup_*``
    fixtures, so an empty list means nothing runs around the bare call.

    Args:
        item: A collected pytest item.

    Returns:
        True only for a plain ``pytest.Function`` with no fixtures, no
        parametrization, no coroutine body, and no skip/xfail markers.
    """
    if type(item) is not pytest.Function:
        return False
    if len(item.nodeid.split('::')) > MAX_NODE_ID_SEGMENTS:
        return False
    if item.fixturenames or getattr(item, 'callspec', None) is not None:
        return False
    if inspect.iscoroutinefunction(item.obj) or inspect.isasyncgenfunction(item.obj):
        return False
    return not _has_skip_semantics(item)


def _has_skip_semantics(item: pytest.Item) -> bool:
    return any(item.get_closest_marker(name) is not None for name in _SKIP_SEMANTIC_MARKERS)
