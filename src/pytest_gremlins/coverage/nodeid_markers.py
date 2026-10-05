"""Single rule for removing plugin size markers from pytest node IDs.

Plugins like ``pytest-test-categories`` append a display-only marker such as
`` [SMALL]`` to node IDs.  The main gremlins session, the coverage subprocess
and the selection explainer must all strip exactly the same suffix, otherwise
the coverage contexts and the node IDs they are matched against drift apart.

This module is deliberately import-light because the coverage subprocess loads it.

Example:
    >>> strip_marker_suffix('test_module.py::test_add [SMALL]')
    'test_module.py::test_add'
"""

from __future__ import annotations

import re

_MARKER_SUFFIX = re.compile(r'\s+\[[A-Z]+\]\s*$')


def strip_marker_suffix(nodeid: str) -> str:
    """Remove a trailing `` [UPPERCASE]`` marker from a node ID.

    Only a marker at the very end is a plugin decoration.  A `` [`` inside a
    parametrize id (``test_x[x [y]]``) is part of the node ID and is kept.

    Example:
        >>> strip_marker_suffix('test_module.py::test_add[x [y]] [SMALL]')
        'test_module.py::test_add[x [y]]'
        >>> strip_marker_suffix('test_module.py::test_add[GET]')
        'test_module.py::test_add[GET]'
    """
    return _MARKER_SUFFIX.sub('', nodeid)
