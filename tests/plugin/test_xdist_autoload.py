"""``-n 0`` is forwarded to gremlin runs only when they load pytest-xdist themselves (issue #668).

With pytest's plugin autoload disabled, gremlin runs register xdist only if they are told to, so forwarding
``-n 0`` for a session that loaded xdist with ``-p xdist`` made every gremlin run exit with ``unrecognized
arguments`` and score ERROR.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from cov_samples import (  # type: ignore[import-not-found]
    SESSION_ARGS,
    assert_gremlins_ran_cleanly,
    write_project,
)
import pytest

from pytest_gremlins.plugin import (
    _xdist_options_for,
)
from pytest_gremlins.verdicts import (
    _build_test_command,
)

AUTOLOAD_OFF_FLAG = '--disable-plugin-autoload'
NO_XDIST: tuple[list[str], bool] = ([], False)


def _config(*, loaded: tuple[str, ...] = (), autoload_flag_in_addopts: bool = False) -> Any:
    """Return a config whose plugin manager has registered exactly the ``loaded`` plugin names."""
    manager = MagicMock(spec=pytest.PytestPluginManager)
    manager.hasplugin.side_effect = lambda name: name in loaded
    config = MagicMock(spec=pytest.Config)
    config.pluginmanager = manager
    config.option = SimpleNamespace()
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
class DescribeBuildTestCommandXdistLoader:
    def it_places_the_loader_options_before_n_zero(self) -> None:
        command = _build_test_command(None, xdist_loaded=True, xdist_loader_options=['-p', 'xdist'])

        assert command[-4:] == ['-p', 'xdist', '-n', '0']

    def it_adds_no_loader_by_default(self) -> None:
        command = _build_test_command(None, xdist_loaded=True)

        assert command[-2:] == ['-n', '0']
        assert 'xdist' not in command


@pytest.mark.small
@pytest.mark.usefixtures('autoload_enabled')
class DescribeXdistOptionsWithAutoloadOn:
    def it_forwards_n_zero_without_a_loader_when_xdist_is_loaded(self) -> None:
        assert _xdist_options_for(_config(loaded=('xdist',)), []) == ([], True)

    def it_forwards_nothing_when_xdist_is_not_loaded(self) -> None:
        assert _xdist_options_for(_config(), []) == NO_XDIST

    def it_keeps_the_existing_behavior_for_the_module_name_alone(self) -> None:
        assert _xdist_options_for(_config(loaded=('xdist.plugin',)), []) == ([], False)


@pytest.mark.small
@pytest.mark.usefixtures('autoload_disabled')
class DescribeXdistOptionsWithAutoloadOff:
    @pytest.mark.parametrize('name', ['xdist', 'xdist.plugin'])
    def it_loads_xdist_under_the_name_the_session_registered(self, name: str) -> None:
        assert _xdist_options_for(_config(loaded=(name,)), []) == (['-p', name], True)

    def it_forwards_nothing_when_xdist_is_not_loaded(self) -> None:
        assert _xdist_options_for(_config(), []) == NO_XDIST

    def it_forwards_nothing_when_xdist_is_registered_under_an_unknown_name(self) -> None:
        assert _xdist_options_for(_config(loaded=('other',)), []) == NO_XDIST

    def it_loads_the_module_name_when_the_bare_package_holds_the_entry_point_name(self) -> None:
        config = _config(loaded=('xdist', 'xdist.plugin'))

        assert _xdist_options_for(config, []) == (['-p', 'xdist.plugin'], True)


@pytest.mark.small
@pytest.mark.usefixtures('autoload_enabled')
class DescribeXdistOptionsWithAutoloadOffByTheRunsInputs:
    def it_loads_xdist_when_the_flag_comes_from_addopts(self) -> None:
        config = _config(loaded=('xdist',), autoload_flag_in_addopts=True)

        assert _xdist_options_for(config, []) == (['-p', 'xdist'], True)

    def it_loads_xdist_when_the_rerun_options_forward_the_flag(self) -> None:
        assert _xdist_options_for(_config(loaded=('xdist',)), [AUTOLOAD_OFF_FLAG]) == (['-p', 'xdist'], True)

    def it_loads_xdist_when_the_flag_comes_from_pytest_addopts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', AUTOLOAD_OFF_FLAG)

        assert _xdist_options_for(_config(loaded=('xdist',)), []) == (['-p', 'xdist'], True)


@pytest.mark.small
@pytest.mark.usefixtures('autoload_enabled')
class DescribeXdistOptionsWithAnInheritedBlock:
    @pytest.mark.parametrize('block', ['-p no:xdist', '-pno:xdist'])
    def it_loads_xdist_again_when_addopts_blocks_it(self, block: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', block)

        assert _xdist_options_for(_config(loaded=('xdist',)), []) == (['-p', 'xdist'], True)

    def it_forwards_no_loader_for_no_xdist_plugin_which_does_not_block_the_autoloaded_entry_point(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # pytest blocks the ``xdist.plugin`` module name only; autoload still registers the ``xdist`` entry point.
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p no:xdist.plugin')

        assert _xdist_options_for(_config(loaded=('xdist',)), []) == ([], True)

    @pytest.mark.parametrize('lift', ['-p no:xdist -p xdist', '-pno:xdist -pxdist'])
    def it_forwards_no_loader_when_a_later_inherited_p_xdist_lifts_the_block(
        self, lift: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # e.g. ini ``addopts = -p no:xdist`` with CI exporting ``PYTEST_ADDOPTS='-p xdist'``.
        monkeypatch.setenv('PYTEST_ADDOPTS', lift)

        assert _xdist_options_for(_config(loaded=('xdist',)), []) == ([], True)

    def it_forwards_nothing_when_a_block_hides_xdist_from_the_session_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p no:xdist')

        assert _xdist_options_for(_config(), []) == NO_XDIST


@pytest.mark.medium
@pytest.mark.usefixtures('autoload_disabled')
class DescribeGremlinRunsWithAutoloadDisabledAndXdist:
    @pytest.mark.parametrize('spelling', ['xdist', 'xdist.plugin'])
    def it_zaps_when_xdist_is_loaded_with_p_on_the_command_line(
        self, pytester_with_markers: pytest.Pytester, spelling: str
    ) -> None:
        write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', spelling)

        assert_gremlins_ran_cleanly(result)

    def it_zaps_when_addopts_loads_xdist(self, pytester_with_markers: pytest.Pytester) -> None:
        write_project(pytester_with_markers)
        pytester_with_markers.makeini('[pytest]\naddopts = -p xdist\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        assert_gremlins_ran_cleanly(result)

    def it_zaps_when_xdist_is_not_loaded(self, pytester_with_markers: pytest.Pytester) -> None:
        write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        assert_gremlins_ran_cleanly(result)
