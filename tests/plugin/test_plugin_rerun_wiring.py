"""The plugin forwards rerun settings into gremlin runs and records baseline reruns (refs #546, #661)."""

from __future__ import annotations

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
    _rerun_ini_warnings_for,
    _rerun_options_for,
    _run_prescan_reporting_problems,
    _skip_mutation_unless_baseline_is_green,
)
from pytest_gremlins.rerun_options import unforwarded_rerun_key_warning

_ALL_RERUN_KEYS = ('reruns', 'reruns_delay', 'reruns_delay_backoff_factor', 'only_rerun', 'rerun_except')


def _resets(*keys: str) -> list[str]:
    return [f'--override-ini={key}=' for key in keys]


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


def _config(
    *,
    registered_plugin: str | None,
    args: list[str],
    ini: dict[str, str | list[str]] | None = None,
    inifilename: str | None = None,
    parsed_options: dict[str, object] | None = None,
) -> pytest.Config:
    pluginmanager = SimpleNamespace(hasplugin=lambda name: name == registered_plugin)
    ini_values = ini or {}
    fake = SimpleNamespace(
        pluginmanager=pluginmanager,
        invocation_params=SimpleNamespace(args=tuple(args), dir=Path()),
        rootdir=Path(),
        getini=lambda name: ini_values.get(name, [] if name in ('only_rerun', 'rerun_except') else ''),
        option=SimpleNamespace(inifilename=inifilename, **(parsed_options or {})),
    )
    return cast('pytest.Config', fake)


@pytest.mark.small
class DescribeRerunOptionsFor:
    def it_returns_the_command_line_rerun_options_when_pytest_rerunfailures_is_loaded(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=['--gremlins', '--reruns', '2'])

        assert _rerun_options_for(config) == ['--reruns=2']

    def it_returns_only_the_block_when_pytest_rerunfailures_is_not_loaded(self) -> None:
        config = _config(registered_plugin=None, args=['--reruns', '2'])

        assert _rerun_options_for(config) == ['-p', 'no:rerunfailures']

    def it_carries_the_rerun_options_when_the_plugin_is_registered_as_pytest_rerunfailures(self) -> None:
        # PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 with ``-p pytest_rerunfailures`` (or ``pytest_plugins`` in a
        # conftest) registers the plugin under its module name, not the entry-point name.
        config = _config(registered_plugin='pytest_rerunfailures', args=['--gremlins', '--reruns', '2'])

        assert _rerun_options_for(config) == ['--reruns=2']

    def it_forwards_rerun_ini_settings_as_ini_overrides_so_a_config_file_reaches_gremlin_runs(self) -> None:
        config = _config(
            registered_plugin='rerunfailures', args=['-c', 'ci.ini'], ini={'reruns': '2'}, inifilename='ci.ini'
        )

        assert _rerun_options_for(config) == [
            '--override-ini=reruns=2',
            '--override-ini=reruns_delay=',
            '--override-ini=reruns_delay_backoff_factor=',
            '--override-ini=only_rerun=',
            '--override-ini=rerun_except=',
        ]

    def it_leaves_out_an_ini_count_the_command_line_option_replaces(self) -> None:
        config = _config(
            registered_plugin='rerunfailures', args=['--reruns', '3'], ini={'reruns': '1'}, inifilename='ci.ini'
        )

        assert _rerun_options_for(config) == [
            '--override-ini=reruns_delay=',
            '--override-ini=reruns_delay_backoff_factor=',
            '--override-ini=only_rerun=',
            '--override-ini=rerun_except=',
            '--reruns=3',
        ]

    def it_does_not_repeat_an_ini_setting_the_command_line_already_overrides(self) -> None:
        config = _config(
            registered_plugin='rerunfailures', args=['-o', 'reruns=2'], ini={'reruns': '2'}, inifilename='ci.ini'
        )

        assert _rerun_options_for(config) == [
            '--override-ini=reruns_delay=',
            '--override-ini=reruns_delay_backoff_factor=',
            '--override-ini=only_rerun=',
            '--override-ini=rerun_except=',
            '--override-ini=reruns=2',
        ]

    def it_forwards_no_ini_settings_when_pytest_rerunfailures_is_not_loaded(self) -> None:
        config = _config(registered_plugin=None, args=[], ini={'reruns': '2'})

        assert _rerun_options_for(config) == ['-p', 'no:rerunfailures']


