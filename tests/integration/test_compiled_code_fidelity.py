"""Compiling instrumented modules in the parent must not change what the gremlin subprocess executes (#563 follow-up).

The parent compiles each instrumented module and ships the code object to the gremlin subprocess. Two parent-only
settings leak into that shipped code: the interpreter's optimize level (``python -O`` strips the target's asserts
although the subprocess runs without ``-O``) and the session's warning filters (a compile-time ``SyntaxWarning``
promoted to an error drops the whole target).
"""

from __future__ import annotations

import py_compile
import re
import sys
import warnings

import pytest

_ASSERTING_TARGET = """
def clamp(x):
    if x >= 100:
        return 100
    assert x > 0, 'x must be positive'
    return x
"""

_ASSERTING_TESTS = """
import sys

import pytest

from sample import clamp


def test_small_value():
    assert clamp(3) == 3


@pytest.mark.skipif(sys.flags.optimize > 0, reason='asserts are stripped under -O')
def test_rejects_zero():
    with pytest.raises(AssertionError):
        clamp(0)
"""

_UNOBSERVED_BOUNDARY_GREMLIN = re.compile(r'sample\.py:2 >= to >\s')

_WARNING_TARGET = """
def is_big(x):
    if x is 1:
        return False
    return x > 10
"""

_WARNING_TESTS = """
from sample import is_big


def test_big():
    assert is_big(11)
    assert not is_big(10)
"""


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeCompiledCodeFidelity:
    """The code a gremlin subprocess runs behaves like the target module imported in that subprocess."""

    def it_keeps_target_asserts_when_only_the_parent_runs_with_dash_o(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(sample=_ASSERTING_TARGET)
        pytester_with_markers.makepyfile(test_sample=_ASSERTING_TESTS)

        result = pytester_with_markers.run(
            sys.executable,
            '-O',
            '-m',
            'pytest',
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '-p',
            'no:cacheprovider',
        )

        assert _UNOBSERVED_BOUNDARY_GREMLIN.search(result.stdout.str())

    def it_tests_a_target_whose_compile_warning_the_session_treats_as_an_error(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        target = pytester_with_markers.makepyfile(sample=_WARNING_TARGET)
        pytester_with_markers.makepyfile(test_sample=_WARNING_TESTS)
        pytester_with_markers.makeini('[pytest]\nfilterwarnings = error\n')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            py_compile.compile(str(target), doraise=True)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '-p',
            'no:cacheprovider',
        )

        assert 'No gremlins found' not in result.stdout.str()
