"""Rerun options typed on the command line are carried into gremlin runs (refs #546)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.plugin import (
    GremlinSession,
    _BaselineRecorder,
    _build_test_command,
    _own_session_key,
    _rerun_options_for,
    _run_prescan_reporting_problems,
    _skip_mutation_unless_baseline_is_green,
)
from pytest_gremlins.rerun_options import (
    baseline_rerun_warning,
    rerun_ini_overrides,
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

    @pytest.mark.parametrize(
        'args',
        [
            ['-o', 'reruns=2'],
            ['-o=reruns=2'],
            ['-oreruns=2'],
            ['--override-ini', 'reruns=2'],
            ['--override-ini=reruns=2'],
        ],
    )
    def it_keeps_the_rerun_ini_settings_overridden_on_the_command_line(self, args: list[str]) -> None:
        assert rerun_options_in(args) == ['--override-ini=reruns=2']

    @pytest.mark.parametrize(
        'setting', ['only_rerun=ConnectionError', 'rerun_except=AssertionError', 'reruns_delay_backoff_factor=2']
    )
    def it_carries_every_ini_key_pytest_rerunfailures_reads(self, setting: str) -> None:
        assert rerun_options_in(['-o', setting]) == [f'--override-ini={setting}']

    def it_carries_an_ini_override_written_after_a_short_flag(self) -> None:
        # argparse reads ``-qo reruns=2`` as ``-q -o reruns=2``.
        assert rerun_options_in(['-qo', 'reruns=2']) == ['--override-ini=reruns=2']

    def it_carries_an_ini_override_written_as_a_clustered_flag_with_an_equals_sign(self) -> None:
        # argparse reads ``-qo=reruns=2`` as ``-q -o reruns=2``, just as it reads ``-o=reruns=2`` as ``-o reruns=2``.
        assert rerun_options_in(['-qo=reruns=2']) == ['--override-ini=reruns=2']

    def it_keeps_the_rerun_delay_ini_override_and_drops_unrelated_ones(self) -> None:
        args = ['-o', 'log_level=DEBUG', '-o', 'reruns_delay=0.5', '-o', 'rerunsx=1']

        assert rerun_options_in(args) == ['--override-ini=reruns_delay=0.5']

    def it_does_not_take_a_trailing_override_ini_option_as_a_rerun_setting(self) -> None:
        assert rerun_options_in(['-o']) == []

    def it_does_not_read_an_o_clustered_after_a_flag_that_takes_a_value_as_an_ini_override(self) -> None:
        # argparse reads ``-ko reruns=2`` as ``-k o`` followed by the positional ``reruns=2``.
        assert rerun_options_in(['-ko', 'reruns=2']) == []

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

    def it_names_exactly_ten_tests_without_a_summary(self) -> None:
        warning = baseline_rerun_warning({f't::test_{number:02d}' for number in range(10)})

        assert warning is not None
        assert 't::test_09' in warning
        assert 'more' not in warning

    def it_states_how_many_baseline_tests_needed_a_rerun(self) -> None:
        warning = baseline_rerun_warning({f't::test_{number:02d}' for number in range(13)})

        assert warning is not None
        assert '13 baseline test(s) needed a rerun' in warning


def _config(
    *, registered_plugin: str | None, args: list[str], ini: dict[str, str | list[str]] | None = None
) -> pytest.Config:
    pluginmanager = SimpleNamespace(hasplugin=lambda name: name == registered_plugin)
    ini_values = ini or {}
    fake = SimpleNamespace(
        pluginmanager=pluginmanager,
        invocation_params=SimpleNamespace(args=tuple(args), dir=Path()),
        getini=lambda name: ini_values.get(name, [] if name in ('only_rerun', 'rerun_except') else ''),
    )
    return cast('pytest.Config', fake)


@pytest.mark.small
class DescribeRerunOptionsFor:
    def it_returns_the_command_line_rerun_options_when_pytest_rerunfailures_is_loaded(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=['--gremlins', '--reruns', '2'])

        assert _rerun_options_for(config) == ['--reruns=2']

    def it_returns_nothing_when_pytest_rerunfailures_is_not_loaded(self) -> None:
        config = _config(registered_plugin=None, args=['--reruns', '2'])

        assert _rerun_options_for(config) == []

    def it_carries_the_rerun_options_when_the_plugin_is_registered_as_pytest_rerunfailures(self) -> None:
        # PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 with ``-p pytest_rerunfailures`` (or ``pytest_plugins`` in a
        # conftest) registers the plugin under its module name, not the entry-point name.
        config = _config(registered_plugin='pytest_rerunfailures', args=['--gremlins', '--reruns', '2'])

        assert _rerun_options_for(config) == ['--reruns=2']

    def it_forwards_rerun_ini_settings_as_ini_overrides_so_a_config_file_reaches_gremlin_runs(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=['-c', 'ci.ini'], ini={'reruns': '2'})

        assert _rerun_options_for(config) == ['--override-ini=reruns=2']

    def it_puts_the_command_line_after_the_ini_settings_so_it_wins(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=['--reruns', '3'], ini={'reruns': '1'})

        assert _rerun_options_for(config) == ['--override-ini=reruns=1', '--reruns=3']

    def it_does_not_repeat_an_ini_setting_the_command_line_already_overrides(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=['-o', 'reruns=2'], ini={'reruns': '2'})

        assert _rerun_options_for(config) == ['--override-ini=reruns=2']

    def it_forwards_no_ini_settings_when_pytest_rerunfailures_is_not_loaded(self) -> None:
        config = _config(registered_plugin=None, args=[], ini={'reruns': '2'})

        assert _rerun_options_for(config) == []


@pytest.mark.small
class DescribeRerunIniOverrides:
    @staticmethod
    def _reader(values: dict[str, str | list[str]]) -> Callable[[str], object]:
        return lambda key: values.get(key, [] if key in ('only_rerun', 'rerun_except') else '')

    def it_returns_nothing_when_no_rerun_ini_key_is_set(self) -> None:
        assert rerun_ini_overrides(self._reader({})) == []

    def it_forwards_each_set_key_as_an_ini_override_in_a_fixed_order(self) -> None:
        values = {'reruns_delay': '0.5', 'reruns': '2', 'reruns_delay_backoff_factor': '2'}

        assert rerun_ini_overrides(self._reader(values)) == [
            '--override-ini=reruns=2',
            '--override-ini=reruns_delay=0.5',
            '--override-ini=reruns_delay_backoff_factor=2',
        ]

    def it_joins_a_list_setting_with_newlines_so_pytest_parses_the_same_list(self) -> None:
        values: dict[str, str | list[str]] = {
            'only_rerun': ['no such failure', 'AssertionError'],
            'rerun_except': ['X'],
        }

        assert rerun_ini_overrides(self._reader(values)) == [
            '--override-ini=only_rerun=no such failure\nAssertionError',
            '--override-ini=rerun_except=X',
        ]

    def it_skips_a_key_the_installed_pytest_rerunfailures_does_not_register(self) -> None:
        def read_ini(key: str) -> object:
            if key != 'reruns':
                raise ValueError(f'unknown configuration value: {key!r}')
            return '2'

        assert rerun_ini_overrides(read_ini) == ['--override-ini=reruns=2']

    def it_skips_a_key_pytest_cannot_read_as_a_string_and_forwards_the_rest(self) -> None:
        def read_ini(key: str) -> object:
            if key == 'reruns':
                raise TypeError("expected str, got int for 'reruns'")
            return '0.5' if key == 'reruns_delay' else ''

        assert rerun_ini_overrides(read_ini) == ['--override-ini=reruns_delay=0.5']

    def it_keeps_a_zero_count_from_a_toml_file_so_it_still_overrides_the_gremlin_runs_own_config(self) -> None:
        assert rerun_ini_overrides(self._reader({'reruns': 0})) == ['--override-ini=reruns=0']  # type: ignore[dict-item]

    def it_converts_a_non_string_value_from_a_toml_file_to_text(self) -> None:
        assert rerun_ini_overrides(self._reader({'reruns': 2})) == ['--override-ini=reruns=2']  # type: ignore[dict-item]


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


@pytest.mark.medium
class DescribeCoveragePrescanRerunOptions:
    @pytest.mark.filterwarnings('ignore::UserWarning')
    def it_reruns_flaky_tests_in_the_prescan_like_the_baseline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A test that flakes before it reaches the code under test records no coverage on its failed
        # attempt.  Without the reruns the baseline used, it drops out of the coverage map and every
        # mutant only it could catch is judged by weaker tests alone (a false survivor).
        prescan_commands: list[list[str]] = []
        monkeypatch.setattr(plugin, '_launch_prescan', lambda command, *_args: prescan_commands.append(command))
        gremlin_session = GremlinSession(enabled=True, rerun_options=['--reruns=2'])

        _run_prescan_reporting_problems(['test_a.py::test_flaky'], tmp_path, gremlin_session, coverage_include=None)

        assert '--reruns=2' in prescan_commands[0]
