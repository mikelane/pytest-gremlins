"""A command-line ``--disable-plugin-autoload`` with an inherited module-name rerunfailures load (issue #684).

The session turns autoload off only on its command line, which gremlin runs never see, and the plugin is loaded
by module name through a source gremlin runs inherit (conftest ``pytest_plugins``, ``PYTEST_PLUGINS`` or ini
``addopts``).  Gremlin runs that autoload would register the ``rerunfailures`` entry point and then load the same
module again as ``pytest_rerunfailures``, which pluggy rejects, so every gremlin was an ERROR.
"""

from __future__ import annotations

import pytest
from rerun_samples import (
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
