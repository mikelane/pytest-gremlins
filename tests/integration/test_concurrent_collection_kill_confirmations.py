"""Concurrent collection-kill confirmations score exactly like serial ones (issue #553).

Pooled modes confirm the distinct selections of all load failures concurrently before scoring.
The verdicts must match what the sequential mode, which confirms one at a time, reports.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

_TARGET_TEMPLATE = """
SLOTS = ('first', 'second')
LAST = SLOTS[2 - 1]


def {name}():
    return LAST
"""

_TEST_TEMPLATE = """
import {module}


def test_{module}():
    assert {module}.{module}() == 'second'
"""

_MODULES = ('alpha', 'beta', 'gamma')

_COMMON_ARGS = (
    '--gremlins',
    '--gremlin-targets=alpha.py,beta.py,gamma.py',
    '--gremlin-operators=arithmetic',
    '--gremlin-report=json',
    '-p',
    'no:cacheprovider',
)

_POOLED_MODES = {
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


def _verdicts(pytester: pytest.Pytester) -> list[tuple[str, str, str | None]]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text())
    return sorted((entry['file_path'], entry['status'], entry.get('killing_test')) for entry in report['results'])


def _write_project(pytester: pytest.Pytester) -> None:
    for module in _MODULES:
        pytester.makepyfile(**{module: _TARGET_TEMPLATE.format(name=module)})
        pytester.makepyfile(**{f'test_{module}': _TEST_TEMPLATE.format(module=module)})


@pytest.mark.medium
@pytest.mark.parametrize('mode', list(_POOLED_MODES))
class DescribePooledVerdictsMatchSerialConfirmation:
    """Several distinct load failures are scored the same whether confirmed serially or concurrently."""

    def it_reports_the_same_verdicts_as_the_sequential_mode(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        _write_project(pytester_with_markers)
        pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS)
        serial_verdicts = _verdicts(pytester_with_markers)

        pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_POOLED_MODES[mode])

        assert _verdicts(pytester_with_markers) == serial_verdicts

    def it_zaps_every_load_failure_with_the_collection_phase_as_killer(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        _write_project(pytester_with_markers)

        pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_POOLED_MODES[mode])

        outcomes = {(status, killer) for _, status, killer in _verdicts(pytester_with_markers)}
        assert outcomes == {('zapped', '<collection>')}


_SIBLING_TARGET = """
def first(a, b):
    return a + b


def second(a, b):
    return a - b


def third(a, b):
    return a * b
"""

_TEST_A = """
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'helpers'))

import sample


def test_first():
    assert sample.first(0, 0) in (0, None)
"""

_TEST_NEEDING_SIBLING = """
import helperlib  # importable only after test_a extended sys.path in the same session
import sample


def test_{name}():
    assert sample.{name}(0, 0) in (0, None)
"""

_SPY_PLUGIN = """
import json
import os

import pytest_gremlins.plugin as gremlin_plugin

_original = gremlin_plugin._prefill_collection_kill_confirmations


def _spy(pending, gremlin_session, rootdir):
    distinct = {tuple(node_ids) for _, node_ids in pending}
    with open(os.environ['PREFILL_LOG'], 'a') as log:
        log.write(json.dumps(len(distinct)) + '\\n')
    return _original(pending, gremlin_session, rootdir)


gremlin_plugin._prefill_collection_kill_confirmations = _spy
"""

_SIBLING_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=arithmetic',
    '--gremlin-report=json',
    '-p',
    'no:cacheprovider',
)


def _write_sibling_project(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(sample=_SIBLING_TARGET)
    pytester.mkdir('helpers')
    Path(pytester.path, 'helpers', 'helperlib.py').write_text('VALUE = 1\n')
    pytester.makepyfile(test_a=_TEST_A)
    pytester.makepyfile(test_b=_TEST_NEEDING_SIBLING.format(name='second'))
    pytester.makepyfile(test_c=_TEST_NEEDING_SIBLING.format(name='third'))


def _results(pytester: pytest.Pytester) -> list[tuple[str, str, str | None]]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text())
    return sorted((entry['description'], entry['status'], entry.get('killing_test')) for entry in report['results'])


@pytest.mark.medium
class DescribeSeveralDistinctSelectionsConfirmedConcurrently:
    """Two selections that cannot load unmutated are confirmed together and downgraded like serial ones."""

    def it_downgrades_every_unloadable_selection_exactly_as_the_sequential_mode_does(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        _write_sibling_project(pytester_with_markers)
        pytester_with_markers.runpytest_subprocess(*_SIBLING_ARGS)
        serial_results = _results(pytester_with_markers)

        pytester_with_markers.runpytest_subprocess(*_SIBLING_ARGS, '--gremlin-parallel', '--gremlin-workers=2')

        assert _results(pytester_with_markers) == serial_results
        assert [status for _, status, _ in serial_results].count('error') == 2

    def it_confirms_more_than_one_distinct_selection_in_one_prefill(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_sibling_project(pytester_with_markers)
        pytester_with_markers.makepyfile(spy_plugin=_SPY_PLUGIN)
        log = Path(pytester_with_markers.path, 'prefill.log')
        monkeypatch.setenv('PREFILL_LOG', str(log))
        monkeypatch.setenv('PYTHONPATH', str(pytester_with_markers.path))

        pytester_with_markers.runpytest_subprocess(
            *_SIBLING_ARGS, '-p', 'spy_plugin', '--gremlin-parallel', '--gremlin-workers=2'
        )

        assert max(int(line) for line in log.read_text().split()) > 1
