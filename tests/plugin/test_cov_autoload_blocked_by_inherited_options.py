"""``--no-cov`` reaches gremlin runs whose inherited options block pytest-cov (issue #654, adversarial QA run 2).

The session's own command line is not passed on to gremlin runs, but its ``addopts`` and ``PYTEST_ADDOPTS`` are.
When those block pytest-cov (``-p no:pytest_cov``) and the command line loads it again (``-p pytest_cov``), the
session has ``--no-cov`` while its autoloading gremlin runs do not, so every gremlin errors with
``unrecognized arguments: --no-cov``.
"""

from __future__ import annotations

from cov_samples import (
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
class DescribeGremlinRunsWhoseInheritedOptionsBlockPytestCov:
    def it_zaps_when_addopts_blocks_pytest_cov_and_the_command_line_loads_it(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)
        pytester_with_markers.makeini('[pytest]\naddopts = -p no:pytest_cov\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov')

        assert_gremlins_ran_cleanly(result)

    def it_zaps_when_pytest_addopts_blocks_pytest_cov_and_the_command_line_loads_it(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p no:pytest_cov')
        write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov')

        assert_gremlins_ran_cleanly(result)
