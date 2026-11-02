"""Pooled timeouts are re-run alone, but concurrently, at most one per worker (issue #917).

The lone re-run tells pool contention apart from a real hang. Running the re-runs one after another
cost T + N*T for N hung gremlins; running up to ``parallel_workers`` of them at once costs about 2T and
oversubscribes the machine no more than the pool already did.
"""

from __future__ import annotations

import ast
import threading
from typing import (
    TYPE_CHECKING,
    cast,
)
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest

from pytest_gremlins.control_run import (
    UnmutatedRunOutcome,
    run_unmutated,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import GremlinSession
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.verdicts import (
    _confirm_pooled_results,
    _test_gremlin,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.verdicts import PooledResult

COMMAND = ['python', 'bootstrap.py', 't.py::test_a']
NODE_IDS = ['t.py::test_a']
RENDEZVOUS_SECONDS = 30
HOLD_SECONDS = 0.05


def _gremlin(index: int) -> Gremlin:
    return Gremlin(
        gremlin_id=f'g{index:03d}',
        file_path='/path/to/source.py',
        line_number=index,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


def _pooled_timeouts(count: int) -> list[PooledResult]:
    return [
        (
            GremlinResult(gremlin=_gremlin(i), status=GremlinResultStatus.TIMEOUT, selected_tests=NODE_IDS),
            COMMAND,
            NODE_IDS,
        )
        for i in range(count)
    ]


def _session(tmp_path: Path, workers: int) -> GremlinSession:
    return GremlinSession(enabled=True, instrumented_dir=tmp_path, mutant_timeout=20, parallel_workers=workers)


@pytest.fixture
def unmutated_run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    run = create_autospec(run_unmutated, return_value=UnmutatedRunOutcome(timed_out=False, seconds=0.1))
    monkeypatch.setattr('pytest_gremlins.verdicts.run_unmutated', run)
    return cast('MagicMock', run)


class _ConcurrencyProbe:
    """A stand-in for ``_test_gremlin`` that records how many re-runs overlap, and which one hung."""

    def __init__(self, status: GremlinResultStatus = GremlinResultStatus.TIMEOUT) -> None:
        self._status = status
        self._lock = threading.Lock()
        self._running = 0
        self.max_running = 0
        self.rerun_ids: list[str] = []

    def __call__(self, gremlin: Gremlin, *_args: object, **_kwargs: object) -> GremlinResult:
        with self._lock:
            self._running += 1
            self.max_running = max(self.max_running, self._running)
            self.rerun_ids.append(gremlin.gremlin_id)
        threading.Event().wait(HOLD_SECONDS)
        with self._lock:
            self._running -= 1
        return GremlinResult(gremlin=gremlin, status=self._status)


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> _ConcurrencyProbe:
    concurrency_probe = _ConcurrencyProbe()
    monkeypatch.setattr('pytest_gremlins.verdicts._test_gremlin', concurrency_probe)
    return concurrency_probe


@pytest.mark.medium
@pytest.mark.usefixtures('unmutated_run')
class DescribeConcurrentTimeoutReruns:
    def it_runs_the_lone_reruns_at_the_same_time(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        rendezvous = threading.Barrier(4, timeout=RENDEZVOUS_SECONDS)

        def meet_every_other_rerun(gremlin: Gremlin, *_args: object, **_kwargs: object) -> GremlinResult:
            rendezvous.wait()
            return GremlinResult(gremlin=gremlin, status=GremlinResultStatus.TIMEOUT)

        monkeypatch.setattr('pytest_gremlins.verdicts._test_gremlin', meet_every_other_rerun)

        results = _confirm_pooled_results(_pooled_timeouts(4), _session(tmp_path, workers=4), tmp_path)

        assert [r.status for r in results] == [GremlinResultStatus.TIMEOUT] * 4

    @pytest.mark.parametrize(('workers', 'gremlins', 'expected_peak'), [(2, 5, 2), (4, 4, 4), (8, 3, 3), (1, 3, 1)])
    def it_never_runs_more_reruns_at_once_than_the_pool_has_workers(
        self, probe: _ConcurrencyProbe, tmp_path: Path, workers: int, gremlins: int, expected_peak: int
    ) -> None:
        _confirm_pooled_results(_pooled_timeouts(gremlins), _session(tmp_path, workers), tmp_path)

        assert probe.max_running == expected_peak

    def it_returns_the_verdicts_in_the_order_it_was_given_them(self, probe: _ConcurrencyProbe, tmp_path: Path) -> None:
        pending = _pooled_timeouts(5)

        results = _confirm_pooled_results(pending, _session(tmp_path, workers=3), tmp_path)

        assert [r.gremlin.gremlin_id for r in results] == [p[0].gremlin.gremlin_id for p in pending]
        assert sorted(probe.rerun_ids) == [p[0].gremlin.gremlin_id for p in pending]

    def it_still_re_judges_every_pooled_timeout_alone(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        solo_run = create_autospec(
            _test_gremlin,
            side_effect=lambda gremlin, *_a, **_k: GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED),
        )
        monkeypatch.setattr('pytest_gremlins.verdicts._test_gremlin', solo_run)

        results = _confirm_pooled_results(_pooled_timeouts(3), _session(tmp_path, workers=3), tmp_path)

        assert [r.status for r in results] == [GremlinResultStatus.SURVIVED] * 3
        assert solo_run.call_count == 3

    def it_does_not_rerun_results_that_did_not_time_out(self, probe: _ConcurrencyProbe, tmp_path: Path) -> None:
        survivor = GremlinResult(gremlin=_gremlin(0), status=GremlinResultStatus.SURVIVED, selected_tests=NODE_IDS)

        results = _confirm_pooled_results([(survivor, COMMAND, NODE_IDS)], _session(tmp_path, workers=4), tmp_path)

        assert results == [survivor]
        assert probe.rerun_ids == []

    @pytest.mark.usefixtures('probe')
    def it_reports_a_rerun_that_hangs_again_as_a_timeout(self, tmp_path: Path) -> None:
        results = _confirm_pooled_results(_pooled_timeouts(4), _session(tmp_path, workers=4), tmp_path)

        assert [r.status for r in results] == [GremlinResultStatus.TIMEOUT] * 4
        assert [r.selected_tests for r in results] == [NODE_IDS] * 4
