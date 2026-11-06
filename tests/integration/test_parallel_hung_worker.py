"""A parallel run does not wait for ever on a worker that cannot return (issue #976).

``sitecustomize`` in the run's ``PYTHONPATH`` makes the first pool worker that launches a gremlin's test command
sleep for ever before the launch, outside ``subprocess.run`` and so outside its mutant timeout. The run must
still finish, with a verdict for every gremlin.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from tests.integration._helpers import verdicts

pytestmark = [
    pytest.mark.usefixtures('utf8_child_output'),
    pytest.mark.skipif(sys.platform == 'win32', reason='the watchdog test relies on POSIX process behaviour'),
]

HARD_DEADLINE_SECONDS = 180
MUTANT_TIMEOUT_SECONDS = 2

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
import subprocess
import time

_MARKER = {marker!r}
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
            time.sleep(3600)
    _real_init(self, *args, **kwargs)


subprocess.Popen.__init__ = _hang_once_in_a_pool_worker
"""


@pytest.mark.large
class DescribeAParallelRunWithAHungWorker:
    def it_finishes_and_names_the_hung_gremlin(
        self, pytester_with_markers: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        injected = tmp_path / 'injected'
        injected.mkdir()
        (injected / 'sitecustomize.py').write_text(
            _SITECUSTOMIZE_THAT_HANGS_THE_FIRST_WORKER.format(marker=str(tmp_path / 'hung-once'))
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
        assert 'is hung' in output
        assert sum(verdicts(output).values()) == 3
