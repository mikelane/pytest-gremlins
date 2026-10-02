"""A load failure the mutant did not cause is never scored as a kill (issue #550).

Each scenario below has a green baseline and a weak test the gremlins survive. The suite still
fails to load inside the gremlin subprocess for a reason that has nothing to do with the mutant
(the bootstrap, the forwarded command, or the environment differ from the baseline session), so a
``<collection>`` kill would be a fabricated verdict. An unmutated control run in the same subprocess
harness detects this up front, and every gremlin is then reported as ERROR with one diagnostic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures('utf8_child_output')

_TARGET = """
def add(a, b):
    return a + b
"""

_TARGET_USING_DUNDER_FILE = """
from pathlib import Path

HERE = Path(__file__).parent


def add(a, b):
    return a + b
"""

_WEAK_TEST = """
import sample


def test_add():
    assert sample.add(0, 0) in (0, None)
"""

_WEAK_TEST_WITH_RANDOM_PARAMETRIZE_ID = """
import uuid

import pytest
import sample


@pytest.mark.parametrize('token', [uuid.uuid4().hex])
def test_add(token):
    assert sample.add(0, 0) in (0, None)
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

_DIAGNOSTIC = 'the unmutated test suite fails to load in the gremlin subprocess'


def _statuses_and_killers(pytester: pytest.Pytester) -> list[tuple[str, str | None]]:
    report = json.loads(Path(pytester.path, 'coverage', 'gremlins', 'gremlins.json').read_text())
    return [(entry['status'], entry.get('killing_test')) for entry in report['results']]


def _assert_reported_as_errors(pytester: pytest.Pytester, result: pytest.RunResult) -> None:
    verdicts = _statuses_and_killers(pytester)
    assert verdicts
    assert all(status == 'error' for status, _ in verdicts)
    assert '<collection>' not in [killer for _, killer in verdicts]
    assert result.stderr.str().count(_DIAGNOSTIC) == 1


@pytest.mark.medium
@pytest.mark.parametrize('mode', list(_MODES))
class DescribeLoadFailuresTheMutantDidNotCause:
    """A suite that cannot load in the gremlin subprocess regardless of the mutant is not a kill."""

    def it_reports_errors_for_a_module_that_reads_dunder_file_at_import(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET_USING_DUNDER_FILE)
        pytester_with_markers.makepyfile(test_sample=_WEAK_TEST)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_MODES[mode])

        _assert_reported_as_errors(pytester_with_markers, result)

    def it_reports_errors_for_a_per_process_parametrize_id(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.makepyfile(test_sample=_WEAK_TEST_WITH_RANDOM_PARAMETRIZE_ID)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_MODES[mode])

        _assert_reported_as_errors(pytester_with_markers, result)

    def it_reports_errors_when_a_cli_only_import_mode_is_not_forwarded(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET)
        pytester_with_markers.mkdir('first')
        pytester_with_markers.mkdir('second')
        Path(pytester_with_markers.path, 'first', 'test_same_name.py').write_text(_WEAK_TEST)
        Path(pytester_with_markers.path, 'second', 'test_same_name.py').write_text(_WEAK_TEST)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, '--import-mode=importlib', *_MODES[mode])

        _assert_reported_as_errors(pytester_with_markers, result)

    def it_names_the_cause_in_the_diagnostic(self, pytester_with_markers: pytest.Pytester, mode: str) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET_USING_DUNDER_FILE)
        pytester_with_markers.makepyfile(test_sample=_WEAK_TEST)

        result = pytester_with_markers.runpytest_subprocess(*_COMMON_ARGS, *_MODES[mode])

        assert '__file__' in result.stderr.str()
