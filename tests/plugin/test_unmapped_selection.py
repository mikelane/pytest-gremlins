"""Selected tests with no node id are reported or abstained on, never silently dropped (issue #571)."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import (
    MagicMock,
    create_autospec,
)
import warnings

import pytest

from pytest_gremlins import plugin as plugin_module
from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.control_run import (
    ControlRunOutcome,
    run_control,
)
from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _build_filtered_test_command,
    _build_test_hashes_for_gremlin,
    _immediate_result_if_selection_unrunnable,
    _node_ids_for_tests,
    _run_batch_mutation_testing,
    _run_mutation_testing,
    _run_parallel_mutation_testing,
    _select_tests_for_gremlin_prioritized,
    _verify_suite_loads_unmutated,
    _warn_unmapped_selections,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.reporting.score import MutationScore

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


@pytest.mark.small
class DescribeControlRunIgnoresUnrunnableGremlins:
    def it_spawns_no_control_run_when_every_gremlin_was_left_with_no_test(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An empty node-id list would make the control run load the whole suite for gremlins that never run."""
        control = create_autospec(
            run_control, return_value=ControlRunOutcome(loads_cleanly=True, output='', seconds=0.1)
        )
        monkeypatch.setattr(plugin_module, 'run_control', control)
        monkeypatch.setattr(plugin_module, '_get_rootdir', lambda _: tmp_path)
        session = _session([UNMAPPED])
        session.instrumented_dir = tmp_path

        _verify_suite_loads_unmutated(SimpleNamespace(config=None), session)  # type: ignore[arg-type]

        control.assert_not_called()


@pytest.mark.medium
class DescribeCacheKeyAfterTheMarkerFix:
    """A verdict cached from the shorter selection must not be replayed for the now-complete one (issue #571)."""

    def it_misses_a_verdict_cached_before_the_parametrized_test_gained_a_node_id(self, tmp_path: Path) -> None:
        parametrized = 't.py::test_x[A]'
        before = GremlinSession(test_node_ids={'t.py::test_x': 't.py::test_x'}, test_hashes={'t.py': 'file-hash'})
        after = GremlinSession(test_node_ids={parametrized: parametrized}, test_hashes={'t.py': 'file-hash'})
        cache = IncrementalCache(tmp_path)
        cache.cache_result(
            'g001', 'src', _build_test_hashes_for_gremlin([parametrized], before), {'status': 'survived'}
        )

        replayed = cache.get_cached_result('g001', 'src', _build_test_hashes_for_gremlin([parametrized], after))
        cache.close()

        assert replayed is None


@pytest.mark.small
class DescribeScoringOfUnrunnableGremlins:
    def it_counts_the_abstention_as_an_error_that_stays_in_the_denominator(self) -> None:
        gremlin = _gremlin()
        session = _session([UNMAPPED])
        _select_tests_for_gremlin_prioritized(gremlin, session)
        abstained = _immediate_result_if_selection_unrunnable(gremlin, session)
        assert abstained is not None
        zapped = GremlinResult(gremlin=_gremlin('g002'), status=GremlinResultStatus.ZAPPED)

        score = MutationScore.from_results([zapped, abstained])

        assert (score.zapped, score.error, score.percentage) == (1, 1, 50.0)
