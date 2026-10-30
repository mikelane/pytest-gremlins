"""Every form pytest accepts for ``pytest_plugins`` is read the way pytest reads it (issue #684).

Pytest treats ``None`` as empty and splits a string on commas.  The check for a plugin that loads
pytest-rerunfailures by module name must do the same: ``None`` must not crash the session, and a comma-separated
string must still reveal the loader.  Each test runs a real ``pytest --gremlins`` session that disables autoload and
names ``-p pytest_rerunfailures`` on its command line only.
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
SESSION_ARGS = ('--disable-plugin-autoload', '-p', 'gremlins', '-p', 'pytest_rerunfailures')
EXPECTED = {'Zapped': 1, 'Survived': 1, 'Error': 0}
COMMA_SEPARATED_LOADER = "pytest_plugins = 'otherplug,pytest_rerunfailures'\n"


def _write_project(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, ini: str = '[pytest]\nreruns = 2\n'
) -> None:
    for name in ('PYTEST_DISABLE_PLUGIN_AUTOLOAD', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'):
        monkeypatch.delenv(name, raising=False)
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
    pytester.makepyfile(otherplug='')
    pytester.makeini(ini)
    monkeypatch.setenv('PYTHONPATH', str(pytester.path))


def _run(pytester: pytest.Pytester) -> str:
    return pytester.runpytest_subprocess(*GREMLIN_ARGS, *SESSION_ARGS).stdout.str()


@pytest.mark.medium
class DescribePytestPluginsForms:
    def it_does_not_crash_when_a_conftest_sets_pytest_plugins_to_none(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project(pytester, monkeypatch)
        pytester.makeconftest('pytest_plugins = None\n')

        out = _run(pytester)

        assert 'TypeError' not in out, out[-3000:]
        assert verdicts(out) == EXPECTED, out[-3000:]

    def it_does_not_crash_when_an_addopts_plugin_sets_pytest_plugins_to_none(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project(pytester, monkeypatch, '[pytest]\nreruns = 2\naddopts = -p localplug\n')
        pytester.makepyfile(localplug='pytest_plugins = None\n')

        out = _run(pytester)

        assert 'TypeError' not in out, out[-3000:]
        assert verdicts(out) == EXPECTED, out[-3000:]

    def it_finds_the_module_in_a_comma_separated_conftest_string(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project(pytester, monkeypatch)
        pytester.makeconftest(COMMA_SEPARATED_LOADER)

        assert verdicts(_run(pytester)) == EXPECTED

    def it_finds_the_module_in_a_comma_separated_string_one_level_down(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project(pytester, monkeypatch)
        pytester.makepyfile(localplug=COMMA_SEPARATED_LOADER)
        pytester.makeconftest("pytest_plugins = ['localplug']\n")

        assert verdicts(_run(pytester)) == EXPECTED
