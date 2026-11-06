"""A failing cache flush is reported in the terminal summary, not only in a log pytest swallows (issue #974)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

_SAMPLE = """
def add(a, b):
    return a + b
"""

_TEST = """
from sample import add


def test_add():
    assert add(2, 3) == 5
"""

_CONFTEST_BREAKING_FLUSH = """
import sqlite3

from pytest_gremlins.cache.incremental import IncrementalCache


def _disk_full(self):
    raise sqlite3.OperationalError('database or disk is full')


IncrementalCache.flush = _disk_full
"""

_MODES = {
    'sequential': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
}


@pytest.mark.medium
@pytest.mark.parametrize('mode', list(_MODES))
class DescribeFlushFailureNotice:
    def it_prints_one_warning_in_the_terminal_summary_and_still_reports(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_SAMPLE, test_sample=_TEST)
        pytester_with_markers.makeconftest(
            pytester_with_markers.path.joinpath('conftest.py').read_text() + _CONFTEST_BREAKING_FLUSH
        )

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=sample.py', '--gremlin-cache', '-p', 'no:cacheprovider', *_MODES[mode]
        )

        output = result.stdout.str()
        assert (
            output.count('could not write finished results to the cache (OperationalError: database or disk is full)')
            == 1
        )
        assert 'Mutation Testing' in output or 'zapped' in output.lower()
