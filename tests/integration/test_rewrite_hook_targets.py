"""Targets that pytest's assertion-rewrite hook serves are still instrumented (#603).

pytest installs its ``AssertionRewritingHook`` at the front of ``sys.meta_path`` while parsing the
command line. The gremlin finder is installed before ``pytest.main`` and so ends up behind it, which
left every module the hook claims (``python_files`` matches, ``conftest.py``) uncompiled by us, so its
gremlins could never be zapped.
"""

from __future__ import annotations

import re

import pytest

_COMMON_ARGS = ('--gremlins', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

_POSITIVE = """
def positive(n):
    return n > 0
"""

_HELPER_TESTS = """
from mypkg.core_impl import positive


def test_positive():
    assert positive(1)
    assert not positive(0)
"""

_CONFTEST_WITH_TARGET = """
def positive(n):
    return n > 0
"""

_CONFTEST_TESTS = """
import conftest


def test_positive():
    assert conftest.positive(1)
    assert not conftest.positive(0)
"""


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


def _verdicts(output: str) -> tuple[int, int, int]:
    return _count(output, 'Zapped'), _count(output, 'Survived'), _count(output, 'Error')


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeRewriteHookTargets:
    """A target pytest would rewrite is instrumented anyway, so a test that catches its mutant zaps it."""

    def it_zaps_a_target_whose_file_name_matches_python_files(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\npythonpath = src\npython_files = test_*.py *_impl.py\n')
        package = pytester_with_markers.path / 'src' / 'mypkg'
        package.mkdir(parents=True)
        package.joinpath('__init__.py').write_text('')
        package.joinpath('core_impl.py').write_text(_POSITIVE)
        pytester_with_markers.mkdir('tests').joinpath('test_helper.py').write_text(_HELPER_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=src/mypkg')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)

    def it_zaps_a_conftest_target(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeconftest(_CONFTEST_WITH_TARGET)
        pytester_with_markers.mkdir('tests').joinpath('test_conftest_target.py').write_text(_CONFTEST_TESTS)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--gremlin-targets=conftest.py')

        assert _verdicts(result.stdout.str()) == (2, 0, 0)
