"""A collection kill is confirmed for the order its selection runs in, not just the set (issue #550).

pytest collects command-line node ids in the order given. A module-level gremlin falls back to
every test in collection order, while a covered gremlin gets its tests by specificity. Both can
name the same set of node ids in different orders, and in a suite where one test module only
imports after its sibling, one order loads and the other does not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_TARGET = """
LEVELS = (1 + 1,)


def first(a, b):
    return a * b


def second(a, b):
    return a - b
"""

# Collected first in the suite; covers first() and second(), so it is the LESS specific test.
_TEST_A = """
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'helpers'))

import sample

assert sample.LEVELS == (2,)


def test_a():
    assert sample.first(1, 1) == 1
    assert sample.second(0, 0) in (0, None)
"""

# Covers only second(), so selection by specificity puts it FIRST, before the module it depends on.
_TEST_B = """
import helperlib  # importable only after test_a extended sys.path in the same session
import sample


def test_b():
    assert sample.second(0, 0) in (0, None)
"""


def _status_by_description(pytester: pytest.Pytester) -> dict[str, str]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text())
    return {entry['description']: entry['status'] for entry in report['results']}


@pytest.mark.medium
@pytest.mark.usefixtures('utf8_child_output')
class DescribeConfirmationMemoKeyedByOrder:
    """A selection is only confirmed for the order it actually runs in."""

    def it_reports_an_error_for_a_gremlin_whose_selection_order_fails_to_load(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.mkdir('helpers')
        Path(pytester_with_markers.path, 'helpers', 'helperlib.py').write_text('VALUE = 1\n')
        pytester_with_markers.makepyfile(test_a=_TEST_A)
        pytester_with_markers.makepyfile(test_b=_TEST_B)

        pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=arithmetic',
            '--gremlin-report=json',
            '-p',
            'no:cacheprovider',
        )

        assert _status_by_description(pytester_with_markers)['- to +'] == 'error'
