"""Source lookup inside an instrumented module reads the original file instead of failing (#563).

A module compiled under its dotted name has no file for ``inspect.getsource`` to read, so a test that
only asserts source lookup succeeded was falsely zapped by every gremlin.
"""

from __future__ import annotations

import re

import pytest

_PADDING = '# padding\n' * 30

_TARGET = (
    """
import inspect

"""
    + _PADDING
    + """

def is_positive(x):
    return x > 0


def source_is_readable():
    source = inspect.getsource(is_positive)
    return source.startswith('def is_positive(') and 'x > 0' in source
"""
)

_TESTS = """
import sample


def test_source_is_readable():
    assert sample.source_is_readable() is True
"""

_EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


_UNOBSERVED_GREMLIN = re.compile(r'sample\.py:\d+ > to >=')


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeSourceLookupInInstrumentedModule:
    """``x > 0`` to ``x >= 0`` is invisible to the tests, so it survives instead of being zapped by a lookup failure."""

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_lets_an_unobserved_gremlin_survive(self, pytester_with_markers: pytest.Pytester, mode: str) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.makepyfile(test_sample=_TESTS)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '-p',
            'no:cacheprovider',
            *_EXECUTION_MODES[mode],
        )

        assert _UNOBSERVED_GREMLIN.search(result.stdout.str())
