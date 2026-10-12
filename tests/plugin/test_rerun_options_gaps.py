"""Rerun settings that the baseline uses but gremlin runs or the coverage pre-scan miss (refs #546).

Each case was found by adversarial QA and reproduced end to end: the gremlin runs (or the pre-scan)
did not use the rerun settings the baseline used, so a flaky test zapped mutants it cannot catch, or
was left out of the coverage map and let a mutant survive.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.plugin import (
    GremlinSession,
    _rerun_options_for,
    _run_prescan_reporting_problems,
)
from pytest_gremlins.rerun_options import rerun_options_in


def _config_with_plugin_named(plugin_name: str, args: list[str]) -> pytest.Config:
    pluginmanager = SimpleNamespace(hasplugin=lambda name: name == plugin_name)
    fake = SimpleNamespace(pluginmanager=pluginmanager, invocation_params=SimpleNamespace(args=tuple(args), dir=Path()))
    return cast('pytest.Config', fake)


@pytest.mark.small
class DescribeRerunfailuresLoadedByModuleName:
    def it_carries_the_rerun_options_when_the_plugin_is_registered_as_pytest_rerunfailures(self) -> None:
        # PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 with ``-p pytest_rerunfailures`` (or ``pytest_plugins`` in a
        # conftest) registers the plugin under its module name, not the entry-point name.
        config = _config_with_plugin_named('pytest_rerunfailures', ['--gremlins', '--reruns', '2'])

        assert _rerun_options_for(config) == ['--reruns=2']


@pytest.mark.small
class DescribeRerunIniOverridesBeyondTheCount:
    @pytest.mark.parametrize(
        'setting', ['only_rerun=ConnectionError', 'rerun_except=AssertionError', 'reruns_delay_backoff_factor=2']
    )
    def it_carries_every_ini_key_pytest_rerunfailures_reads(self, setting: str) -> None:
        assert rerun_options_in(['-o', setting]) == [f'--override-ini={setting}']


@pytest.mark.small
class DescribeOverrideIniClusteredWithAFlag:
    def it_carries_an_ini_override_written_after_a_short_flag(self) -> None:
        # argparse reads ``-qo reruns=2`` as ``-q -o reruns=2``.
        assert rerun_options_in(['-qo', 'reruns=2']) == ['--override-ini=reruns=2']


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
