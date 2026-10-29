"""Adversarial QA (#891): pytester loaded under its module path still retires #615 verdicts."""

from __future__ import annotations

import pytest

GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=comparison', '--gremlin-cache')
COLD = 'Cache: 0 hits, 2 misses (0% hit rate)'
TARGET_WITH_COMPARISON = 'def limit(x):\n    return x > 41\n'
TEST_WITH_COMPARISON = 'from target import limit\n\n\ndef test_limit():\n    assert limit(42)\n'


@pytest.fixture
def project(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makepyfile(target=TARGET_WITH_COMPARISON, test_target=TEST_WITH_COMPARISON)
    return pytester


@pytest.mark.medium
class DescribePytesterLoadedByModulePath:
    def it_misses_the_cache_once_when_pytester_is_loaded_with_p_and_its_module_path(
        self, project: pytest.Pytester
    ) -> None:
        project.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([COLD])

        project.runpytest_subprocess(*GREMLIN_ARGS, '-p', '_pytest.pytester').stdout.fnmatch_lines([COLD])


WARM = 'Cache: 2 hits, 0 misses (100% hit rate)'


def _conftest_module_path(pytester: pytest.Pytester, _monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    pytester.makeconftest("pytest_plugins = ['_pytest.pytester']\n")
    return ()


def _conftest_string_form(pytester: pytest.Pytester, _monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    pytester.makeconftest("pytest_plugins = 'pytester'\n")
    return ()


def _env_by_name(_pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    monkeypatch.setenv('PYTEST_PLUGINS', 'pytester')
    return ()


def _env_by_module_path(_pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    monkeypatch.setenv('PYTEST_PLUGINS', '_pytest.pytester')
    return ()


def _addopts_module_path(pytester: pytest.Pytester, _monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    pytester.makeini('[pytest]\naddopts = -p _pytest.pytester\n')
    return ()


EXTRA_ENABLERS = {
    'conftest module path': _conftest_module_path,
    'conftest string form': _conftest_string_form,
    'PYTEST_PLUGINS by name': _env_by_name,
    'PYTEST_PLUGINS by module path': _env_by_module_path,
    'addopts module path': _addopts_module_path,
}

MODES = {
    'serial': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-parallel', '--gremlin-workers=2', '--gremlin-batch'),
}


@pytest.mark.medium
class DescribePytesterLoadedThroughOtherSources:
    @pytest.mark.parametrize('enabler', EXTRA_ENABLERS.values(), ids=EXTRA_ENABLERS.keys())
    def it_misses_once_then_hits(
        self, project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, enabler: object
    ) -> None:
        project.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([COLD])
        extra = enabler(project, monkeypatch)  # type: ignore[operator]

        project.runpytest_subprocess(*GREMLIN_ARGS, *extra).stdout.fnmatch_lines([COLD])

        project.runpytest_subprocess(*GREMLIN_ARGS, *extra).stdout.fnmatch_lines([WARM])


@pytest.mark.medium
class DescribePytesterKeyInPooledModes:
    @pytest.mark.parametrize('mode', MODES.values(), ids=MODES.keys())
    def it_misses_once_with_pytester_then_hits(self, project: pytest.Pytester, mode: tuple[str, ...]) -> None:
        project.runpytest_subprocess(*GREMLIN_ARGS, *mode).stdout.fnmatch_lines([COLD])

        project.runpytest_subprocess(*GREMLIN_ARGS, *mode, '-p', 'pytester').stdout.fnmatch_lines([COLD])

        project.runpytest_subprocess(*GREMLIN_ARGS, *mode, '-p', 'pytester').stdout.fnmatch_lines([WARM])

    @pytest.mark.parametrize('mode', MODES.values(), ids=MODES.keys())
    def it_keeps_a_warm_cache_without_pytester(self, project: pytest.Pytester, mode: tuple[str, ...]) -> None:
        project.runpytest_subprocess(*GREMLIN_ARGS, *mode).stdout.fnmatch_lines([COLD])

        project.runpytest_subprocess(*GREMLIN_ARGS, *mode).stdout.fnmatch_lines([WARM])