@pytest.mark.small
class DescribeRerunIniSettingsWithoutAConfigFileOption:
    @pytest.mark.parametrize('inifilename', [None, ''])
    def it_forwards_no_ini_settings_because_the_gremlin_runs_read_the_project_config(
        self, inifilename: str | None
    ) -> None:
        config = _config(registered_plugin='rerunfailures', args=[], ini={'reruns': '2'}, inifilename=inifilename)

        assert _rerun_options_for(config) == []

    def it_still_forwards_the_rerun_options_typed_on_the_command_line(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=['--reruns', '3'], ini={'reruns': '1'})

        assert _rerun_options_for(config) == ['--reruns=3']

    def it_warns_about_nothing(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=[], ini={'rerun_except': ['xyz ']})

        assert _rerun_ini_warnings_for(config) == []


@pytest.mark.small
class DescribeRerunIniSettingsUnderAConfigFileOption:
    def it_leaves_out_a_list_setting_pytest_would_change_and_forwards_the_rest(self) -> None:
        ini: dict[str, str | list[str]] = {'reruns': '2', 'rerun_except': ['xyz '], 'only_rerun': ['Timeout']}
        config = _config(registered_plugin='rerunfailures', args=[], ini=ini, inifilename='ci.toml')

        assert _rerun_options_for(config) == [
            '--override-ini=reruns=2',
            '--override-ini=only_rerun=Timeout',
            '--override-ini=reruns_delay=',
            '--override-ini=reruns_delay_backoff_factor=',
            '--override-ini=rerun_except=',
        ]

    def it_resets_a_list_setting_the_config_file_leaves_unset_so_the_project_file_cannot_fill_it_in(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=[], ini={'reruns': '2'}, inifilename='ci.ini')

        assert _rerun_options_for(config) == [
            '--override-ini=reruns=2',
            '--override-ini=reruns_delay=',
            '--override-ini=reruns_delay_backoff_factor=',
            '--override-ini=only_rerun=',
            '--override-ini=rerun_except=',
        ]

    def it_puts_the_resets_before_the_command_line_so_the_command_line_wins(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=['--only-rerun', 'Timeout'], inifilename='ci.ini')

        assert _rerun_options_for(config) == [
            '--override-ini=reruns=',
            '--override-ini=reruns_delay=',
            '--override-ini=reruns_delay_backoff_factor=',
            '--override-ini=rerun_except=',
            '--only-rerun=Timeout',
        ]

    def it_does_not_warn_about_a_key_a_command_line_option_replaces(self) -> None:
        config = _config(
            registered_plugin='rerunfailures',
            args=['--rerun-except', 'safe'],
            ini={'rerun_except': ['xyz ']},
            inifilename='ci.toml',
        )

        assert _rerun_ini_warnings_for(config) == []

    def it_warns_once_per_left_out_key(self) -> None:
        ini: dict[str, str | list[str]] = {'rerun_except': [' a'], 'only_rerun': ['b\r']}
        config = _config(registered_plugin='rerunfailures', args=[], ini=ini, inifilename='ci.toml')

        warnings = _rerun_ini_warnings_for(config)

        assert warnings == [unforwarded_rerun_key_warning('only_rerun'), unforwarded_rerun_key_warning('rerun_except')]

    def it_does_not_warn_about_a_key_the_command_line_overrides(self) -> None:
        config = _config(
            registered_plugin='rerunfailures',
            args=['-o', 'rerun_except=safe'],
            ini={'rerun_except': ['xyz ']},
            inifilename='ci.toml',
        )

        assert _rerun_ini_warnings_for(config) == []

    @pytest.mark.parametrize('key', ['only_rerun', 'rerun_except'])
    def it_does_not_warn_about_a_key_a_parsed_option_replaces_from_addopts(self, key: str) -> None:
        config = _config(
            registered_plugin='rerunfailures',
            args=['-c', 'ci.toml'],
            ini={key: ['xyz ']},
            inifilename='ci.toml',
            parsed_options={key: ['flaky']},
        )

        assert _rerun_ini_warnings_for(config) == []

    def it_does_not_reset_or_forward_a_key_a_parsed_option_sets_from_addopts(self) -> None:
        config = _config(
            registered_plugin='rerunfailures',
            args=['-c', 'ci.toml'],
            ini={'reruns': '2', 'only_rerun': ['xyz ']},
            inifilename='ci.toml',
            parsed_options={'only_rerun': ['flaky'], 'reruns': 3},
        )

        assert _rerun_options_for(config) == _resets('reruns_delay', 'reruns_delay_backoff_factor', 'rerun_except')

    def it_resets_every_unset_key_so_the_project_file_fills_in_none(self) -> None:
        config = _config(registered_plugin='rerunfailures', args=['-c', 'ci.ini'], inifilename='ci.ini')

        assert _rerun_options_for(config) == _resets(*_ALL_RERUN_KEYS)

    def it_does_not_warn_when_pytest_rerunfailures_is_not_loaded(self) -> None:
        config = _config(registered_plugin=None, args=[], ini={'rerun_except': ['xyz ']}, inifilename='ci.toml')

        assert _rerun_ini_warnings_for(config) == []


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
