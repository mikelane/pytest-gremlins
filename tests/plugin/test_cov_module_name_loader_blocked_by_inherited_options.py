"""Adversarial QA run 3 (issue #654): the session loads pytest-cov by its module name while inherited options block it.

With autoload on, ``-p no:pytest_cov`` in ``addopts`` or ``PYTEST_ADDOPTS`` blocks the entry point in every gremlin run.
When the session loads pytest-cov again by its module name (``-p pytest_cov.plugin`` on the command line, or
``PYTEST_PLUGINS=pytest_cov.plugin``), only ``pytest_cov.plugin`` is registered, so the session has ``--no-cov`` and
the gremlin runs are given the bare flag.
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
class DescribeGremlinRunsWhenTheSessionLoadsPytestCovByModuleNamePastAnInheritedBlock:
    def it_zaps_when_addopts_blocks_pytest_cov_and_the_command_line_loads_the_module(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=STRONG_TEST)
        pytester_with_markers.makeini('[pytest]\naddopts = -p no:pytest_cov\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov.plugin')

        _assert_gremlins_ran_cleanly(result)

    def it_zaps_when_pytest_addopts_blocks_pytest_cov_and_the_command_line_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p no:pytest_cov')
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=STRONG_TEST)

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'pytest_cov.plugin')

        _assert_gremlins_ran_cleanly(result)

    def it_zaps_when_addopts_blocks_pytest_cov_and_pytest_plugins_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTEST_PLUGINS', 'pytest_cov.plugin')
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=STRONG_TEST)
        pytester_with_markers.makeini('[pytest]\naddopts = -p no:pytest_cov\n')

        result = pytester_with_markers.runpytest_subprocess(*SESSION_ARGS)

        _assert_gremlins_ran_cleanly(result)

    @pytest.mark.parametrize('extra_args', [(), ('--cov=.',)])
    def it_zaps_without_registering_twice_when_only_the_command_line_blocks_and_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, extra_args: tuple[str, ...]
    ) -> None:
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=STRONG_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            *SESSION_ARGS, '-p', 'no:pytest_cov', '-p', 'pytest_cov.plugin', *extra_args
        )

        _assert_gremlins_ran_cleanly(result)
