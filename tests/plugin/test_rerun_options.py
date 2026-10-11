"""Rerun options typed on the command line are carried into gremlin runs (refs #546)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _BaselineRecorder,
    _build_test_command,
    _own_session_key,
    _rerun_options_for,
    _skip_mutation_unless_baseline_is_green,
)
from pytest_gremlins.rerun_options import (
    baseline_rerun_warning,
    rerun_options_in,
)


@pytest.mark.small
class DescribeRerunOptionsIn:
    @pytest.mark.parametrize(
        ('args', 'expected'),
        [
            (['--reruns', '2'], ['--reruns=2']),
            (['--reruns=2'], ['--reruns=2']),
            (['--reruns', '3', '--reruns-delay', '0.5'], ['--reruns=3', '--reruns-delay=0.5']),
            (['--only-rerun', 'Timeout', '--only-rerun=Conn.*'], ['--only-rerun=Timeout', '--only-rerun=Conn.*']),
            (['--rerun-except', 'AssertionError'], ['--rerun-except=AssertionError']),
            (['--rerun-exclude-path', 'tests/slow'], ['--rerun-exclude-path=tests/slow']),
            (['--reruns-mode', 'append'], ['--reruns-mode=append']),
            (['--reruns-delay-backoff-factor=2'], ['--reruns-delay-backoff-factor=2']),
            (['--force-reruns', '1'], ['--force-reruns=1']),
            (['--max-suite-reruns', '10'], ['--max-suite-reruns=10']),
        ],
    )
    def it_keeps_each_rerun_option_with_its_value(self, args: list[str], expected: list[str]) -> None:
        assert rerun_options_in(args) == expected

    def it_ignores_every_other_argument(self) -> None:
        args = ['tests/', '-x', '--reruns', '2', '-k', 'flaky', '--gremlins', '-n', '2']

        assert rerun_options_in(args) == ['--reruns=2']

    @pytest.mark.parametrize('flag', ['--fail-on-flaky', '--rerun-show-tracebacks'])
    def it_leaves_out_options_that_change_the_exit_code_or_only_the_output(self, flag: str) -> None:
        assert rerun_options_in([flag, '--reruns', '1']) == ['--reruns=1']

    def it_does_not_take_the_next_argument_as_the_value_of_a_trailing_option(self) -> None:
        assert rerun_options_in(['--reruns']) == []

    def it_returns_nothing_when_no_rerun_option_was_typed(self) -> None:
        assert rerun_options_in(['--gremlins', 'tests/']) == []


@pytest.mark.small
class DescribeBuildTestCommandWithRerunOptions:
    def it_appends_the_rerun_options_to_the_bootstrap_command(self, tmp_path: Path) -> None:
        command = _build_test_command(tmp_path, '', rerun_options=['--reruns=2'])

        assert command[-1] == '--reruns=2'

    def it_appends_the_rerun_options_to_the_direct_pytest_command(self) -> None:
        command = _build_test_command(None, '', rerun_options=['--reruns=2', '--reruns-delay=1'])

        assert command[-2:] == ['--reruns=2', '--reruns-delay=1']

    def it_appends_nothing_by_default(self) -> None:
        assert not any(arg.startswith('--rerun') for arg in _build_test_command(None))


@pytest.mark.small
class DescribeBaselineRerunWarning:
    def it_returns_nothing_when_no_test_needed_a_rerun(self) -> None:
        assert baseline_rerun_warning(set()) is None

    def it_names_the_test_that_needed_a_rerun(self) -> None:
        warning = baseline_rerun_warning({'tests/test_a.py::test_flaky'})

        assert warning is not None
        assert 'tests/test_a.py::test_flaky' in warning
        assert warning.startswith('pytest-gremlins: warning:')

    def it_is_a_single_line_naming_every_test_in_sorted_order(self) -> None:
        warning = baseline_rerun_warning({'t::b', 't::a'})

        assert warning is not None
        assert '\n' not in warning
        assert warning.index('t::a') < warning.index('t::b')

    def it_summarizes_the_tests_beyond_the_first_ten(self) -> None:
        warning = baseline_rerun_warning({f't::test_{number:02d}' for number in range(13)})

        assert warning is not None
        assert 't::test_09' in warning
        assert 't::test_10' not in warning
        assert 'and 3 more' in warning


def _config(*, has_rerunfailures: bool, args: list[str]) -> Any:
    pluginmanager = SimpleNamespace(hasplugin=lambda name: has_rerunfailures and name == 'rerunfailures')
    return SimpleNamespace(pluginmanager=pluginmanager, invocation_params=SimpleNamespace(args=tuple(args)))


@pytest.mark.small
class DescribeRerunOptionsFor:
    def it_returns_the_command_line_rerun_options_when_pytest_rerunfailures_is_loaded(self) -> None:
        config = _config(has_rerunfailures=True, args=['--gremlins', '--reruns', '2'])

        assert _rerun_options_for(config) == ['--reruns=2']

    def it_returns_nothing_when_pytest_rerunfailures_is_not_loaded(self) -> None:
        config = _config(has_rerunfailures=False, args=['--reruns', '2'])

        assert _rerun_options_for(config) == []


def _report(node_id: str, outcome: str) -> pytest.TestReport:
    return pytest.TestReport(node_id, (node_id, 0, node_id), {}, outcome, None, 'call')  # type: ignore[arg-type]


def _recorder_for(gremlin_session: GremlinSession) -> _BaselineRecorder:
    config = SimpleNamespace(stash=pytest.Stash())
    config.stash[_own_session_key] = gremlin_session
    return _BaselineRecorder(config)  # type: ignore[arg-type]


@pytest.mark.small
class DescribeBaselineRerunRecording:
    def it_records_a_test_whose_report_has_the_rerun_outcome(self) -> None:
        gremlin_session = GremlinSession(enabled=True)

        _recorder_for(gremlin_session).pytest_runtest_logreport(_report('t::flaky', 'rerun'))

        assert gremlin_session.baseline_rerun_test_ids == {'t::flaky'}

    def it_does_not_count_a_rerun_as_a_failure(self) -> None:
        gremlin_session = GremlinSession(enabled=True)

        _recorder_for(gremlin_session).pytest_runtest_logreport(_report('t::flaky', 'rerun'))

        assert gremlin_session.baseline_failed_test_ids == set()

    def it_does_not_record_tests_that_passed_first_time(self) -> None:
        gremlin_session = GremlinSession(enabled=True)

        _recorder_for(gremlin_session).pytest_runtest_logreport(_report('t::steady', 'passed'))

        assert gremlin_session.baseline_rerun_test_ids == set()

    def it_prints_one_warning_for_a_test_that_was_rerun_several_times(self, capsys: pytest.CaptureFixture[str]) -> None:
        gremlin_session = GremlinSession(enabled=True)
        recorder = _recorder_for(gremlin_session)
        recorder.pytest_runtest_logreport(_report('t::flaky', 'rerun'))
        recorder.pytest_runtest_logreport(_report('t::flaky', 'rerun'))

        skipped = _skip_mutation_unless_baseline_is_green(gremlin_session, pytest.ExitCode.OK)

        assert skipped is False
        assert capsys.readouterr().err.count('t::flaky') == 1
