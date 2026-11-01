"""A plugin that an inherited source loads, and that itself loads pytest-rerunfailures, counts as a loader (issue #684).

Each test runs a real ``pytest --gremlins`` session that disables autoload on its command line only and names
``-p pytest_rerunfailures`` there too.  Gremlin runs do not get those flags, so they autoload the plugin through its
entry point; when the project's own ``localplug`` also loads the module by name, pluggy rejects the second
registration and every gremlin errors unless gremlin runs are told to disable autoload.
"""

from __future__ import annotations

import pytest
from rerun_samples import (
    FLAKY_UNDER_GREMLINS_TEST,
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

SESSION_ARGS = ('--disable-plugin-autoload', '-p', 'gremlins')
EXPECTED = {'Zapped': 1, 'Survived': 1, 'Error': 0}


def _write_project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, ini: str) -> None:
    for name in ('PYTEST_DISABLE_PLUGIN_AUTOLOAD', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'):
        monkeypatch.delenv(name, raising=False)
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
    pytester.makepyfile(localplug="pytest_plugins = ['pytest_rerunfailures']\n")
    pytester.makeini(ini)
    monkeypatch.setenv('PYTHONPATH', str(pytester.path))


@pytest.mark.medium
class DescribeTransitiveLoaderWithTheModuleOnTheCommandLine:
    def it_scores_no_errors_when_a_conftest_plugin_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project(pytester, monkeypatch, '[pytest]\nreruns = 2\n')
        pytester.makeconftest("pytest_plugins = ['localplug']\n")

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == EXPECTED, result.stdout.str()[-3000:]

    def it_scores_no_errors_when_an_ini_addopts_plugin_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project(pytester, monkeypatch, '[pytest]\nreruns = 2\naddopts = -p localplug\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == EXPECTED, result.stdout.str()[-3000:]

    def it_scores_no_errors_when_a_pytest_plugins_env_plugin_loads_the_module(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project(pytester, monkeypatch, '[pytest]\nreruns = 2\n')
        monkeypatch.setenv('PYTEST_PLUGINS', 'localplug')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == EXPECTED, result.stdout.str()[-3000:]
