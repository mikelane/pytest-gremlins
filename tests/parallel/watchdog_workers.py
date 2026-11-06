"""Worker functions for the pool watchdog tests; module level so spawned workers can import them."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import GremlinResultStatus


def run_scripted(
    gremlin_id: str,
    test_command: list[str],
    rootdir: str,
    env_vars: dict[str, str],  # noqa: ARG001
    timeout: int,  # noqa: ARG001
) -> WorkerResult:
    """Sleep as ``test_command`` says (its first item is the seconds), outside subprocess.run.

    The worker writes its pid to ``<rootdir>/<gremlin_id>.pid`` first, so tests can check it is gone later.
    """
    Path(rootdir, f'{gremlin_id}.pid').write_text(str(os.getpid()))
    seconds = float(test_command[0])
    time.sleep(seconds)
    return WorkerResult(gremlin_id=gremlin_id, status=GremlinResultStatus.SURVIVED, execution_time_ms=seconds * 1000)


def run_with_test_command(
    gremlin_id: str,
    test_command: list[str],
    rootdir: str,
    env_vars: dict[str, str],  # noqa: ARG001
    timeout: int,  # noqa: ARG001
) -> WorkerResult:
    """Start a long-lived child (a stand-in test command), record its pid, sleep ``test_command[0]`` seconds.

    Each start writes ``<rootdir>/<gremlin_id>.<child pid>.child``, so a test can check that the command of every
    attempt, including one cut short by a rebuild, is gone after the run.
    """
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])
    Path(rootdir, f'{gremlin_id}.{child.pid}.child').write_text(str(child.pid))
    seconds = float(test_command[0])
    time.sleep(seconds)
    child.kill()
    child.wait()
    return WorkerResult(gremlin_id=gremlin_id, status=GremlinResultStatus.SURVIVED, execution_time_ms=seconds * 1000)
