"""A parallel run does not wait for ever on a worker that cannot return (issue #976).

``sitecustomize`` in the run's ``PYTHONPATH`` makes the first pool worker that launches a gremlin's test command
freeze that command and then sleep for ever, outside ``subprocess.run`` and so outside its mutant timeout. The run
must still finish, with a verdict for every gremlin, and neither the worker nor its frozen test command may be
left running.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

import pytest

from tests.integration._helpers import verdicts
from tests.process_liveness import is_alive

pytestmark = [
    pytest.mark.usefixtures('utf8_child_output'),
    pytest.mark.skipif(sys.platform == 'win32', reason='the watchdog test relies on POSIX process behaviour'),
]

HARD_DEADLINE_SECONDS = 180
MUTANT_TIMEOUT_SECONDS = 2
REAPING_GRACE_SECONDS = 10

_TARGET = """
def is_larger(a, b):
    return a > b
"""

_TEST = """
import sample


def test_larger():
    assert sample.is_larger(2, 1)
    assert not sample.is_larger(1, 2)
"""

_SITECUSTOMIZE_THAT_HANGS_THE_FIRST_WORKER = """
import multiprocessing
import os
import signal
import subprocess
import time

_MARKER = {marker!r}
_PIDS = {pids!r}
_real_init = subprocess.Popen.__init__


def _hang_once_in_a_pool_worker(self, *args, **kwargs):
    env = kwargs.get('env') or {{}}
    is_gremlin_run = env.get('ACTIVE_GREMLIN', 'NONE') != 'NONE'
    if is_gremlin_run and multiprocessing.parent_process() is not None:
        try:
            os.close(os.open(_MARKER, os.O_CREAT | os.O_EXCL))
        except FileExistsError:
            pass
        else:
            _real_init(self, *args, **kwargs)
            os.kill(self.pid, signal.SIGSTOP)
            with open(_PIDS, 'w') as pids:
                pids.write(f'{{os.getpid()}} {{self.pid}}')
            time.sleep(3600)
    _real_init(self, *args, **kwargs)


subprocess.Popen.__init__ = _hang_once_in_a_pool_worker
"""


@pytest.mark.large
class DescribeAParallelRunWithAHungWorker:
    def it_finishes_and_names_the_hung_gremlin(
        self, pytester_with_markers: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pids_file = tmp_path / 'hung-pids'
        injected = tmp_path / 'injected'
        injected.mkdir()
        (injected / 'sitecustomize.py').write_text(
            _SITECUSTOMIZE_THAT_HANGS_THE_FIRST_WORKER.format(marker=str(tmp_path / 'hung-once'), pids=str(pids_file))
        )
        monkeypatch.setenv('PYTHONPATH', str(injected))
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.makepyfile(test_sample=_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-parallel',
            '--gremlin-workers=2',
            f'--gremlin-mutant-timeout={MUTANT_TIMEOUT_SECONDS}',
            timeout=HARD_DEADLINE_SECONDS,
        )

        output = result.stdout.str() + result.stderr.str()
        assert (tmp_path / 'hung-once').exists(), 'no worker was hung: the test did not exercise the watchdog'
        assert 'hung-worker watchdog killed the worker of gremlin' in output
        assert sum(verdicts(output).values()) == 3
        worker_pid, test_command_pid = (int(pid) for pid in pids_file.read_text().split())
        assert _all_gone([worker_pid, test_command_pid]), _describe([worker_pid, test_command_pid])


def _all_gone(pids: list[int]) -> bool:
    """Wait up to the reaping grace for every pid to disappear; a freshly killed process is reaped by init."""
    deadline = time.monotonic() + REAPING_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not any(is_alive(pid) for pid in pids):
            return True
        time.sleep(0.1)
    return False


def _describe(pids: list[int]) -> str:
    listing = subprocess.run(
        ['ps', '-o', 'pid,ppid,pgid,stat,command', '-p', ','.join(map(str, pids))],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return listing.stdout
