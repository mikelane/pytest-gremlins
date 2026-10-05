"""Selected tests with no node id are reported or abstained on, never silently dropped (issue #571)."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import (
    MagicMock,
    create_autospec,
)
import warnings

import pytest

from pytest_gremlins import plugin as plugin_module
from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _build_filtered_test_command,
    _immediate_result_if_selection_unrunnable,
    _node_ids_for_tests,
    _run_batch_mutation_testing,
    _run_mutation_testing,
    _run_parallel_mutation_testing,
    _select_tests_for_gremlin_prioritized,
    _warn_unmapped_selections,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

MAPPED = 'tests/test_m.py::test_mapped'
UNMAPPED = 'tests/test_m.py::test_unmapped[A]'
OTHER_UNMAPPED = 'tests/test_m.py::test_unmapped[B]'


def _gremlin(gremlin_id: str = 'g001') -> Gremlin:
    node = ast.parse('a < b', mode='eval').body
    return Gremlin(
        gremlin_id=gremlin_id,
        file_path='example.py',
        line_number=7,
        original_node=node,
        mutated_node=node,
        operator_name='comparison',
        description='< to <=',
    )


def _session(selected: list[str], gremlins: list[Gremlin] | None = None) -> GremlinSession:
    selector = create_autospec(PrioritizedSelector, instance=True)
    selector.select_tests_prioritized.return_value = selected
    return GremlinSession(
        enabled=True,
        gremlins=gremlins if gremlins is not None else [_gremlin()],
        prioritized_selector=selector,
        test_node_ids={MAPPED: MAPPED},
    )


@pytest.mark.small
class DescribeSelectionWithUnmappedTests:
    def it_selects_only_tests_that_have_a_node_id(self) -> None:
        session = _session([UNMAPPED, MAPPED])

        assert _select_tests_for_gremlin_prioritized(_gremlin(), session) == [MAPPED]

    def it_records_the_dropped_tests_for_the_gremlin(self) -> None:
        session = _session([UNMAPPED, MAPPED, OTHER_UNMAPPED])

        _select_tests_for_gremlin_prioritized(_gremlin('g007'), session)

        assert session.unmapped_selections == {'g007': [UNMAPPED, OTHER_UNMAPPED]}

    def it_records_nothing_when_every_selected_test_has_a_node_id(self) -> None:
        session = _session([MAPPED])

        _select_tests_for_gremlin_prioritized(_gremlin(), session)

        assert session.unmapped_selections == {}

    def it_clears_a_stale_record_when_the_gremlin_is_selected_again_without_drops(self) -> None:
        session = _session([MAPPED])
        session.unmapped_selections['g001'] = [UNMAPPED]

        _select_tests_for_gremlin_prioritized(_gremlin('g001'), session)

        assert session.unmapped_selections == {}

    def it_does_not_fall_back_to_the_whole_suite_when_every_selected_test_is_dropped(self) -> None:
        session = _session([UNMAPPED])

        assert _select_tests_for_gremlin_prioritized(_gremlin(), session) == []

    def it_hands_the_command_and_the_confirmations_the_same_node_ids(self) -> None:
        session = _session([UNMAPPED, MAPPED])
        selected = _select_tests_for_gremlin_prioritized(_gremlin(), session)

        command = _build_filtered_test_command(['pytest'], selected, session)

        assert command == ['pytest', *_node_ids_for_tests(selected, session)]
        assert command[1:] == [MAPPED]


@pytest.mark.small
class DescribeUnrunnableSelection:
    def it_abstains_with_an_error_naming_the_dropped_tests_when_the_whole_selection_is_dropped(self) -> None:
        gremlin = _gremlin()
        session = _session([UNMAPPED, OTHER_UNMAPPED])
        _select_tests_for_gremlin_prioritized(gremlin, session)

        result = _immediate_result_if_selection_unrunnable(gremlin, session)

        assert result is not None
        assert result.status == GremlinResultStatus.ERROR
        assert UNMAPPED in (result.error_output or '')
        assert OTHER_UNMAPPED in (result.error_output or '')

    def it_scores_nothing_when_part_of_the_selection_still_runs(self) -> None:
        gremlin = _gremlin()
        session = _session([UNMAPPED, MAPPED])
        _select_tests_for_gremlin_prioritized(gremlin, session)

        assert _immediate_result_if_selection_unrunnable(gremlin, session) is None

    def it_scores_nothing_for_a_gremlin_with_no_dropped_tests(self) -> None:
        session = _session([MAPPED])

        assert _immediate_result_if_selection_unrunnable(_gremlin(), session) is None


@pytest.mark.small
class DescribeUnmappedSelectionWarning:
    def it_reports_once_with_the_count_and_an_example_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        session = _session([])
        session.unmapped_selections = {'g001': [UNMAPPED, OTHER_UNMAPPED], 'g002': [UNMAPPED]}

        _warn_unmapped_selections(session)

        lines = capsys.readouterr().err.splitlines()
        assert len(lines) == 1
        assert '2 selected test(s) for 2 gremlin(s)' in lines[0]
        assert UNMAPPED in lines[0]

    def it_is_not_escalated_by_a_filterwarnings_error_config(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A project with ``filterwarnings = error`` must not crash on a green run because of this report (#543)."""
        session = _session([])
        session.unmapped_selections = {'g001': [UNMAPPED]}

        with warnings.catch_warnings():
            warnings.simplefilter('error')
            _warn_unmapped_selections(session)

        assert UNMAPPED in capsys.readouterr().err

    def it_stays_silent_when_nothing_was_dropped(self, capsys: pytest.CaptureFixture[str]) -> None:
        session = _session([MAPPED])

        _warn_unmapped_selections(session)

        assert capsys.readouterr().err == ''


