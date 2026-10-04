"""A timeout kill is confirmed by running the gremlin's own selection unmutated (issue #565)."""

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
    _confirm_timeout_kill,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

FINISHES = UnmutatedRunOutcome(timed_out=False, seconds=0.1)
HANGS = UnmutatedRunOutcome(timed_out=True, seconds=1.0)
TIMEOUT_SECONDS = 7


def _gremlin(gremlin_id: str = 'g001') -> Gremlin:
    return Gremlin(
        gremlin_id=gremlin_id,
        file_path='/path/to/source.py',
        line_number=1,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


def _timeout(gremlin_id: str = 'g001') -> GremlinResult:
    return GremlinResult(gremlin=_gremlin(gremlin_id), status=GremlinResultStatus.TIMEOUT)


@pytest.fixture
def session(tmp_path: Path) -> GremlinSession:
    return GremlinSession(enabled=True, instrumented_dir=tmp_path, mutant_timeout=TIMEOUT_SECONDS)


@pytest.fixture
def fake_unmutated_run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    unmutated_run = create_autospec(run_unmutated, return_value=FINISHES)
    monkeypatch.setattr('pytest_gremlins.plugin.run_unmutated', unmutated_run)
    return unmutated_run


@pytest.mark.medium
class DescribeConfirmTimeoutKill:
    @pytest.mark.usefixtures('fake_unmutated_run')
    def it_keeps_a_timeout_when_the_unmutated_selection_finishes_in_time(
        self, session: GremlinSession, tmp_path: Path
    ) -> None:
        result = _confirm_timeout_kill(_timeout(), ['t.py::test_a'], session, tmp_path)

        assert result.status == GremlinResultStatus.TIMEOUT

    def it_downgrades_a_timeout_to_error_when_the_unmutated_selection_also_times_out(
        self, session: GremlinSession, fake_unmutated_run: MagicMock, tmp_path: Path
    ) -> None:
        fake_unmutated_run.return_value = HANGS

        result = _confirm_timeout_kill(_timeout(), ['t.py::test_a'], session, tmp_path)

        assert result.status == GremlinResultStatus.ERROR

    def it_names_the_selection_the_timeout_and_the_ways_to_raise_it(
        self, session: GremlinSession, fake_unmutated_run: MagicMock, tmp_path: Path
    ) -> None:
        fake_unmutated_run.return_value = HANGS

        message = _confirm_timeout_kill(_timeout(), ['t.py::test_a', 't.py::test_b'], session, tmp_path).error_output

        assert message is not None
        assert 't.py::test_a' in message
        assert f'{TIMEOUT_SECONDS}s' in message
        assert '--gremlin-mutant-timeout' in message
        assert '[tool.pytest-gremlins].mutant_timeout' in message

    def it_runs_the_exact_node_ids_under_the_session_timeout(
        self, session: GremlinSession, fake_unmutated_run: MagicMock, tmp_path: Path
    ) -> None:
        _confirm_timeout_kill(_timeout(), ['t.py::test_b', 't.py::test_a'], session, tmp_path)

        assert fake_unmutated_run.call_args.args[1] == ['t.py::test_b', 't.py::test_a']
        assert fake_unmutated_run.call_args.kwargs['timeout'] == TIMEOUT_SECONDS

    def it_runs_a_selection_shared_by_many_gremlins_once(
        self, session: GremlinSession, fake_unmutated_run: MagicMock, tmp_path: Path
    ) -> None:
        for gremlin_id in ('g001', 'g002', 'g003'):
            _confirm_timeout_kill(_timeout(gremlin_id), ['t.py::test_a'], session, tmp_path)

        assert fake_unmutated_run.call_count == 1

    def it_runs_each_distinct_selection_separately(
        self, session: GremlinSession, fake_unmutated_run: MagicMock, tmp_path: Path
    ) -> None:
        _confirm_timeout_kill(_timeout('g001'), ['t.py::test_a'], session, tmp_path)
        _confirm_timeout_kill(_timeout('g002'), ['t.py::test_b'], session, tmp_path)

        assert fake_unmutated_run.call_count == 2

    @pytest.mark.parametrize(
        'result',
        [
            pytest.param(
                GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.ZAPPED, killing_test='unknown'),
                id='kill',
            ),
            pytest.param(GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.SURVIVED), id='survivor'),
            pytest.param(
                GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.ERROR, error_output='boom'), id='error'
            ),
        ],
    )
    def it_leaves_every_other_verdict_alone_without_running_anything(
        self, session: GremlinSession, fake_unmutated_run: MagicMock, tmp_path: Path, result: GremlinResult
    ) -> None:
        assert _confirm_timeout_kill(result, ['t.py::test_a'], session, tmp_path) is result
        fake_unmutated_run.assert_not_called()


@pytest.mark.medium
class DescribeCachingOfDowngradedTimeouts:
    @pytest.fixture
    def cached_session(self, tmp_path: Path) -> tuple[GremlinSession, MagicMock]:
        cache = create_autospec(IncrementalCache, instance=True)
        session = GremlinSession(
            enabled=True,
            cache_enabled=True,
            cache=cache,
            source_hashes={'/path/to/source.py': 'hash'},
            instrumented_dir=tmp_path,
            mutant_timeout=TIMEOUT_SECONDS,
        )
        return session, cache

    def it_caches_a_confirmed_timeout(self, cached_session: tuple[GremlinSession, MagicMock]) -> None:
        session, cache = cached_session

        _cache_gremlin_result(_gremlin(), [], _timeout(), session)

        cache.cache_result_deferred.assert_called_once()

    def it_does_not_cache_a_timeout_downgraded_to_error(
        self,
        cached_session: tuple[GremlinSession, MagicMock],
        fake_unmutated_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        session, cache = cached_session
        fake_unmutated_run.return_value = HANGS
        downgraded = _confirm_timeout_kill(_timeout(), ['t.py::test_a'], session, tmp_path)

        _cache_gremlin_result(_gremlin(), [], downgraded, session)

        cache.cache_result_deferred.assert_not_called()
