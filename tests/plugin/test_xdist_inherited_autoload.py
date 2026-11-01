"""Gremlin runs get a working ``-n 0`` however the session and its gremlin runs differ in loading xdist (issue #685).

The session's own command line is not passed to gremlin runs, so a plugin the command line loads (or unblocks)
can be missing from them.  Forwarding ``-n 0`` then made every gremlin run exit with ``unrecognized arguments``.
"""

from __future__ import annotations

from cov_samples import (  # type: ignore[import-not-found]
    SESSION_ARGS,
    assert_gremlins_ran_cleanly,
    write_project,
)
import pytest


@pytest.fixture(autouse=True)
def autoload_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
    monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
    monkeypatch.delenv('PYTEST_PLUGINS', raising=False)


@pytest.mark.medium
class DescribeGremlinRunsThatInheritAutoloadOff:
    def it_zaps_when_addopts_disables_autoload_and_the_command_line_loads_xdist(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)
        pytester_with_markers.makeini('[pytest]\naddopts = --disable-plugin-autoload\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'xdist')

        assert_gremlins_ran_cleanly(result)


@pytest.mark.medium
class DescribeGremlinRunsThatInheritAnXdistBlock:
    def it_zaps_when_addopts_blocks_xdist_and_the_command_line_loads_it_again(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)
        pytester_with_markers.makeini('[pytest]\naddopts = -p no:xdist\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'xdist')

        assert_gremlins_ran_cleanly(result)

    def it_zaps_when_pytest_addopts_blocks_xdist_and_the_command_line_loads_it_again(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_project(pytester_with_markers)
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p no:xdist')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'xdist')

        assert_gremlins_ran_cleanly(result)


@pytest.mark.medium
class DescribeGremlinRunsWithBareXdistInPytestPlugins:
    def it_zaps_when_pytest_plugins_names_xdist(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_project(pytester_with_markers)
        monkeypatch.setenv('PYTEST_PLUGINS', 'xdist')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        assert_gremlins_ran_cleanly(result)

    def it_zaps_when_pytest_plugins_names_xdist_and_the_command_line_disables_autoload(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_project(pytester_with_markers)
        monkeypatch.setenv('PYTEST_PLUGINS', 'xdist')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '--disable-plugin-autoload')

        assert_gremlins_ran_cleanly(result)

    def it_zaps_when_pytest_plugins_names_xdist_and_autoload_is_disabled_by_the_environment(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_project(pytester_with_markers)
        monkeypatch.setenv('PYTEST_PLUGINS', 'xdist')
        monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        assert_gremlins_ran_cleanly(result)
