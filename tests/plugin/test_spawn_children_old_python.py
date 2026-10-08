"""A child interpreter older than 3.10 must not turn into a false ZAPPED (#604 adversarial QA, run 2).

The spawn hook embeds ``origin_finder``'s source, whose module-level type aliases (``X | None``,
``dict[str, ...]``) are evaluated at import. Python 3.9 and earlier cannot evaluate them, so importing the hook
raises before the version gate runs: ``site`` prints ``Error in sitecustomize`` on the child's stderr and the
user's own ``sitecustomize`` is never chained. Both happen only in gremlin runs, so a test that checks the
child's stderr kills a gremlin it cannot see.
"""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest


def _find_old_python() -> str | None:
    pyenv_versions = Path.home() / '.pyenv' / 'versions'
    candidates = sorted(pyenv_versions.glob('3.9.*/bin/python3.9')) + sorted(pyenv_versions.glob('3.8.*/bin/python3.8'))
    if candidates:
        return str(candidates[-1])
    return shutil.which('python3.9') or shutil.which('python3.8')


OLD_PYTHON = _find_old_python()

_TARGET = """\
def double(value):
    return value * 2
"""

# ``double(0)`` cannot tell ``value * 2`` from ``value / 2``: that gremlin must survive. The old child does not
# even import the target; it only has to start cleanly.
_TEST = f"""\
import subprocess

from target import double


def test_double_and_an_old_child():
    assert double(0) == 0
    child = subprocess.run([{OLD_PYTHON!r}, '-c', 'pass'], capture_output=True, text=True)
    assert child.stderr == ''
"""


@pytest.mark.medium
@pytest.mark.skipif(OLD_PYTHON is None, reason='needs a python3.9 or python3.8')
class DescribeChildOfAnOldPython:
    """A gremlin the test cannot detect survives even when the test starts a pre-3.10 interpreter."""

    def it_does_not_zap_a_gremlin_the_test_cannot_detect(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(target=_TARGET)
        pytester_with_markers.makepyfile(test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        result.stdout.fnmatch_lines(['*Survived: 1 gremlins*'])
