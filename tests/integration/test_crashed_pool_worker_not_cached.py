"""A gremlin whose pool worker crashed is reported as ERROR but never cached (issue #981).

The project's test kills its parent process, the pool worker that launched it, the first time a gremlin runs, the
way an OOM kill would. The executor then fails the gremlins in flight with ``BrokenProcessPool``. Those ERRORs come
from the crash, not from running the gremlin's tests, so the next run must test the gremlins again.
"""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

import pytest

from tests.integration._helpers import verdicts

pytestmark = [
    pytest.mark.usefixtures('utf8_child_output'),
    pytest.mark.skipif(sys.platform == 'win32', reason='the project kills its parent with a POSIX signal'),
]

HARD_DEADLINE_SECONDS = 180

_TARGET = """
def is_larger(a, b):
    return a > b
"""

_TEST_THAT_KILLS_ITS_WORKER_ONCE = """
import os
import signal

import sample

_MARKER = {marker!r}


def test_larger():
    if os.environ.get('ACTIVE_GREMLIN', 'NONE') != 'NONE':
        try:
            os.close(os.open(_MARKER, os.O_CREAT | os.O_EXCL))
        except FileExistsError:
            pass
        else:
            os.kill(os.getppid(), signal.SIGKILL)
    assert sample.is_larger(2, 1)
    assert not sample.is_larger(1, 2)
"""


def _cached_statuses(project: Path) -> list[str]:
    database = project / '.gremlins_cache' / 'results.db'
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as connection:
        rows = connection.execute('SELECT result_json FROM results').fetchall()
    return [json.loads(result_json)['status'] for (result_json,) in rows]


@pytest.mark.medium
class DescribeACrashedPoolWorker:
    def it_reports_the_crash_as_an_error_without_caching_it(
        self, pytester_with_markers: pytest.Pytester, tmp_path: Path
    ) -> None:
        crashed_once = tmp_path / 'crashed-once'
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.makepyfile(test_sample=_TEST_THAT_KILLS_ITS_WORKER_ONCE.format(marker=str(crashed_once)))

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-parallel',
            '--gremlin-workers=1',
            '--gremlin-cache',
            '-p',
            'no:cacheprovider',
            timeout=HARD_DEADLINE_SECONDS,
        )

        output = result.stdout.str() + result.stderr.str()
        assert crashed_once.exists(), 'no worker was killed: the test did not exercise a crash'
        assert verdicts(output)['Error'] > 0, output
        assert 'error' not in _cached_statuses(pytester_with_markers.path)
