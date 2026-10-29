"""``--no-cov`` is forwarded to gremlin runs only when they have pytest-cov loaded (issue #654).

Importable is not loaded: with pytest's plugin autoload disabled, an installed pytest-cov registers neither
itself nor ``--no-cov``, so forwarding the flag made every gremlin run exit with ``unrecognized arguments``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from cov_samples import (
    SESSION_ARGS,
    assert_gremlins_ran_cleanly,
    write_project,
)
import pytest

from pytest_gremlins.plugin import (
    _build_test_command,
    _pytest_cov_options_for,
)

AUTOLOAD_OFF_FLAG = '--disable-plugin-autoload'


def _config(
    *,
    loaded: tuple[str, ...] = (),
    option_names: tuple[str, ...] = ('no_cov',),
    autoload_flag_in_addopts: bool = False,
) -> Any:
    """Return a config whose plugin manager has registered exactly the ``loaded`` plugin names."""
    manager = MagicMock(spec=pytest.PytestPluginManager)
    manager.hasplugin.side_effect = lambda name: name in loaded
    config = MagicMock(spec=pytest.Config)
    config.pluginmanager = manager
    config.option = SimpleNamespace(**dict.fromkeys(option_names, False))
    config.getini.return_value = [AUTOLOAD_OFF_FLAG] if autoload_flag_in_addopts else []
    config.rootpath = None
    return config


@pytest.fixture
def autoload_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
    monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
    monkeypatch.delenv('PYTEST_PLUGINS', raising=False)


@pytest.fixture
def autoload_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
    monkeypatch.delenv('PYTEST_PLUGINS', raising=False)


@pytest.mark.small
class DescribeBuildTestCommandPytestCovOptions:
    def it_appends_the_given_pytest_cov_options(self) -> None:
        command = _build_test_command(None, pytest_cov_options=['-p', 'pytest_cov', '--no-cov'])

        assert command[-3:] == ['-p', 'pytest_cov', '--no-cov']

    def it_adds_no_pytest_cov_option_by_default(self) -> None:
        command = _build_test_command(None)

        assert '--no-cov' not in command
        assert 'pytest_cov' not in command


@pytest.mark.small
@pytest.mark.usefixtures('autoload_enabled')
class DescribePytestCovOptionsWithAutoloadOn:
    def it_loads_the_entry_point_name_so_an_inherited_block_cannot_hide_the_option(self) -> None:
        assert _pytest_cov_options_for(_config(loaded=('pytest_cov',)), []) == ['-p', 'pytest_cov', '--no-cov']

    def it_forwards_only_no_cov_for_the_module_name_which_would_register_twice(self) -> None:
        assert _pytest_cov_options_for(_config(loaded=('pytest_cov.plugin',)), []) == ['--no-cov']

    def it_forwards_nothing_when_the_session_lacks_the_option(self) -> None:
        assert _pytest_cov_options_for(_config(option_names=()), []) == []


@pytest.mark.small
@pytest.mark.usefixtures('autoload_disabled')
class DescribePytestCovOptionsWithAutoloadOff:
    @pytest.mark.parametrize('name', ['pytest_cov', 'pytest_cov.plugin'])
    def it_loads_the_plugin_under_the_name_the_session_registered(self, name: str) -> None:
        assert _pytest_cov_options_for(_config(loaded=(name,)), []) == ['-p', name, '--no-cov']

    def it_forwards_nothing_when_the_session_lacks_the_option(self) -> None:
        assert _pytest_cov_options_for(_config(option_names=()), []) == []

    def it_forwards_nothing_when_the_plugin_is_registered_under_an_unknown_name(self) -> None:
        assert _pytest_cov_options_for(_config(loaded=('other',)), []) == []

    def it_loads_the_plugin_by_its_module_name_when_the_bare_package_holds_the_entry_point_name(self) -> None:
        config = _config(loaded=('pytest_cov', 'pytest_cov.plugin'))

        assert _pytest_cov_options_for(config, []) == ['-p', 'pytest_cov.plugin', '--no-cov']


@pytest.mark.small
@pytest.mark.usefixtures('autoload_enabled')
class DescribePytestCovOptionsWithAutoloadOffByTheRunsInputs:
    def it_loads_the_plugin_when_the_flag_comes_from_addopts(self) -> None:
        config = _config(loaded=('pytest_cov',), autoload_flag_in_addopts=True)

        assert _pytest_cov_options_for(config, []) == ['-p', 'pytest_cov', '--no-cov']

    def it_loads_the_plugin_when_the_rerun_options_forward_the_flag(self) -> None:
        config = _config(loaded=('pytest_cov',))

        assert _pytest_cov_options_for(config, [AUTOLOAD_OFF_FLAG, '-p', 'pytest_rerunfailures']) == [
            '-p',
            'pytest_cov',
            '--no-cov',
        ]

    def it_loads_the_plugin_when_the_flag_comes_from_pytest_addopts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', AUTOLOAD_OFF_FLAG)

        assert _pytest_cov_options_for(_config(loaded=('pytest_cov',)), []) == ['-p', 'pytest_cov', '--no-cov']


@pytest.mark.medium
@pytest.mark.usefixtures('autoload_disabled')
class DescribeGremlinRunsWithAutoloadDisabled:
    def it_zaps_without_forwarding_no_cov_when_pytest_cov_is_not_loaded(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        assert_gremlins_ran_cleanly(result)

    def it_keeps_pytest_cov_when_it_is_loaded_with_p_on_the_command_line(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov')

        assert_gremlins_ran_cleanly(result)

    def it_registers_pytest_cov_once_when_addopts_loads_it_by_module_path(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)
        pytester_with_markers.makeini('[pytest]\naddopts = -p pytest_cov.plugin\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        assert_gremlins_ran_cleanly(result)

    def it_registers_pytest_cov_once_when_pytest_plugins_also_names_the_bare_package(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_PLUGINS', 'pytest_cov')
        write_project(pytester_with_markers)
        pytester_with_markers.makeini('[pytest]\naddopts = -p pytest_cov.plugin\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        assert_gremlins_ran_cleanly(result)


@pytest.mark.medium
@pytest.mark.usefixtures('autoload_enabled')
class DescribeGremlinRunsWithTheDisableFlagInPytestAddopts:
    def it_zaps_when_pytest_addopts_disables_autoload_and_the_command_line_loads_pytest_cov(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', AUTOLOAD_OFF_FLAG)
        write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov')

        assert_gremlins_ran_cleanly(result)
