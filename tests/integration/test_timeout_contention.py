"""A timeout caused by worker contention is not a kill (issue #565).

In parallel and batch mode a gremlin runs among other workers, but the unmutated confirmation runs alone.
A test that asserts nothing, slowed only by a lock the workers share, must not be scored as a kill: the
timed-out gremlin is re-run alone first, where it finishes and survives.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

pytestmark = [
    pytest.mark.usefixtures('utf8_child_output'),
    pytest.mark.skipif(sys.platform == 'win32', reason='the shared lock uses fcntl, which is Unix-only'),
]

_TARGET = """
def is_larger(a, b):
    return a > b


def add(a, b):
    return a + b


def sub(a, b):
    return a - b
"""

_TEST_THAT_ASSERTS_NOTHING_AND_SHARES_A_LOCK = """
import fcntl
import pathlib
import time

import pytest
import sample


@pytest.mark.medium
def test_uses_shared_resource():
    with open(pathlib.Path(__file__).with_name('shared.lock'), 'w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        sample.is_larger(2, 1)
        sample.add(1, 2)
        sample.sub(1, 2)
        time.sleep(5)
"""

_MODES = {
    'parallel': ('--gremlin-parallel', '--gremlin-workers=4'),
    'batch': ('--gremlin-batch', '--gremlin-workers=4', '--gremlin-batch-size=1'),
}

_LIMIT_BELOW_THE_QUEUED_RUNS_BUT_ABOVE_A_SOLO_RUN = 15


@pytest.mark.large
@pytest.mark.parametrize('mode', list(_MODES))
class DescribeTimeoutCausedByContention:
    """Workers queueing on a shared lock make a gremlin time out that is fine alone."""

    def it_does_not_score_a_contention_timeout_of_a_test_that_asserts_nothing_as_a_kill(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.makepyfile(test_sample=_TEST_THAT_ASSERTS_NOTHING_AND_SHARES_A_LOCK)

        pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-report=json',
            '-p',
            'no:cacheprovider',
            f'--gremlin-mutant-timeout={_LIMIT_BELOW_THE_QUEUED_RUNS_BUT_ABOVE_A_SOLO_RUN}',
            *_MODES[mode],
        )

        report = json.loads(Path(pytester_with_markers.path, 'coverage', 'gremlins', 'gremlins.json').read_text())
        assert report['summary']['timeout'] == 0, report['summary']
        assert report['summary']['zapped'] == 0, report['summary']
