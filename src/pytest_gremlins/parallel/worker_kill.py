"""Kill a hung pool worker together with everything it started (#976).

A worker that hangs can still own a test command, and that command can own more processes. Ending only the
worker would leave them running, so the whole tree goes: the descendants are listed first (they are reparented
the moment their parent dies), then every process is killed.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import sys

logger = logging.getLogger(__name__)

_PS_TIMEOUT_SECONDS = 10
_IS_WINDOWS = sys.platform == 'win32'


def kill_process_tree(root_pid: int) -> None:
    """SIGKILL ``root_pid`` and all of its descendants (``taskkill /T /F`` on Windows)."""
    if _IS_WINDOWS:
        _taskkill_tree(root_pid)
        return
    victims = [*descendants_of(root_pid), root_pid]
    for pid in victims:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)


def descendants_of(root_pid: int) -> list[int]:
    """Return every descendant pid of ``root_pid`` (POSIX), found through the parent links ``ps`` reports."""
    try:
        listing = subprocess.run(  # Intentional: lists the process table
            ['ps', '-A', '-o', 'pid=,ppid='],  # noqa: S607  # nosec B607
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT_SECONDS,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as ps_error:
        logger.warning('Cannot list the descendants of worker %s: %s', root_pid, ps_error)
        return []
    children_by_parent: dict[int, list[int]] = {}
    for line in listing.splitlines():
        columns = line.split()
        if len(columns) == 2 and all(column.isdigit() for column in columns):  # noqa: PLR2004
            children_by_parent.setdefault(int(columns[1]), []).append(int(columns[0]))
    found: list[int] = []
    frontier = [root_pid]
    while frontier:
        children = children_by_parent.get(frontier.pop(), [])
        found.extend(children)
        frontier.extend(children)
    return found


def _taskkill_tree(root_pid: int) -> None:
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(  # Intentional: ends a Windows process tree
            ['taskkill', '/PID', str(root_pid), '/T', '/F'],  # noqa: S607  # nosec B607
            capture_output=True,
            timeout=_PS_TIMEOUT_SECONDS,
            check=False,
        )
