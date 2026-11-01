"""A command-line ``--disable-plugin-autoload`` with an inherited module-name rerunfailures load (issue #684).

The session turns autoload off only on its command line, which gremlin runs never see, and the plugin is loaded
by module name through a source gremlin runs inherit (conftest ``pytest_plugins``, ``PYTEST_PLUGINS`` or ini
``addopts``).  Gremlin runs that autoload would register the ``rerunfailures`` entry point and then load the same
module again as ``pytest_rerunfailures``, which pluggy rejects, so every gremlin was an ERROR.
"""

from __future__ import annotations

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

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
SESSION_ARGS = ('--disable-plugin-autoload', '-p', 'gremlins')
# Inherited, so gremlin runs (which pass ``--no-cov`` when pytest-cov is installed) still know that option.
COV_ADDOPTS = '-p pytest_cov.plugin'


def _write_flaky_project(pytester: pytest.Pytester, ini: str, conftest: str = '') -> None:
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
    pytester.makeini(ini)
    if conftest:
        pytester.makeconftest(conftest)


@pytest.mark.medium
class DescribeModuleNameLoadWithAutoloadDisabledOnlyOnTheCommandLine:
    def it_reruns_when_a_conftest_loads_the_plugin(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        _write_flaky_project(
            pytester_with_markers,
            f'[pytest]\nreruns = 2\naddopts = {COV_ADDOPTS}\n',
            conftest="pytest_plugins = ['pytest_rerunfailures']\n",
        )

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS)

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_reruns_when_pytest_plugins_loads_the_plugin(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        monkeypatch.setenv('PYTEST_PLUGINS', 'pytest_rerunfailures')
        _write_flaky_project(pytester_with_markers, f'[pytest]\nreruns = 2\naddopts = {COV_ADDOPTS}\n')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS)

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_reruns_when_ini_addopts_loads_the_plugin(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        _write_flaky_project(
            pytester_with_markers, f'[pytest]\nreruns = 2\naddopts = {COV_ADDOPTS} -p pytest_rerunfailures\n'
        )

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS)

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}


CONFTEST_LOADING_RERUNFAILURES = "pytest_plugins = ['pytest_rerunfailures']\n"


@pytest.mark.medium
class DescribeGremlinRunsThatSkipAutoloadWithoutAnInheritedCovLoader:
    """Gremlin runs given ``--disable-plugin-autoload`` do not load pytest-cov, so ``--no-cov`` is unknown to them."""

    @pytest.mark.parametrize('extra_args', [(), ('-p', 'pytest_cov')])
    def it_has_no_errors_without_an_inherited_cov_loader(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, extra_args: tuple[str, ...]
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
        _write_flaky_project(pytester_with_markers, '[pytest]\nreruns = 2\n', conftest=CONFTEST_LOADING_RERUNFAILURES)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS, *extra_args)

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}


@pytest.mark.medium
class DescribeModuleNameLoadOnTheCommandLineAndInherited:
    def it_reruns_when_the_command_line_and_a_conftest_both_load_the_plugin(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
        _write_flaky_project(
            pytester_with_markers,
            f'[pytest]\nreruns = 2\naddopts = {COV_ADDOPTS}\n',
            conftest=CONFTEST_LOADING_RERUNFAILURES,
        )

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}


ENTRY_POINT_FIXTURE_TEST = """
from sample import classify


def test_big(no_cover):
    assert classify(11) == 'big'
"""
NO_ERRORS = {'Zapped': 1, 'Survived': 1, 'Error': 0}


@pytest.mark.medium
class DescribeModuleNameLoadOnTheCommandLineOnly:
    """Nothing inherited names the module, so gremlin runs keep autoload and load it once through the entry point."""

    def it_keeps_entry_point_fixtures_of_other_command_line_plugins(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
        monkeypatch.delenv('PYTEST_PLUGINS', raising=False)
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=ENTRY_POINT_FIXTURE_TEST)
        pytester_with_markers.makeini('[pytest]\nreruns = 2\n')

        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, *SESSION_ARGS, '-p', 'pytest_rerunfailures', '-p', 'pytest_cov'
        )

        assert verdicts(result.stdout.str()) == NO_ERRORS

    def it_has_no_errors_when_xdist_is_also_loaded_on_the_command_line(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
        monkeypatch.delenv('PYTEST_PLUGINS', raising=False)
        _write_flaky_project(pytester_with_markers, '[pytest]\nreruns = 2\n')

        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, *SESSION_ARGS, '-p', 'pytest_rerunfailures', '-p', 'xdist'
        )

        assert verdicts(result.stdout.str()) == NO_ERRORS

    def it_ignores_pytest_plugins_declared_by_a_command_line_only_plugin(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
        monkeypatch.delenv('PYTEST_PLUGINS', raising=False)
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=ENTRY_POINT_FIXTURE_TEST)
        pytester_with_markers.makepyfile(localplug="pytest_plugins = ['pytest_rerunfailures']\n")
        pytester_with_markers.makeini('[pytest]\nreruns = 2\n')
        monkeypatch.setenv('PYTHONPATH', str(pytester_with_markers.path))

        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, *SESSION_ARGS, '-p', 'pytest_rerunfailures', '-p', 'localplug', '-p', 'pytest_cov'
        )

        assert verdicts(result.stdout.str()) == NO_ERRORS


@pytest.mark.medium
class DescribeCovLoadedThroughPytestAddopts:
    def it_does_not_let_the_coverage_gate_fail_gremlin_runs(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        monkeypatch.delenv('PYTEST_PLUGINS', raising=False)
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p pytest_cov --cov=sample --cov-fail-under=100')
        _write_flaky_project(pytester_with_markers, '[pytest]\nreruns = 2\n', conftest=CONFTEST_LOADING_RERUNFAILURES)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS)

        assert verdicts(result.stdout.str()) == NO_ERRORS
