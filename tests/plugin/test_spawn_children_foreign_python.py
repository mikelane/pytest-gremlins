"""A test that starts an interpreter of another Python version must not turn into a false ZAPPED (#604 adversarial QA).

The spawn hook reaches every interpreter the test starts, not only ``multiprocessing`` children. A Python 3.11 child
cannot unpickle an ``ast`` tree pickled by 3.13 or later, so the import of the target fails there. That failure
happens only in gremlin runs (the plain run and the control run carry no hook), so it is reported as a kill of a
gremlin the test cannot see.
"""

from __future__ import annotations

import shutil
import sys

import pytest

FOREIGN_PYTHON = shutil.which('python3.11')

_TARGET = """\
def double(value):
    return value * 2
"""

# ``double(0)`` cannot tell ``value * 2`` from ``value / 2``: that gremlin must survive. The 3.11 child only has
# to import the target and run without error.
_TEST = f"""\
import pathlib
import subprocess

from target import double


def test_double_and_a_foreign_child():
    assert double(0) == 0
    child = subprocess.run(
        [{FOREIGN_PYTHON!r}, '-c', 'from target import double; double(0)'],
        cwd=pathlib.Path(__file__).parent,
        capture_output=True,
        text=True,
    )
    assert child.returncode == 0, child.stderr
"""


@pytest.mark.medium
@pytest.mark.skipif(FOREIGN_PYTHON is None, reason='needs a python3.11 on PATH')
@pytest.mark.skipif(sys.version_info < (3, 13), reason='a 3.11/3.12 tree still unpickles in 3.11')
class DescribeChildOfAnotherPython:
    """A gremlin the test cannot detect survives even when the test starts an interpreter of another version."""

    def it_does_not_zap_a_gremlin_the_test_cannot_detect(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(target=_TARGET)
        pytester_with_markers.makepyfile(test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        result.stdout.fnmatch_lines(['*Survived: 1 gremlins*'])
