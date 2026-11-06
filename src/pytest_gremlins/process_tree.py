"""Run a test command so that a timeout ends the whole process tree, not only its first process (#975).

``subprocess.run(timeout=...)`` kills only the direct child. Anything that child started (a multiprocessing
pool, a server fixture, a ``subprocess`` call in a test) keeps running after every timeout, and on Windows it
also keeps the output pipes open, so the final ``communicate()`` of ``subprocess.run`` has no end.
:func:`run_bounded` puts the command in its own process group (a session on POSIX), kills the group on a
timeout or an interrupt, and bounds the wait for the pipes to drain.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import (
        Mapping,
        Sequence,
    )

TERMINATE_GRACE_SECONDS = 0.5
"""How long the group gets to exit after SIGTERM before SIGKILL (POSIX)."""

PIPE_DRAIN_SECONDS = 5.0
"""How long to wait for the output pipes to close after the kill."""

_TASKKILL_TIMEOUT_SECONDS = 10


def run_bounded(
    command: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``command`` with captured output, ending its whole process tree if it outlasts ``timeout``.

    Args:
        command: The command line to run.
        cwd: Working directory of the command.
        env: Environment of the command.
        timeout: Seconds the command may run.

    Returns:
        The completed process, with its captured stdout and stderr.

    Raises:
        subprocess.TimeoutExpired: If the command outlasted ``timeout``. Its process tree has been killed, and
            the output read before the kill is attached.
    """
    process = _start(command, cwd=cwd, env=env)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        try:
            _terminate_tree(process)
        finally:
            # An interrupt during the grace period still reaps the command and closes its pipes.
            stdout, stderr = _drain(process)
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from expired
    except BaseException:
        _kill_tree(process)
        _drain(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _start(command: Sequence[str], *, cwd: str, env: Mapping[str, str]) -> subprocess.Popen[bytes]:
    if sys.platform == 'win32':
        return subprocess.Popen(  # Intentional: runs pytest test commands
            command,
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(  # Intentional: runs pytest test commands
        command,
        cwd=cwd,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    """Ask the tree to exit, then force it; Windows has no polite signal for a group.

    The grace period ends as soon as the command exits, and the SIGKILL is sent even if the wait is interrupted.
    Reaping the command first is safe: its group id stays reserved while any member of the group is alive.
    """
    try:
        if sys.platform != 'win32':
            _signal_group(process, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
    finally:
        _kill_tree(process)


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == 'win32':
        _taskkill_tree(process)
    else:
        _signal_group(process, signal.SIGKILL)


def _signal_group(process: subprocess.Popen[bytes], signal_number: int) -> None:
    # The command is its own group leader (start_new_session), so its pid is the group id.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal_number)


def _taskkill_path() -> str:
    system_root = os.environ.get('SystemRoot', r'C:\Windows')  # noqa: SIM112 - the name Windows defines
    return str(Path(system_root) / 'System32' / 'taskkill.exe')


def _taskkill_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        subprocess.run(  # Intentional: ends the process tree of a timed-out test run
            [_taskkill_path(), '/F', '/T', '/PID', str(process.pid)],
            capture_output=True,
            timeout=_TASKKILL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        process.kill()


def _drain(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    """Collect what the killed command wrote, giving up if something outside the tree still holds the pipes."""
    try:
        stdout, stderr = process.communicate(timeout=PIPE_DRAIN_SECONDS)
    except subprocess.TimeoutExpired as still_open:
        _abandon_pipes(process)
        return still_open.stdout or b'', still_open.stderr or b''
    return stdout, stderr


def _abandon_pipes(process: subprocess.Popen[bytes]) -> None:
    if sys.platform != 'win32':
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=PIPE_DRAIN_SECONDS)
