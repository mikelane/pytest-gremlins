"""A killed parallel run keeps the results it finished, so the next run hits the cache (issue #974).

One gremlin makes the target spin forever, so the run can never finish by itself; the test kills it as soon
as other gremlins have reached the cache file, the way a CI timeout or an OOM kill would.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

WAIT_LIMIT_SECONDS = 180
POLL_SECONDS = 0.2

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
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as connection:
            return int(connection.execute('SELECT COUNT(*) FROM results').fetchone()[0])
    except sqlite3.Error:
        return 0


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    if process.stdout is not None:
        process.stdout.close()


def _wait_until(condition: object) -> None:
    deadline = time.monotonic() + WAIT_LIMIT_SECONDS
    while time.monotonic() < deadline:
        if condition():  # type: ignore[operator]
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

        assert rows_kept > 0
        assert hits == rows_kept


def _first_cache_hit_count(process: subprocess.Popen[bytes]) -> int:
    assert process.stdout is not None
    deadline = time.monotonic() + WAIT_LIMIT_SECONDS
    for raw_line in process.stdout:
        match = re.search(r'(\d+) gremlins from cache', raw_line.decode('utf-8', 'replace'))
        if match:
            return int(match.group(1))
        if time.monotonic() > deadline:
            break
    pytest.fail('the second run never reported its cache hits')
