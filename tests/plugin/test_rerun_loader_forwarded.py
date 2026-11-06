"""With plugin autoload disabled, a session-loaded pytest-rerunfailures is loaded in gremlin runs too (issue #679).

``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` is inherited by gremlin runs, but a command-line ``-p pytest_rerunfailures`` is
not, so they used to run without reruns while the budget, timeout and cache key described reruns.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import (
    TYPE_CHECKING,
    cast,
)

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    AUTOLOAD_ENV_VAR,
    FLAKY_UNDER_GREMLINS_TEST,
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

from pytest_gremlins import plugin
from pytest_gremlins.cache import incremental
from pytest_gremlins.cache.incremental import IncrementalCache

if TYPE_CHECKING:
    from pytest_gremlins.cache.types import CachedGremlinResult

LOAD_PLUGINS = ('-p', 'gremlins', '-p', 'pytest_rerunfailures')


def _session_with(
    *, loaded: tuple[str, ...] = (), addopts: tuple[str, ...] = (), args: tuple[str, ...] = ()
) -> SimpleNamespace:
    return SimpleNamespace(
        pluginmanager=SimpleNamespace(hasplugin=lambda name: name in loaded),
        option=SimpleNamespace(inifilename=None),
        invocation_params=SimpleNamespace(args=args, dir=None),
        rootdir=Path(),
        getini=lambda name: list(addopts) if name == 'addopts' else None,
    )


@pytest.mark.small
class DescribeRerunOptionsWhenAutoloadIsDisabled:
    # Pytest tests the variable for truthiness of the string, so '0' and 'false' disable autoload too.
    @pytest.mark.parametrize('autoload_value', ['1', 'true', 'yes', '0', 'false'])
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

        assert plugin._rerun_options_for(config) == ['-p', 'pytest_rerunfailures', '--reruns=2']  # type: ignore[arg-type]

    def it_still_blocks_the_plugin_when_the_session_did_not_load_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
        config = _session_with(loaded=())

        assert plugin._rerun_options_for(config) == ['-p', 'no:rerunfailures']  # type: ignore[arg-type]

    def it_forwards_no_loader_when_gremlin_runs_autoload_the_plugin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Autoload on: gremlin runs register the entry point, and a second ``-p`` would register it twice.
        monkeypatch.delenv(AUTOLOAD_ENV_VAR, raising=False)
        config = _session_with(loaded=('rerunfailures',))

        assert plugin._rerun_options_for(config) == []  # type: ignore[arg-type]

    def it_forwards_no_loader_when_the_autoload_variable_is_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pytest treats an empty value as unset, so gremlin runs autoload the plugin.
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '')
        config = _session_with(loaded=('rerunfailures',))

        assert plugin._rerun_options_for(config) == []  # type: ignore[arg-type]


@pytest.mark.small
class DescribeTheLoaderNameForwardedToGremlinRuns:
    """The loader repeats the name the session registered, so no gremlin run sees the module under two names."""

    @pytest.mark.parametrize('registered_name', ['rerunfailures', 'pytest_rerunfailures'])
    def it_forwards_the_loader_under_the_registered_name(
        self, monkeypatch: pytest.MonkeyPatch, registered_name: str
    ) -> None:
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
        config = _session_with(loaded=(registered_name,))

        assert plugin._rerun_options_for(config) == ['-p', registered_name]  # type: ignore[arg-type]


@pytest.mark.small
class DescribeRerunOptionsWhenGremlinRunsInheritTheAutoloadFlag:
    """Gremlin runs get the project's ``addopts`` and ``PYTEST_ADDOPTS``, so a flag there disables their autoload."""

    @pytest.fixture(autouse=True)
    def _autoload_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(AUTOLOAD_ENV_VAR, raising=False)
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)

    def it_forwards_the_loader_when_ini_addopts_disables_autoload(self) -> None:
        config = _session_with(loaded=('pytest_rerunfailures',), addopts=('-v', '--disable-plugin-autoload'))

        assert plugin._rerun_options_for(config) == ['-p', 'pytest_rerunfailures']  # type: ignore[arg-type]

    def it_forwards_the_loader_when_pytest_addopts_disables_autoload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', "-p 'my plugin' --disable-plugin-autoload")
        config = _session_with(loaded=('pytest_rerunfailures',))

        assert plugin._rerun_options_for(config) == ['-p', 'pytest_rerunfailures']  # type: ignore[arg-type]

    def it_forwards_no_loader_when_only_the_session_command_line_disables_autoload(self) -> None:
        # The command line is not inherited, so gremlin runs autoload the plugin and would register it twice.
        config = _session_with(loaded=('pytest_rerunfailures',), args=('--disable-plugin-autoload',))

        assert plugin._rerun_options_for(config) == []  # type: ignore[arg-type]

    def it_ignores_an_option_that_merely_contains_the_flag_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '--disable-plugin-autoload-not')
        config = _session_with(loaded=('rerunfailures',), addopts=('--ignore=--disable-plugin-autoload',))

        assert plugin._rerun_options_for(config) == []  # type: ignore[arg-type]

    def it_tolerates_unparsable_pytest_addopts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '"unterminated')
        config = _session_with(loaded=('rerunfailures',))

        assert plugin._rerun_options_for(config) == []  # type: ignore[arg-type]


