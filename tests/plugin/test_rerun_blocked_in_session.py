"""A command-line ``-p no:rerunfailures`` reaches gremlin runs, so they match the session (issue #670)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from rerun_samples import (
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import IncrementalCache

if TYPE_CHECKING:
    from pathlib import Path

# Kills every comparison mutant of ``classify`` on the first attempt.
STEADY_TEST = """
from sample import classify


def test_big():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

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

BLOCK_RERUNFAILURES = ('-p', 'no:rerunfailures')


def _session_with(*, blocked: tuple[str, ...], loaded: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        pluginmanager=SimpleNamespace(
            hasplugin=lambda name: name in loaded,
            is_blocked=lambda name: name in blocked,
        ),
        option=SimpleNamespace(inifilename=None),
        invocation_params=SimpleNamespace(args=(), dir=None),
    )


@pytest.mark.small
class DescribeRerunOptionsWhenTheSessionBlockedThePlugin:
    @pytest.mark.parametrize('blocked_name', ['rerunfailures', 'pytest_rerunfailures'])
    def it_forwards_the_block_to_gremlin_runs(self, blocked_name: str) -> None:
        config = _session_with(blocked=(blocked_name,))

        assert plugin._rerun_options_for(config) == ['-p', 'no:rerunfailures']  # type: ignore[arg-type]

    def it_forwards_nothing_when_the_plugin_is_neither_loaded_nor_blocked(self) -> None:
        assert plugin._rerun_options_for(_session_with(blocked=())) == []  # type: ignore[arg-type]

    def it_does_not_block_the_entry_point_plugin_the_session_loaded_when_only_the_module_name_was_blocked(self) -> None:
        # ``-p no:pytest_rerunfailures`` blocks only the module name; the plugin still autoloads as ``rerunfailures``.
        config = _session_with(blocked=('pytest_rerunfailures',), loaded=('rerunfailures',))

        assert plugin._rerun_options_for(config) == []  # type: ignore[arg-type]

    def it_does_not_block_a_plugin_the_session_loaded(self) -> None:
        config = _session_with(blocked=(), loaded=('rerunfailures',))

        assert '-p' not in plugin._rerun_options_for(config)  # type: ignore[arg-type]


@pytest.mark.medium
class DescribeRetiredVerdictsFromBlockedSessions:
    def it_retires_verdicts_cached_while_gremlin_runs_ignored_the_block(self, tmp_path: Path) -> None:
        with IncrementalCache(tmp_path / '.gremlins_cache') as cache:
            current_key = cache._build_cache_key('g001', 'src_hash', {'t': 'h'}, 30)

        assert current_key.rsplit(':', 1)[1] != 'rf15'


@pytest.mark.medium
class DescribeGremlinRunsUnderACommandLineBlock:
    def it_does_not_let_the_ini_reruns_delay_outlast_the_timeout(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=STEADY_TEST)
        pytester.makeini('[pytest]\nreruns = 1\nreruns_delay = 8\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--gremlin-mutant-timeout', '3', *BLOCK_RERUNFAILURES)

        output = result.stdout.str()
        assert 'Timeout' not in output
        assert verdicts(output)['Zapped'] > 0

    def it_accepts_the_block_when_addopts_repeats_it(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=STEADY_TEST)
        pytester.makeini('[pytest]\nreruns = 1\nreruns_delay = 8\naddopts = -p no:rerunfailures\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--gremlin-mutant-timeout', '3', *BLOCK_RERUNFAILURES)

        assert verdicts(result.stdout.str())['Zapped'] > 0
        assert result.ret == 0

    def it_serves_a_verdict_cached_without_reruns_the_same_as_a_fresh_run(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
        pytester.makeini('[pytest]\nreruns = 2\n')
        cache_args = ('--gremlin-cache',)

        def run(*extra_args: str) -> pytest.RunResult:
            return pytester.runpytest_subprocess(*GREMLIN_ARGS, *BLOCK_RERUNFAILURES, *extra_args)

        uncached_run = run()
        pytester.runpytest_subprocess(*GREMLIN_ARGS, '-o', 'reruns=0', *cache_args)
        cached_run = run(*cache_args)

        assert verdicts(cached_run.stdout.str()) == verdicts(uncached_run.stdout.str())
