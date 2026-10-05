"""A pooled timeout is re-run alone before it is judged (issue #565).

In parallel and batch mode a gremlin shares the machine with other workers, so a timeout may be contention,
not the mutant. The unmutated confirmation runs alone, so the mutated run it is compared with must too.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.control_run import (
    UnmutatedRunOutcome,
    run_unmutated,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _cache_gremlin_result,
    _confirm_pooled_result,
    _test_gremlin,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

TIMEOUT_SECONDS = 20
FINISHES_QUICKLY = UnmutatedRunOutcome(timed_out=False, seconds=0.1)
HANGS = UnmutatedRunOutcome(timed_out=True, seconds=float(TIMEOUT_SECONDS))
COMMAND = ['python', 'bootstrap.py', 't.py::test_a']
NODE_IDS = ['t.py::test_a']
SELECTED_TESTS = ['t.py::test_a']


def _gremlin() -> Gremlin:
    return Gremlin(
        gremlin_id='g001',
        file_path='/path/to/source.py',
        line_number=1,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


def _pooled(status: GremlinResultStatus, killing_test: str | None = None) -> GremlinResult:
    return GremlinResult(gremlin=_gremlin(), status=status, killing_test=killing_test, selected_tests=SELECTED_TESTS)


@pytest.fixture
def session(tmp_path: Path) -> GremlinSession:
    return GremlinSession(enabled=True, instrumented_dir=tmp_path, mutant_timeout=TIMEOUT_SECONDS)


@pytest.fixture
def fake_solo_run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    solo_run = create_autospec(_test_gremlin, return_value=_pooled(GremlinResultStatus.SURVIVED))
    monkeypatch.setattr('pytest_gremlins.plugin._test_gremlin', solo_run)
    return solo_run


@pytest.fixture
def fake_unmutated_run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    unmutated_run = create_autospec(run_unmutated, return_value=FINISHES_QUICKLY)
    monkeypatch.setattr('pytest_gremlins.plugin.run_unmutated', unmutated_run)
    return unmutated_run


def _confirm(result: GremlinResult, session: GremlinSession, tmp_path: Path) -> GremlinResult:
    return _confirm_pooled_result(result, COMMAND, NODE_IDS, session, tmp_path)


@pytest.mark.medium
@pytest.mark.usefixtures('fake_unmutated_run')
class DescribeRerunningAPooledTimeoutAlone:
    def it_scores_a_passing_solo_rerun_as_survived(
        self, session: GremlinSession, fake_solo_run: MagicMock, tmp_path: Path
    ) -> None:
        fake_solo_run.return_value = _pooled(GremlinResultStatus.SURVIVED)

        result = _confirm(_pooled(GremlinResultStatus.TIMEOUT), session, tmp_path)

        assert result.status == GremlinResultStatus.SURVIVED

    def it_scores_a_failing_solo_rerun_as_zapped_with_its_killing_test(
        self, session: GremlinSession, fake_solo_run: MagicMock, tmp_path: Path
    ) -> None:
        fake_solo_run.return_value = _pooled(GremlinResultStatus.ZAPPED, killing_test='t.py::test_a')

        result = _confirm(_pooled(GremlinResultStatus.TIMEOUT), session, tmp_path)

        assert result.status == GremlinResultStatus.ZAPPED
        assert result.killing_test == 't.py::test_a'

    def it_reruns_with_the_same_command_the_same_timeout_and_the_mutant_active(
        self, session: GremlinSession, fake_solo_run: MagicMock, tmp_path: Path
    ) -> None:
        _confirm(_pooled(GremlinResultStatus.TIMEOUT), session, tmp_path)

        args = fake_solo_run.call_args
        assert args.args[0].gremlin_id == _gremlin().gremlin_id
        assert args.args[1] == COMMAND
        assert args.args[2] == tmp_path
        assert args.kwargs['timeout'] == TIMEOUT_SECONDS

    def it_keeps_the_selected_tests_on_the_solo_result(
        self, session: GremlinSession, fake_solo_run: MagicMock, tmp_path: Path
    ) -> None:
        fake_solo_run.return_value = GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.SURVIVED)

        result = _confirm(_pooled(GremlinResultStatus.TIMEOUT), session, tmp_path)

        assert result.selected_tests == SELECTED_TESTS

    def it_keeps_a_timeout_that_repeats_alone_when_the_unmutated_run_has_headroom(
        self, session: GremlinSession, fake_solo_run: MagicMock, tmp_path: Path
    ) -> None:
        fake_solo_run.return_value = _pooled(GremlinResultStatus.TIMEOUT)

        result = _confirm(_pooled(GremlinResultStatus.TIMEOUT), session, tmp_path)

        assert result.status == GremlinResultStatus.TIMEOUT

    def it_downgrades_a_timeout_that_repeats_alone_when_the_unmutated_run_also_hangs(
        self, session: GremlinSession, fake_solo_run: MagicMock, fake_unmutated_run: MagicMock, tmp_path: Path
    ) -> None:
        fake_solo_run.return_value = _pooled(GremlinResultStatus.TIMEOUT)
        fake_unmutated_run.return_value = HANGS

        result = _confirm(_pooled(GremlinResultStatus.TIMEOUT), session, tmp_path)

        assert result.status == GremlinResultStatus.ERROR

    @pytest.mark.parametrize(
        'pooled',
        [
            pytest.param(_pooled(GremlinResultStatus.ZAPPED, killing_test='unknown'), id='zapped'),
            pytest.param(_pooled(GremlinResultStatus.SURVIVED), id='survived'),
            pytest.param(_pooled(GremlinResultStatus.ERROR), id='error'),
        ],
    )
    def it_runs_nothing_alone_for_a_pooled_result_that_did_not_time_out(
        self, session: GremlinSession, fake_solo_run: MagicMock, tmp_path: Path, pooled: GremlinResult
    ) -> None:
        result = _confirm(pooled, session, tmp_path)

        assert result == pooled
        fake_solo_run.assert_not_called()


@pytest.mark.medium
@pytest.mark.usefixtures('fake_unmutated_run')
class DescribeCachingOfSoloRerunResults:
    @pytest.fixture
    def cache(self, session: GremlinSession) -> MagicMock:
        cache = create_autospec(IncrementalCache, instance=True)
        session.cache_enabled = True
        session.cache = cache
        session.source_hashes = {'/path/to/source.py': 'hash'}
        return cache

    @pytest.mark.parametrize(
        ('solo', 'expected'),
        [
            pytest.param(_pooled(GremlinResultStatus.SURVIVED), 'survived', id='survived'),
            pytest.param(_pooled(GremlinResultStatus.ZAPPED, killing_test='unknown'), 'zapped', id='zapped'),
        ],
    )
    def it_caches_the_solo_verdict_like_any_other(
        self,
        session: GremlinSession,
        fake_solo_run: MagicMock,
        cache: MagicMock,
        tmp_path: Path,
        solo: GremlinResult,
        expected: str,
    ) -> None:
        fake_solo_run.return_value = solo
        result = _confirm(_pooled(GremlinResultStatus.TIMEOUT), session, tmp_path)

        _cache_gremlin_result(_gremlin(), SELECTED_TESTS, result, session)

        cache.cache_result_deferred.assert_called_once()
        assert cache.cache_result_deferred.call_args.kwargs['result']['status'] == expected
