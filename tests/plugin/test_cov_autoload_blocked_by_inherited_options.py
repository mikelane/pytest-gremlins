"""``--no-cov`` reaches gremlin runs whose inherited options block pytest-cov (issue #654, adversarial QA run 2).

The session's own command line is not passed on to gremlin runs, but its ``addopts`` and ``PYTEST_ADDOPTS`` are.
When those block pytest-cov (``-p no:pytest_cov``) and the command line loads it again (``-p pytest_cov``), the
session has ``--no-cov`` while its autoloading gremlin runs do not, so every gremlin errors with
``unrecognized arguments: --no-cov``.
"""

from __future__ import annotations

import pytest
from rerun_samples import (
    SAMPLE,
    verdicts,
)

STRONG_TEST = """
from sample import classify


def test_boundary():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""
SESSION_ARGS = ('--gremlins', '--gremlin-targets=sample.py', '--gremlin-operators=comparison', '-p', 'gremlins')


@pytest.fixture
def autoload_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
    monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
    monkeypatch.delenv('PYTEST_PLUGINS', raising=False)


def _assert_gremlins_ran_cleanly(result: pytest.RunResult) -> None:
    output = result.stdout.str() + result.stderr.str()
    assert 'unrecognized arguments' not in output
    counted = verdicts(output)
    assert counted['Error'] == 0
    assert counted['Zapped'] > 0


@pytest.mark.medium
@pytest.mark.usefixtures('autoload_enabled')
class DescribeGremlinRunsWhoseInheritedOptionsBlockPytestCov:
    def it_zaps_when_addopts_blocks_pytest_cov_and_the_command_line_loads_it(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=STRONG_TEST)
        pytester_with_markers.makeini('[pytest]\naddopts = -p no:pytest_cov\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov')

        _assert_gremlins_ran_cleanly(result)

    def it_zaps_when_pytest_addopts_blocks_pytest_cov_and_the_command_line_loads_it(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p no:pytest_cov')
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=STRONG_TEST)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov')

        _assert_gremlins_ran_cleanly(result)
