"""Tests for scripts/check_verdict_change.py -- the CI gate on verdict changes without a cache-version bump (#876)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_verdict_change.py'


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_verdict_change', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['check_verdict_change'] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

BASE_MARKERS = checker.Markers(cache_version='1', runner_fidelity_version='rf21')
ZAPPED = {'sample.py:10 comparison: >= to >': 'zapped'}
SURVIVED = {'sample.py:10 comparison: >= to >': 'survived'}


@pytest.mark.small
class DescribeVerdictCheck:
    def it_passes_when_every_verdict_is_unchanged(self) -> None:
        failure = checker.check_verdicts(ZAPPED, ZAPPED, BASE_MARKERS, BASE_MARKERS)

        assert failure is None

    def it_fails_when_a_verdict_changed_and_no_marker_was_raised(self) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, BASE_MARKERS)

        assert failure is not None

    @pytest.mark.parametrize(
        'head_markers',
        [
            checker.Markers(cache_version='2', runner_fidelity_version='rf21'),
            checker.Markers(cache_version='1', runner_fidelity_version='rf22'),
        ],
        ids=['cache-version', 'runner-fidelity-version'],
    )
    def it_passes_when_a_verdict_changed_and_a_marker_was_raised(self, head_markers: object) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, head_markers)

        assert failure is None

    def it_names_a_gremlin_whose_verdict_changed_with_both_verdicts(self) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, BASE_MARKERS)

        assert 'sample.py:10 comparison: >= to >: zapped -> survived' in failure

    def it_asks_for_the_runner_fidelity_version_when_only_verdicts_changed(self) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, BASE_MARKERS)

        assert failure.endswith(checker.RUNNER_FIDELITY_ADVICE)

    def it_names_a_gremlin_that_only_the_head_code_creates(self) -> None:
        head = {**ZAPPED, 'sample.py:12 boolean: and to or': 'zapped'}

        failure = checker.check_verdicts(ZAPPED, head, BASE_MARKERS, BASE_MARKERS)

        assert 'added: sample.py:12 boolean: and to or' in failure

    def it_names_a_gremlin_that_the_head_code_no_longer_creates(self) -> None:
        base = {**ZAPPED, 'sample.py:12 boolean: and to or': 'zapped'}

        failure = checker.check_verdicts(base, ZAPPED, BASE_MARKERS, BASE_MARKERS)

        assert 'removed: sample.py:12 boolean: and to or' in failure

    def it_asks_for_the_cache_version_when_the_set_of_gremlins_changed(self) -> None:
        head = {**ZAPPED, 'sample.py:12 boolean: and to or': 'zapped'}

        failure = checker.check_verdicts(ZAPPED, head, BASE_MARKERS, BASE_MARKERS)

        assert failure.endswith(checker.CACHE_VERSION_ADVICE)


def _entry(line_number: int, status: str, description: str = '>= to >') -> dict[str, object]:
    return {
        'gremlin_id': f'sample_ab12_g{line_number:03d}',
        'file_path': '/runner/work/sample/sample.py',
        'line_number': line_number,
        'status': status,
        'operator': 'comparison',
        'description': description,
    }


@pytest.mark.small
class DescribeVerdictsFromReport:
    def it_keys_each_verdict_by_the_path_inside_the_sample_and_the_mutation(self) -> None:
        report = {'results': [_entry(10, 'zapped')]}

        verdicts = checker.verdicts_from_report(report, Path('/runner/work/sample'))

        assert verdicts == {'sample.py:10 comparison: >= to >': 'zapped'}

    def it_numbers_gremlins_that_share_a_line_operator_and_description(self) -> None:
        report = {'results': [_entry(10, 'zapped', 'boundary shift'), _entry(10, 'survived', 'boundary shift')]}

        verdicts = checker.verdicts_from_report(report, Path('/runner/work/sample'))

        assert verdicts == {
            'sample.py:10 comparison: boundary shift': 'zapped',
            'sample.py:10 comparison: boundary shift #2': 'survived',
        }


GUARDED = frozenset({'src/pytest_gremlins/plugin.py', 'src/pytest_gremlins/config.py'})


@pytest.mark.small
class DescribeGuardedChanges:
    def it_keeps_a_changed_path_that_the_guard_covers(self) -> None:
        changes = checker.guarded_changes(['src/pytest_gremlins/plugin.py', 'docs/index.md'], [], GUARDED)

        assert changes == ['src/pytest_gremlins/plugin.py']

    def it_drops_a_changed_package_file_that_the_guard_excludes(self) -> None:
        changes = checker.guarded_changes(['src/pytest_gremlins/reporting/html.py'], [], GUARDED)

        assert changes == []

    def it_keeps_a_deleted_package_module_because_the_head_guard_cannot_list_it(self) -> None:
        deleted = ['src/pytest_gremlins/old_module.py']

        changes = checker.guarded_changes(deleted, deleted, GUARDED)

        assert changes == ['src/pytest_gremlins/old_module.py']

    def it_drops_a_deleted_file_outside_the_package_sources(self) -> None:
        deleted = ['tests/test_old.py', 'src/pytest_gremlins/py.typed']

        changes = checker.guarded_changes(deleted, deleted, GUARDED)

        assert changes == []
