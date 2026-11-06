"""Kill a hung pool worker together with everything it started (#976).

A worker that hangs can still own a test command, and that command can own more processes. Ending only the
worker would leave them running, so the whole tree goes: the descendants are listed first (they are reparented
the moment their parent dies), then their process groups and every process are killed. A process that starts
its own session escapes, and so does one that left the command's group after its parent died.
"""

from __future__ import annotations

from collections.abc import Iterable
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
    """SIGKILL ``root_pid``, its descendants and their process groups (``taskkill /T /F`` on Windows)."""
    kill_process_trees([root_pid])


def kill_process_trees(root_pids: Iterable[int]) -> None:
    """Kill several process trees, listing every tree before any process is killed.

    Killing one pool worker breaks the executor, whose manager then terminates the other workers. A worker that
    dies that way is no longer the parent of its test command, so the command can be found only if the trees
    were listed first.
    """
    roots = list(root_pids)
    if _IS_WINDOWS:
        for root_pid in roots:
            _taskkill_tree(root_pid)
        return
    descendants_by_root = {root_pid: descendants_of(root_pid) for root_pid in roots}
    process_groups: set[int] = set()
    for root_pid, descendants in descendants_by_root.items():
        process_groups |= _groups_to_signal(root_pid, descendants)
    for group in process_groups:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(group, signal.SIGKILL)
    for root_pid, descendants in descendants_by_root.items():
        for pid in [*descendants, root_pid]:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)


def _groups_to_signal(root_pid: int, descendants: list[int]) -> set[int]:
    """Return the process groups of the descendants, which also hold members whose parent died first.

    A test command that runs in its own process group (see #975) can leave a grandchild that outlives its
    parent: the parent links no longer reach it, but it is still in the command's group. Signalling that group
    ends it. The group of this process and the worker's own group are never signalled, so a descendant that
    shares them cannot take the parent run down.
    """
    own_groups = {os.getpgrp(), _group_of(root_pid)}
    return {group for pid in descendants if (group := _group_of(pid)) not in own_groups}


def _group_of(pid: int) -> int:
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return os.getpgrp()


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
    """Read the parent links ``ps`` prints, using its output even when it exits non-zero.

    ``ps`` exits with 1 when a process ends while it lists, which happens on a busy machine; the rest of the
    listing is still good, and discarding it would leave the worker's test command running.
    """
    for ps_command in (PS_COMMAND, FIXED_PATH_PS_COMMAND):
        try:
            listing = subprocess.run(  # Intentional: lists the process table
                [ps_command, '-A', '-o', 'pid=,ppid='],
                capture_output=True,
                text=True,
                timeout=_PS_TIMEOUT_SECONDS,
                check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        links = []
        for line in listing.splitlines():
            columns = line.split()
            if len(columns) == _PS_COLUMNS and all(column.isdigit() for column in columns):
                links.append((int(columns[0]), int(columns[1])))
        if links:
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
            stat_line = (entry / 'stat').read_bytes()
        except OSError:
            continue
        # "pid (comm) state ppid ...": comm is any bytes, even spaces, parentheses and non-UTF-8, so split after the
        # last ")" and decode only the numeric fields.
        fields_after_comm = stat_line.rpartition(b')')[2].split()
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
