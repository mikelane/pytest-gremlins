"""Adversarial QA run 3 (issue #654): the session loads pytest-cov by its module name while inherited options block it.

With autoload on, ``-p no:pytest_cov`` in ``addopts`` or ``PYTEST_ADDOPTS`` blocks the entry point in every gremlin run.
When the session loads pytest-cov again by its module name (``-p pytest_cov.plugin`` on the command line, or
``PYTEST_PLUGINS=pytest_cov.plugin``), only ``pytest_cov.plugin`` is registered, so the session has ``--no-cov`` and
the gremlin runs are given the bare flag.
"""

from __future__ import annotations

from cov_samples import (  # type: ignore[import-not-found]
    SESSION_ARGS,
    assert_gremlins_ran_cleanly,
    write_project,
)
import pytest


@pytest.fixture
def autoload_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
    monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
    monkeypatch.delenv('PYTEST_PLUGINS', raising=False)


@pytest.mark.medium
@pytest.mark.usefixtures('autoload_enabled')
class DescribeGremlinRunsWhenTheSessionLoadsPytestCovByModuleNamePastAnInheritedBlock:
    def it_zaps_when_addopts_blocks_pytest_cov_and_the_command_line_loads_the_module(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)
        pytester_with_markers.makeini('[pytest]\naddopts = -p no:pytest_cov\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov.plugin')

        assert_gremlins_ran_cleanly(result)

    def it_zaps_when_pytest_addopts_blocks_pytest_cov_and_the_command_line_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p no:pytest_cov')
        write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov.plugin')

        assert_gremlins_ran_cleanly(result)

    def it_zaps_when_addopts_blocks_pytest_cov_and_pytest_plugins_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_PLUGINS', 'pytest_cov.plugin')
        write_project(pytester_with_markers)
        pytester_with_markers.makeini('[pytest]\naddopts = -p no:pytest_cov\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        assert_gremlins_ran_cleanly(result)

    @pytest.mark.parametrize('extra_args', [(), ('--cov=.',)])
    def it_zaps_without_registering_twice_when_only_the_command_line_blocks_and_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, extra_args: tuple[str, ...]
    ) -> None:
        write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(
            *SESSION_ARGS, '-p', 'no:pytest_cov', '-p', 'pytest_cov.plugin', *extra_args
        )

        assert_gremlins_ran_cleanly(result)
