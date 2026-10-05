"""Coverage-selected parametrized tests run under their gremlins through the real entry point (issue #571)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_TARGET = """
def is_positive(x):
    return x > 0
"""

# Weak on purpose: neither case sits on the boundary, so some gremlins must survive.
_PARAMETRIZED_TESTS = """
import pytest

from sample import is_positive


@pytest.mark.parametrize(('value', 'expected'), [(1, True), (5, True)], ids={ids!r})
def test_is_positive(value, expected):
    assert is_positive(value) is expected
"""

# Covers none of sample.py, so coverage never selects it: it runs under a gremlin only when the selection is ignored.
_UNSELECTED_TRAP = """
import os


def test_unrelated():
    assert 'ACTIVE_GREMLIN' not in os.environ
"""

_RECORD_TESTS_RUN_UNDER_A_GREMLIN = """
import os


def pytest_runtest_call(item):
    gremlin_id = os.environ.get('ACTIVE_GREMLIN')
    if gremlin_id:
        with open({log!r}, 'a', encoding='utf-8') as log:
            log.write(item.nodeid + '\\n')
"""

_COMMON_ARGS = ('--gremlins', '--gremlin-targets=sample.py', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')
_WITHOUT_SIZE_MARKER_SUFFIX = ('-p', 'no:test_categories')


@pytest.fixture(autouse=True)
def _utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every pytest child these tests spawn write its output as UTF-8."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


def _verdicts(output: str) -> dict[str, int]:
    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Error')}


def _make_project(pytester: pytest.Pytester, ids: list[str]) -> Path:
    log = pytester.path / 'ran_under_gremlins.log'
    pytester.makepyfile(
        sample=_TARGET,
        test_sample=_PARAMETRIZED_TESTS.format(ids=ids),
        test_other=_UNSELECTED_TRAP,
    )
    pytester.makepyfile(conftest=_RECORD_TESTS_RUN_UNDER_A_GREMLIN.format(log=str(log)))
    return log


def _tests_run_under_gremlins(log: Path) -> set[str]:
    return set(log.read_text(encoding='utf-8').splitlines())


@pytest.mark.medium
class DescribeAllCapsParametrizeIds:
    """An all-caps parametrize id is part of the node id, not a size-marker suffix."""

    def it_runs_the_selected_all_caps_tests_under_their_gremlins(self, pytester: pytest.Pytester) -> None:
        log = _make_project(pytester, ['A', 'GET'])

        pytester.runpytest_subprocess(*_COMMON_ARGS, *_WITHOUT_SIZE_MARKER_SUFFIX)

        assert _tests_run_under_gremlins(log) == {
            'test_sample.py::test_is_positive[A]',
            'test_sample.py::test_is_positive[GET]',
        }

    def it_never_runs_a_test_coverage_did_not_select(self, pytester: pytest.Pytester) -> None:
        log = _make_project(pytester, ['A', 'GET'])

        pytester.runpytest_subprocess(*_COMMON_ARGS, *_WITHOUT_SIZE_MARKER_SUFFIX)

        assert 'test_other.py::test_unrelated' not in _tests_run_under_gremlins(log)

    def it_lets_a_gremlin_the_selected_tests_miss_survive(self, pytester: pytest.Pytester) -> None:
        _make_project(pytester, ['A', 'GET'])

        output = pytester.runpytest_subprocess(*_COMMON_ARGS, *_WITHOUT_SIZE_MARKER_SUFFIX).stdout.str()

        verdicts = _verdicts(output)
        assert verdicts['Survived'] > 0
        assert verdicts['Error'] == 0


@pytest.mark.large
class DescribeAllCapsParametrizeIdsUnderXdist:
    """xdist Phase 2 rebuilds the node ids from worker reports and must keep the all-caps id too."""

    def it_runs_only_the_selected_all_caps_tests_under_their_gremlins(self, pytester: pytest.Pytester) -> None:
        log = _make_project(pytester, ['A', 'GET'])

        output = pytester.runpytest_subprocess(*_COMMON_ARGS, *_WITHOUT_SIZE_MARKER_SUFFIX, '-n', '2').stdout.str()

        assert _tests_run_under_gremlins(log) == {
            'test_sample.py::test_is_positive[A]',
            'test_sample.py::test_is_positive[GET]',
        }
        assert _verdicts(output)['Survived'] > 0
