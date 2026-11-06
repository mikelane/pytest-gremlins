"""Kill a hung pool worker together with everything it started (#976).

A worker that hangs can still own a test command, and that command can own more processes. Ending only the
worker would leave them running, so the whole tree goes: the descendants are listed first (they are reparented
the moment their parent dies), then every process is killed.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys

logger = logging.getLogger(__name__)

_PS_TIMEOUT_SECONDS = 10
_PS_COLUMNS = 2
PS_COMMAND = 'ps'
FIXED_PATH_PS_COMMAND = '/bin/ps'
PROC_ROOT = Path('/proc')
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
    """Return every descendant pid of ``root_pid`` (POSIX), found through the parent links of the process table."""
    children_by_parent = _children_by_parent()
    if children_by_parent is None:
        logger.warning('Cannot list the descendants of worker %s: no `ps` and no /proc', root_pid)
        return []
    found: list[int] = []
    frontier = [root_pid]
    while frontier:
        children = children_by_parent.get(frontier.pop(), [])
        found.extend(children)
        frontier.extend(children)
    return found


def _children_by_parent() -> dict[int, list[int]] | None:
    """Map each pid to its children, from ``ps`` or, where that is missing (slim container images), from /proc."""
    parent_links = _parent_links_from_ps() or _parent_links_from_proc()
    if parent_links is None:
        return None
    children_by_parent: dict[int, list[int]] = {}
    for pid, parent in parent_links:
        children_by_parent.setdefault(parent, []).append(pid)
    return children_by_parent


def _parent_links_from_ps() -> list[tuple[int, int]] | None:
    for ps_command in (PS_COMMAND, FIXED_PATH_PS_COMMAND):
        try:
            listing = subprocess.run(  # Intentional: lists the process table
                [ps_command, '-A', '-o', 'pid=,ppid='],
                capture_output=True,
                text=True,
                timeout=_PS_TIMEOUT_SECONDS,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        links = []
        for line in listing.splitlines():
            columns = line.split()
            if len(columns) == _PS_COLUMNS and all(column.isdigit() for column in columns):
                links.append((int(columns[0]), int(columns[1])))
        return links
    return None


def _parent_links_from_proc() -> list[tuple[int, int]] | None:
    if not PROC_ROOT.is_dir():
        return None
    links = []
    for entry in PROC_ROOT.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat_line = (entry / 'stat').read_text()
        except OSError:
            continue
        # "pid (comm) state ppid ...": comm may hold spaces and parentheses, so split after the last ")".
        fields_after_comm = stat_line.rpartition(')')[2].split()
        if len(fields_after_comm) > 1 and fields_after_comm[1].isdigit():
            links.append((int(entry.name), int(fields_after_comm[1])))
    return links


def _taskkill_tree(root_pid: int) -> None:
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(  # Intentional: ends a Windows process tree
            ['taskkill', '/PID', str(root_pid), '/T', '/F'],  # noqa: S607  # nosec B607
            capture_output=True,
            timeout=_PS_TIMEOUT_SECONDS,
            check=False,
        )
