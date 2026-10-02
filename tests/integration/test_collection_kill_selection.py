"""A gremlin's load failure is confirmed against its own selection, not just the union (issue #550).

The unmutated control run collects every selected node id in ONE session. A gremlin subprocess
collects only the node ids covering that gremlin. When one test module only imports because a
sibling module was collected first in the same session (it extends ``sys.path`` at import), the
union loads but the subset does not, so the subset's load failure is not the mutant's doing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

_TARGET = """
def first(a, b):
    return a + b


def second(a, b):
    return a - b
"""

_TEST_THAT_EXTENDS_SYS_PATH = """
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'helpers'))

import sample


def test_first():
    assert sample.first(0, 0) in (0, None)
"""

_TEST_THAT_NEEDS_THE_SIBLING = """
import helperlib  # importable only after test_a extended sys.path in the same session
import sample


def test_second():
    assert sample.second(0, 0) in (0, None)
"""

_COMMON_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=arithmetic',
    '--gremlin-report=json',
    '-p',
    'no:cacheprovider',
)

_MODES = {
    'sequential': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


# Batch runs every gremlin with one unified command whose order loads, so the weak test honestly survives.
_EXPECTED_STATUS_OF_SECOND_GREMLIN = {'sequential': 'error', 'parallel': 'error', 'batch': 'survived'}


def _status_by_description(pytester: pytest.Pytester) -> dict[str, str]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text())
    return {entry['description']: entry['status'] for entry in report['results']}


@pytest.mark.medium
@pytest.mark.parametrize('mode', list(_MODES))
class DescribeSubsetLoadFailuresTheControlRunCannotSee:
    """A subset that cannot load unmutated is not a kill, even when the union loads."""

    def it_never_scores_a_collection_kill_for_a_test_that_only_imports_after_a_sibling_module(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.mkdir('helpers')
        Path(pytester_with_markers.path, 'helpers', 'helperlib.py').write_text('VALUE = 1\n')
        pytester_with_markers.makepyfile(test_a=_TEST_THAT_EXTENDS_SYS_PATH)
        pytester_with_markers.makepyfile(test_b=_TEST_THAT_NEEDS_THE_SIBLING)

        pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_MODES[mode])

        statuses = _status_by_description(pytester_with_markers)
        assert statuses['- to +'] == _EXPECTED_STATUS_OF_SECOND_GREMLIN[mode]
