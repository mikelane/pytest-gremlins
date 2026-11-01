"""The coverage pre-scan gets the xdist loader gremlin runs get (issue #927)."""

from __future__ import annotations

from pathlib import Path

from cov_samples import (
    SESSION_ARGS,
    assert_gremlins_ran_cleanly,
)
import pytest
from rerun_samples import SAMPLE

from pytest_gremlins import plugin

WORKER_ID_TEST = """
from sample import classify


def test_boundary(worker_id):
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

WEAK_TEST = """
from sample import classify


def test_runs_without_asserting():
    classify(5)
"""


def _prescan_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> list[str]:
    captured: list[list[str]] = []

    def capture(cmd: list[str], *_args: object) -> None:
        captured.append(cmd)
        raise plugin.CoveragePrescanLaunchError(OSError('stop'))

    monkeypatch.setattr(plugin, '_launch_prescan', capture)
    with pytest.raises(plugin.CoveragePrescanLaunchError):
        plugin._run_tests_with_coverage([], tmp_path, preserved_addopts='-q', **kwargs)  # type: ignore[arg-type]
    return captured[0]


@pytest.mark.medium
class DescribeXdistLoaderInThePrescanCommand:
    def it_puts_the_loader_options_in_the_prescan_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        command = _prescan_command(tmp_path, monkeypatch, xdist_loader_options=['-p', 'xdist'])

        assert command[command.index('xdist') - 1] == '-p'

    def it_places_the_loader_after_the_no_gremlins_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        command = _prescan_command(tmp_path, monkeypatch, xdist_loader_options=['-p', 'xdist'])

        assert command.index('xdist') > command.index('no:gremlins')

    def it_leaves_the_command_unchanged_when_no_loader_is_needed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        without = _prescan_command(tmp_path, monkeypatch)
        empty = _prescan_command(tmp_path, monkeypatch, xdist_loader_options=[])

        assert empty == without
        assert 'xdist' not in without

    def it_forwards_the_session_loader_to_the_prescan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}

        def fake(*_args: object, **kwargs: object) -> dict[str, dict[str, list[int]]]:
            seen.update(kwargs)
            return {'t': {}}

        monkeypatch.setattr(plugin, '_run_tests_with_coverage', fake)
        session = plugin.GremlinSession(enabled=True, xdist_loader_options=['-p', 'xdist'])

        plugin._run_prescan_reporting_problems(['t'], tmp_path, session, coverage_include=None)

        assert seen['xdist_loader_options'] == ['-p', 'xdist']


@pytest.fixture
def worker_id_project(pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    for name in ('PYTEST_DISABLE_PLUGIN_AUTOLOAD', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS'):
        monkeypatch.delenv(name, raising=False)
    pytester_with_markers.makepyfile(sample=SAMPLE)
    pytester_with_markers.makepyfile(test_sample=WORKER_ID_TEST)
    pytester_with_markers.makepyfile(test_weak=WEAK_TEST)
    return pytester_with_markers


@pytest.mark.medium
class DescribeAGremlinOnlyAWorkerIdTestCatches:
    def it_zaps_it_when_autoload_is_off_and_the_command_line_loads_xdist(
        self, worker_id_project: pytest.Pytester
    ) -> None:
        worker_id_project.makeini('[pytest]\naddopts = --disable-plugin-autoload\n')

        result = worker_id_project.runpytest_subprocess(*SESSION_ARGS, '-p', 'xdist')

        assert_gremlins_ran_cleanly(result)

    def it_zaps_it_when_addopts_blocks_xdist_and_the_command_line_loads_it_again(
        self, worker_id_project: pytest.Pytester
    ) -> None:
        worker_id_project.makeini('[pytest]\naddopts = -p no:xdist\n')

        result = worker_id_project.runpytest_subprocess(*SESSION_ARGS, '-p', 'xdist')

        assert_gremlins_ran_cleanly(result)
