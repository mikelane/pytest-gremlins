"""A session that does not load pytest-rerunfailures blocks it in gremlin runs too, so they match it (issue #670).

That covers a command-line ``-p no:rerunfailures``, ``--disable-plugin-autoload`` and the plugin not being installed.
"""

from __future__ import annotations

from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from rerun_samples import (
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

from pytest_gremlins import plugin
from pytest_gremlins.cache.incremental import IncrementalCache

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

# Mutants at the boundary of ``classify`` stay alive, so a gremlin run must reach the end of the flaky test.
FLAKY_MARKER_TEST = """
import pytest
from sample import classify


@pytest.mark.flaky(reruns=1, reruns_delay=8)
def test_big():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

BLOCK_RERUNFAILURES = ('-p', 'no:rerunfailures')
PARALLEL_RERUNS_DELAY_SECONDS = 60
AUTOLOAD_DISABLED = ('--disable-plugin-autoload', '-p', 'gremlins')


def _session_with(*, loaded: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        pluginmanager=SimpleNamespace(hasplugin=lambda name: name in loaded),
        option=SimpleNamespace(inifilename=None),
        invocation_params=SimpleNamespace(args=(), dir=None),
        rootdir=Path(),
        getini=lambda name: [] if name == 'addopts' else None,
    )


@pytest.mark.small
class DescribeRerunOptionsWhenTheSessionDidNotLoadThePlugin:
    def it_forwards_the_block_to_gremlin_runs(self) -> None:
        # ``-p no:rerunfailures``, ``-p no:pytest_rerunfailures`` with autoload off, and ``--disable-plugin-autoload``
        # all leave the session without the plugin; gremlin runs would still autoload it.
        config = _session_with(loaded=())

        assert plugin._rerun_options_for(config) == ['-p', 'no:rerunfailures']  # type: ignore[arg-type]

    @pytest.mark.parametrize('loaded_name', ['rerunfailures', 'pytest_rerunfailures'])
    def it_forwards_no_block_when_the_session_loaded_the_plugin(self, loaded_name: str) -> None:
        # ``-p no:pytest_rerunfailures`` blocks only the module name; the plugin still autoloads as ``rerunfailures``.
        config = _session_with(loaded=(loaded_name,))

        assert plugin._rerun_options_for(config) == []  # type: ignore[arg-type]


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


@pytest.mark.medium
class DescribeGremlinRunsWithPluginAutoloadDisabled:
    def it_does_not_let_the_ini_reruns_delay_outlast_the_timeout(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=STEADY_TEST)
        pytester.makeini('[pytest]\nreruns = 1\nreruns_delay = 8\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--gremlin-mutant-timeout', '3', *AUTOLOAD_DISABLED)

        output = result.stdout.str()
        assert 'Timeout' not in output
        assert verdicts(output)['Zapped'] > 0

    def it_serves_a_verdict_cached_without_reruns_the_same_as_a_fresh_run(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
        pytester.makeini('[pytest]\nreruns = 2\n')
        cache_args = ('--gremlin-cache',)

        def run(*extra_args: str) -> pytest.RunResult:
            return pytester.runpytest_subprocess(*GREMLIN_ARGS, *AUTOLOAD_DISABLED, *extra_args)

        uncached_run = run()
        pytester.runpytest_subprocess(*GREMLIN_ARGS, '-o', 'reruns=0', *cache_args)
        cached_run = run(*cache_args)

        assert verdicts(cached_run.stdout.str()) == verdicts(uncached_run.stdout.str())


@pytest.mark.medium
class DescribeGremlinRunsUnderABlockWithOtherRunModes:
    def it_ignores_a_flaky_marker_reruns_delay(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=FLAKY_MARKER_TEST)

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--gremlin-mutant-timeout', '3', *BLOCK_RERUNFAILURES)

        output = result.stdout.str()
        assert 'Timeout' not in output
        assert verdicts(output)['Zapped'] > 0

    def it_applies_the_block_to_parallel_workers(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=STEADY_TEST)
        # Wider than the siblings' 8/3: worker start-up on a loaded runner can eat a 3s timeout. Workers do
        # have a per-mutant timeout, but this session runs with -p no:rerunfailures, so the timeout is not
        # widened: an unblocked rerun is cut at the 20s timeout and reported as a Timeout, leaving no Zapped
        # gremlins. Zapped > 0 is the primary signal; elapsed time below the delay is a backup.
        pytester.makeini(f'[pytest]\nreruns = 1\nreruns_delay = {PARALLEL_RERUNS_DELAY_SECONDS}\n')

        started = time.monotonic()
        result = pytester.runpytest_subprocess(
            *GREMLIN_ARGS,
            '--gremlin-mutant-timeout',
            '20',
            '--gremlin-parallel',
            '--gremlin-workers',
            '2',
            *BLOCK_RERUNFAILURES,
        )
        elapsed = time.monotonic() - started

        output = result.stdout.str()
        assert elapsed < PARALLEL_RERUNS_DELAY_SECONDS
        assert verdicts(output)['Zapped'] > 0

    def it_applies_the_block_to_batched_runs(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        pytester.makepyfile(sample=SAMPLE)
        pytester.makepyfile(test_sample=STEADY_TEST)
        pytester.makeini('[pytest]\nreruns = 1\nreruns_delay = 8\n')

        result = pytester.runpytest_subprocess(
            *GREMLIN_ARGS, '--gremlin-mutant-timeout', '3', '--gremlin-batch', *BLOCK_RERUNFAILURES
        )

        output = result.stdout.str()
        assert 'Timeout' not in output
        assert verdicts(output)['Zapped'] > 0