@pytest.mark.small
class DescribeExecutionLoopsAbstainOnUnrunnableSelection:
    """Wiring guard: a correct helper that no loop calls would still score a verdict no test backed."""

    def it_never_runs_a_serial_gremlin_whose_whole_selection_was_dropped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fail_if_run(*_args: object, **_kwargs: object) -> GremlinResult:
            raise AssertionError('_test_gremlin ran with no node ids')

        monkeypatch.setattr(plugin_module, '_test_gremlin', fail_if_run)
        monkeypatch.setattr(plugin_module, '_get_rootdir', lambda _: tmp_path)
        monkeypatch.setattr(plugin_module, '_build_test_command', lambda *_, **__: ['pytest'])
        monkeypatch.setattr(plugin_module, '_check_cache_for_gremlin', lambda *_a, **_kw: None)

        results = _run_mutation_testing(MagicMock(spec=pytest.Session), _session([UNMAPPED]))

        assert [r.status for r in results] == [GremlinResultStatus.ERROR]

    def it_never_submits_a_parallel_gremlin_whose_whole_selection_was_dropped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fail_if_pooled(*_args: object, **_kwargs: object) -> None:
            raise AssertionError('WorkerPool was used for an unrunnable gremlin')

        monkeypatch.setattr(plugin_module, 'WorkerPool', fail_if_pooled)
        monkeypatch.setattr(plugin_module, '_get_rootdir', lambda _: tmp_path)
        monkeypatch.setattr(plugin_module, '_build_test_command', lambda *_, **__: ['pytest'])
        monkeypatch.setattr(plugin_module, '_check_cache_for_gremlin', lambda *_a, **_kw: None)

        results = _run_parallel_mutation_testing(MagicMock(spec=pytest.Session), _session([UNMAPPED]))

        assert [r.status for r in results] == [GremlinResultStatus.ERROR]

    def it_never_batches_a_gremlin_whose_whole_selection_was_dropped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fail_if_batched(*_args: object, **_kwargs: object) -> None:
            raise AssertionError('BatchExecutor was used for an unrunnable gremlin')

        monkeypatch.setattr(plugin_module, 'BatchExecutor', fail_if_batched)
        monkeypatch.setattr(plugin_module, '_get_rootdir', lambda _: tmp_path)
        monkeypatch.setattr(plugin_module, '_build_test_command', lambda *_, **__: ['pytest'])
        monkeypatch.setattr(plugin_module, '_check_cache_for_gremlin', lambda *_a, **_kw: None)

        results = _run_batch_mutation_testing(MagicMock(spec=pytest.Session), _session([UNMAPPED]))

        assert [r.status for r in results] == [GremlinResultStatus.ERROR]
