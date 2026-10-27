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
