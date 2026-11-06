"""A killed parallel run keeps the results it finished, so the next run hits the cache (issue #974).

One gremlin makes the target spin forever, so the run can never finish by itself; the test kills it as soon
as other gremlins have reached the cache file, the way a CI timeout or an OOM kill would.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
import os
from pathlib import Path
import re
import select
import signal
import sqlite3
import subprocess
import sys
import time

from process_helpers import (  # type: ignore[import-not-found]
    kill_quietly,
    wait_until_no_process_has_env_marker,
)
import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

WAIT_LIMIT_SECONDS = 180
# Every process a killed run started inherits this marker, so any that outlives the kill (a test command that was
# left spinning) shows up in the process list.
_RUN_MARKER_NAME = 'GREMLINS_974_RUN_MARKER'
_RUN_MARKER_VALUE = 'interrupted-run-leaves-nothing-behind'
POLL_SECONDS = 0.2
READ_CHUNK_BYTES = 4096

_CALC = """
def add(a, b):
    return a + b


def spin(n):
    while n > 0:
        n = n - 1
    return n
"""

_TESTS = """
from calc import add, spin


def test_add():
    assert add(2, 3) == 5


def test_spin():
    assert spin(3) == 0
"""

_ARGS = (
    '--gremlins',
    '--gremlin-targets=calc.py',
    '--gremlin-operators=arithmetic,comparison,boundary',
    '--gremlin-cache',
    '--gremlin-parallel',
    '--gremlin-workers=8',
    '--gremlin-mutant-timeout=600',
    '-p',
    'no:cacheprovider',
)


def _cached_row_count(project: Path) -> int:
    database = project / '.gremlins_cache' / 'results.db'
    if not database.exists():
        return 0
    try:
        with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as connection:
            return int(connection.execute('SELECT COUNT(*) FROM results').fetchone()[0])
    except sqlite3.Error:
        return 0


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    if process.stdout is not None:
        process.stdout.close()


def _wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_LIMIT_SECONDS
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(POLL_SECONDS)
    pytest.fail('the run did not reach the expected state in time')


@pytest.mark.medium
@pytest.mark.skipif(os.name == 'nt', reason='the test kills the run with a POSIX process group signal')
class DescribeKilledParallelRun:
    def it_keeps_finished_results_for_the_next_run(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONUNBUFFERED', '1')
        monkeypatch.setenv(_RUN_MARKER_NAME, _RUN_MARKER_VALUE)
        pytester_with_markers.makepyfile(calc=_CALC, test_calc=_TESTS)
        project = pytester_with_markers.path

        first_run = pytester_with_markers.popen(
            [sys.executable, '-m', 'pytest', *_ARGS],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            _wait_until(lambda: _cached_row_count(project) > 0)
        finally:
            _kill_group(first_run)
        rows_kept = _cached_row_count(project)

        second_run = pytester_with_markers.popen(
            [sys.executable, '-m', 'pytest', *_ARGS],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            hits = _first_cache_hit_count(second_run)
        finally:
            _kill_group(second_run)

        leftover = wait_until_no_process_has_env_marker(f'{_RUN_MARKER_NAME}={_RUN_MARKER_VALUE}')
        for pid in leftover:
            kill_quietly(pid)

        assert (rows_kept > 0, hits == rows_kept, leftover) == (True, True, [])


def _first_cache_hit_count(process: subprocess.Popen[bytes]) -> int:
    """Return the cache-hit count the run prints, failing at a hard deadline even if the run goes silent.

    Reads the pipe with ``select`` and ``os.read`` so a child that prints nothing cannot block past the
    deadline. The caller kills the child.
    """
    assert process.stdout is not None
    descriptor = process.stdout.fileno()
    deadline = time.monotonic() + WAIT_LIMIT_SECONDS
    collected = b''
    while (remaining := deadline - time.monotonic()) > 0:
        readable, _, _ = select.select([descriptor], [], [], remaining)
        chunk = os.read(descriptor, READ_CHUNK_BYTES) if readable else b''
        if not chunk:
            break
        collected += chunk
        match = re.search(rb'(\d+) gremlins from cache', collected)
        if match:
            return int(match.group(1))
    pytest.fail(f'the second run never reported its cache hits. Output so far:\n{collected.decode("utf-8", "replace")}')