@pytest.mark.medium
class DescribeFidelityVersionAfterTheLoaderIsForwarded:
    """Verdicts cached while gremlin runs never reran belong to an older fidelity version and must miss."""

    TEST_HASHES = {'tests/test_x.py::test_a': 'hash_a'}  # noqa: RUF012
    VERDICT = cast('CachedGremlinResult', {'status': 'survived'})

    def it_misses_a_verdict_cached_under_a_previous_fidelity_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            with monkeypatch.context() as previous:
                previous.setattr(incremental, 'RUNNER_FIDELITY_VERSION', f'{incremental.RUNNER_FIDELITY_VERSION}-old')
                cache.cache_result('g001', 'src_hash', self.TEST_HASHES, self.VERDICT)

            assert cache.get_cached_result('g001', 'src_hash', self.TEST_HASHES) is None

    def it_hits_a_verdict_cached_under_the_current_fidelity_version(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            cache.cache_result('g001', 'src_hash', self.TEST_HASHES, self.VERDICT)

            assert cache.get_cached_result('g001', 'src_hash', self.TEST_HASHES) == self.VERDICT


def _write_flaky_project(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
    pytester.makeini('[pytest]\nreruns = 2\n')


@pytest.fixture
def autoload_disabled(
    pytester_with_markers: pytest.Pytester,  # noqa: ARG001 - requested only so it is created first
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disable plugin autoload for the runs below; gremlin runs inherit it.

    ``-p pytest_cov.plugin`` rides along in ``PYTEST_ADDOPTS`` because gremlin runs append ``--no-cov`` whenever
    pytest-cov is installed, and they would reject it without the plugin loaded (a separate bug, issue #654).
    Requesting ``pytester_with_markers`` first matters: pytester clears ``PYTEST_ADDOPTS`` when it is created.
    """
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
        assert verdicts(autoload_off.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_does_not_register_the_plugin_twice_when_addopts_repeats_the_loader(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        pytester.makeini('[pytest]\nreruns = 2\naddopts = -p pytest_rerunfailures\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, *LOAD_PLUGINS)

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_does_not_register_the_plugin_twice_when_pytest_addopts_repeats_the_loader(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p pytest_cov.plugin -p pytest_rerunfailures')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'gremlins')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_does_not_register_the_plugin_twice_when_a_conftest_loads_it(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester)
        pytester.makeconftest("pytest_plugins = ['pytest_rerunfailures']\n")

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'gremlins')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

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
        assert verdicts(second_run.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}
