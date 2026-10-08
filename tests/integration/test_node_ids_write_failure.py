"""A gremlin whose node ids file cannot be written is scored ERROR, and the run still completes (issue #625).

Since the node ids moved into a file (#485), every execution mode builds a gremlin's command — and so
writes that file — in the parent's main loop, with nothing guarding the write. A full disk or a tmp
cleaner removing the instrumented directory mid-run therefore aborted the whole session with a
traceback, after the user's tests had already passed, instead of costing one gremlin its verdict.

These tests inject the failure into the child project's conftest: writing the node ids file for a
selection that holds the one test covering ``lone`` raises ``OSError``. Each execution mode must then
score that gremlin ERROR with a diagnostic, keep real verdicts for the gremlins whose writes succeeded,
and still produce the report. In batch mode every uncached gremlin shares the one unified command, whose
ids include the lone test, so the whole batch is reported as ERROR results rather than a traceback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

LONE_NODE_ID = 'test_lone.py::test_lone'

_TARGET = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'


def lone(n):
    return n > 1
"""

_CLASSIFY_TESTS = """
import sample


def test_classify_one_is_small():
    assert sample.classify(1) == 'small'


def test_classify_ten_is_small():
    assert sample.classify(10) == 'small'


def test_classify_twenty_is_big():
    assert sample.classify(20) == 'big'
"""

_LONE_TESTS = """
import sample


def test_lone():
    assert sample.lone(5)
"""

# The auto-marker conftest keeps pytest-test-categories (loaded in the child through the shared venv)
# happy; the patch makes the node ids file write fail for the one selection that holds test_lone.
_CONFTEST = f"""
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line('markers', 'small: marks tests as small (fast unit tests)')


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if not any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers()):
            item.add_marker(pytest.mark.small)


import pytest_gremlins.node_id_file as node_id_file

_write_node_ids_file = node_id_file.write_node_ids_file


def _write_node_ids_file_failing_for_lone(node_ids, directory):
    if Path(directory, 'gremlin_bootstrap.py').exists() and {LONE_NODE_ID!r} in list(node_ids):
        raise OSError('injected node ids file write failure')
    return _write_node_ids_file(node_ids, directory)


node_id_file.write_node_ids_file = _write_node_ids_file_failing_for_lone
"""

_COMMON_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=comparison',
    '--gremlin-report=json',
    '-p',
    'no:cacheprovider',
)

_MODES = {
    'sequential': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}

# classify is covered by the three classify tests, which kill both its mutants (ten tells > from >=);
# lone is covered only by test_lone, so the injected write failure takes its mutants' verdicts.
_EXPECTED_VERDICTS = {
    'sequential': [
        (2, '> to <', 'zapped'),
        (2, '> to >=', 'zapped'),
        (8, '> to <', 'error'),
        (8, '> to >=', 'error'),
    ],
    'parallel': [
        (2, '> to <', 'zapped'),
        (2, '> to >=', 'zapped'),
        (8, '> to <', 'error'),
        (8, '> to >=', 'error'),
    ],
    # One unified command serves the whole batch, so its write failing costs every gremlin in it.
    'batch': [
        (2, '> to <', 'error'),
        (2, '> to >=', 'error'),
        (8, '> to <', 'error'),
        (8, '> to >=', 'error'),
    ],
}


def _verdicts(pytester: pytest.Pytester) -> list[tuple[int, str, str]]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text(encoding='utf-8'))
    return sorted((entry['line_number'], entry['description'], entry['status']) for entry in report['results'])


def _diagnostics(pytester: pytest.Pytester) -> list[str]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text(encoding='utf-8'))
    return [entry.get('error_output', '') for entry in report['results'] if entry['status'] == 'error']


@pytest.mark.medium
@pytest.mark.parametrize('mode', list(_MODES))
class DescribeNodeIdsWriteFailure:
    """The failure the issue describes: the parent's node ids file write raises OSError mid-run."""

    def it_scores_one_failed_write_as_error_and_still_reports(self, pytester: pytest.Pytester, mode: str) -> None:
        pytester.makeconftest(_CONFTEST)
        pytester.makepyfile(sample=_TARGET)
        pytester.makepyfile(test_classify=_CLASSIFY_TESTS)
        pytester.makepyfile(test_lone=_LONE_TESTS)

        result = pytester.runpytest_subprocess(*_COMMON_ARGS, *_MODES[mode])

        assert 'Traceback' not in result.stderr.str()
        assert _verdicts(pytester) == _EXPECTED_VERDICTS[mode]
        assert all('injected node ids file write failure' in diagnostic for diagnostic in _diagnostics(pytester))
