"""With plugin autoload disabled, a session-loaded pytest-rerunfailures is loaded in gremlin runs too (issue #679).

``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` is inherited by gremlin runs, but a command-line ``-p pytest_rerunfailures`` is
not, so they used to run without reruns while the budget, timeout and cache key described reruns.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rerun_samples import (
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import RUNNER_FIDELITY_VERSION

AUTOLOAD_ENV_VAR = 'PYTEST_DISABLE_PLUGIN_AUTOLOAD'
LOAD_PLUGINS = ('-p', 'gremlins', '-p', 'pytest_rerunfailures')

# Fails on its first call in every gremlin run (ACTIVE_GREMLIN is set only there) and passes on a rerun, and
# leaves the mutants at the boundary alive.
FLAKY_UNDER_GREMLINS_TEST = """
import os

from sample import classify

calls = []


def test_big():
    calls.append(1)
    in_gremlin_run = 'ACTIVE_GREMLIN' in os.environ
    assert len(calls) > 1 or not in_gremlin_run, 'flaky inside gremlin runs'
    assert classify(11) == 'big'
"""


def _session_with(*, loaded: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        pluginmanager=SimpleNamespace(hasplugin=lambda name: name in loaded),
        option=SimpleNamespace(inifilename=None),
        invocation_params=SimpleNamespace(args=(), dir=None),
    )


@pytest.mark.small
class DescribeRerunOptionsWhenAutoloadIsDisabled:
    @pytest.mark.parametrize('autoload_value', ['1', 'true', 'yes'])
    def it_forwards_the_loader_when_the_session_loaded_the_plugin(
        self, monkeypatch: pytest.MonkeyPatch, autoload_value: str
    ) -> None:
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, autoload_value)
        config = _session_with(loaded=('pytest_rerunfailures',))

        assert plugin._rerun_options_for(config) == ['-p', 'pytest_rerunfailures']  # type: ignore[arg-type]

    def it_forwards_the_loader_ahead_of_the_command_line_rerun_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
        config = _session_with(loaded=('pytest_rerunfailures',))
        config.invocation_params.args = ('--reruns=2',)

        assert plugin._rerun_options_for(config)[:2] == ['-p', 'pytest_rerunfailures']  # type: ignore[arg-type]
        assert plugin._rerun_options_for(config)[2:] == ['--reruns=2']  # type: ignore[arg-type]

    def it_still_blocks_the_plugin_when_the_session_did_not_load_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
        config = _session_with(loaded=())

        assert plugin._rerun_options_for(config) == ['-p', 'no:rerunfailures']  # type: ignore[arg-type]

    @pytest.mark.parametrize('autoload_value', [None, ''])
    def it_forwards_no_loader_when_gremlin_runs_autoload_the_plugin(
        self, monkeypatch: pytest.MonkeyPatch, autoload_value: str | None
    ) -> None:
        # Autoload on: gremlin runs register the entry point, and a second ``-p`` would register it twice.
        if autoload_value is None:
            monkeypatch.delenv(AUTOLOAD_ENV_VAR, raising=False)
        else:
            monkeypatch.setenv(AUTOLOAD_ENV_VAR, autoload_value)
        config = _session_with(loaded=('rerunfailures',))

        assert plugin._rerun_options_for(config) == []  # type: ignore[arg-type]


@pytest.mark.small
class DescribeFidelityVersionAfterTheLoaderIsForwarded:
    def it_retires_verdicts_cached_while_gremlin_runs_never_reran(self) -> None:
        assert RUNNER_FIDELITY_VERSION == 'rf17'


def _write_flaky_project(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
    pytester.makeini('[pytest]\nreruns = 2\n')


@pytest.fixture
def autoload_disabled(pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable plugin autoload for the runs below; gremlin runs inherit it.

    ``-p pytest_cov.plugin`` rides along in ``PYTEST_ADDOPTS`` because gremlin runs append ``--no-cov`` whenever
    pytest-cov is installed, and they would reject it without the plugin loaded (a separate bug, issue #654).
    """
    assert pytester_with_markers  # pytester clears PYTEST_ADDOPTS when it is created, so it must exist first
    monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
    monkeypatch.setenv('PYTEST_ADDOPTS', '-p pytest_cov.plugin')


@pytest.mark.medium
@pytest.mark.usefixtures('autoload_disabled')
class DescribeGremlinRunsWhenAutoloadIsDisabledAndTheLoaderIsOnTheCommandLine:
    def it_reruns_like_a_session_with_autoload_on(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        autoload_off = pytester.runpytest_subprocess(*GREMLIN_ARGS, *LOAD_PLUGINS)
        monkeypatch.delenv(AUTOLOAD_ENV_VAR)
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)

        autoload_on = pytester.runpytest_subprocess(*GREMLIN_ARGS)

        assert verdicts(autoload_off.stdout.str()) == verdicts(autoload_on.stdout.str())
        assert verdicts(autoload_off.stdout.str())['Survived'] > 0

    def it_does_not_register_the_plugin_twice_when_addopts_repeats_the_loader(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        pytester.makeini('[pytest]\nreruns = 2\naddopts = -p pytest_rerunfailures\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, *LOAD_PLUGINS)

        assert verdicts(result.stdout.str())['Error'] == 0
        assert verdicts(result.stdout.str())['Survived'] > 0

    def it_does_not_register_the_plugin_twice_when_pytest_addopts_repeats_the_loader(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p pytest_cov.plugin -p pytest_rerunfailures')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'gremlins')

        assert verdicts(result.stdout.str())['Error'] == 0
        assert verdicts(result.stdout.str())['Survived'] > 0

    def it_does_not_register_the_plugin_twice_when_a_conftest_loads_it(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        pytester.makeconftest("pytest_plugins = ['pytest_rerunfailures']\n")

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'gremlins')

        assert verdicts(result.stdout.str())['Error'] == 0
        assert verdicts(result.stdout.str())['Survived'] > 0

    def it_does_not_serve_a_verdict_cached_without_reruns_to_a_run_that_reruns(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        cache_args = ('--gremlin-cache',)
        uncached_run = pytester.runpytest_subprocess(*GREMLIN_ARGS, *LOAD_PLUGINS)
        pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'gremlins', '-o', 'reruns=0', *cache_args)

        cached_run = pytester.runpytest_subprocess(*GREMLIN_ARGS, *LOAD_PLUGINS, *cache_args)

        assert verdicts(cached_run.stdout.str()) == verdicts(uncached_run.stdout.str())

    def it_serves_a_verdict_cached_by_a_run_that_reruns_to_the_next_one(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        cache_args = ('--gremlin-cache',)
        first_run = pytester.runpytest_subprocess(*GREMLIN_ARGS, *LOAD_PLUGINS, *cache_args)

        second_run = pytester.runpytest_subprocess(*GREMLIN_ARGS, *LOAD_PLUGINS, *cache_args)

        assert verdicts(second_run.stdout.str()) == verdicts(first_run.stdout.str())
        assert verdicts(second_run.stdout.str())['Survived'] > 0
