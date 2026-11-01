"""Distinct collection-kill confirmations run concurrently before scoring (issue #553)."""

from __future__ import annotations

import ast
import threading
import time
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
    ControlRunOutcome,
    run_control,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.exit_codes import COLLECTION_KILLING_TEST
from pytest_gremlins.plugin import (
    GremlinSession,
    _confirm_collection_kill,
    _prefill_collection_kill_confirmations,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

LOADS = ControlRunOutcome(loads_cleanly=True, output='', seconds=0.1)
FAILS = ControlRunOutcome(loads_cleanly=False, output='ImportError: nope', seconds=0.1)
SLOW_SECONDS = 0.3


def _gremlin(gremlin_id: str) -> Gremlin:
    return Gremlin(
        gremlin_id=gremlin_id,
        file_path='/path/to/source.py',
        line_number=1,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


def _kill(gremlin_id: str, killing_test: str | None = COLLECTION_KILLING_TEST) -> GremlinResult:
    return GremlinResult(gremlin=_gremlin(gremlin_id), status=GremlinResultStatus.ZAPPED, killing_test=killing_test)


def _pending(count: int) -> list[tuple[GremlinResult, list[str]]]:
    return [(_kill(f'g{index}'), [f't.py::test_{index}']) for index in range(count)]


def _session(tmp_path: Path, workers: int | None) -> GremlinSession:
    return GremlinSession(enabled=True, instrumented_dir=tmp_path, parallel_workers=workers)


@pytest.fixture
def fake_control(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    control = create_autospec(run_control, return_value=LOADS)
    monkeypatch.setattr('pytest_gremlins.plugin.run_control', control)
    return cast('MagicMock', control)


@pytest.mark.medium
class DescribePrefillCollectionKillConfirmations:
    def it_runs_distinct_confirmations_in_about_n_over_workers_times_one_run(
        self, fake_control: MagicMock, tmp_path: Path
    ) -> None:
        def slow(*_args: object, **_kwargs: object) -> ControlRunOutcome:
            time.sleep(SLOW_SECONDS)
            return LOADS

        fake_control.side_effect = slow
        session = _session(tmp_path, workers=4)

        started = time.monotonic()
        _prefill_collection_kill_confirmations(_pending(8), session, tmp_path)
        elapsed = time.monotonic() - started

        assert elapsed < SLOW_SECONDS * 8 / 2

    def it_never_runs_more_confirmations_at_once_than_the_configured_workers(
        self, fake_control: MagicMock, tmp_path: Path
    ) -> None:
        lock = threading.Lock()
        running = 0
        peak = 0

        def tracked(*_args: object, **_kwargs: object) -> ControlRunOutcome:
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with lock:
                running -= 1
            return LOADS

        fake_control.side_effect = tracked

        _prefill_collection_kill_confirmations(_pending(10), _session(tmp_path, workers=2), tmp_path)

        assert peak == 2

    def it_confirms_each_distinct_selection_once(self, fake_control: MagicMock, tmp_path: Path) -> None:
        session = _session(tmp_path, workers=4)
        pending = [(_kill('g1'), ['a']), (_kill('g2'), ['a']), (_kill('g3'), ['b'])]

        _prefill_collection_kill_confirmations(pending, session, tmp_path)

        assert (fake_control.call_count, sorted(session.unmutated_load_checks)) == (2, [('a',), ('b',)])

    def it_skips_selections_already_in_the_memo(self, fake_control: MagicMock, tmp_path: Path) -> None:
        session = _session(tmp_path, workers=4)
        session.unmutated_load_checks[('a',)] = LOADS

        _prefill_collection_kill_confirmations([(_kill('g1'), ['a'])], session, tmp_path)

        assert fake_control.call_count == 0

    def it_ignores_results_that_are_not_collection_kills(self, fake_control: MagicMock, tmp_path: Path) -> None:
        session = _session(tmp_path, workers=4)
        pending = [
            (_kill('g1', killing_test='t.py::test_x'), ['a']),
            (GremlinResult(gremlin=_gremlin('g2'), status=GremlinResultStatus.TIMEOUT), ['b']),
        ]

        _prefill_collection_kill_confirmations(pending, session, tmp_path)

        assert fake_control.call_count == 0

    def it_defaults_to_a_bounded_pool_when_workers_is_auto(self, fake_control: MagicMock, tmp_path: Path) -> None:
        session = _session(tmp_path, workers=None)

        _prefill_collection_kill_confirmations(_pending(3), session, tmp_path)

        assert fake_control.call_count == 3

    def it_leaves_verdicts_identical_to_serial_confirmation(self, fake_control: MagicMock, tmp_path: Path) -> None:
        def by_selection(_command: object, node_ids: list[str], *_args: object, **_kwargs: object) -> ControlRunOutcome:
            return FAILS if node_ids[0].endswith(('_1', '_3')) else LOADS

        fake_control.side_effect = by_selection
        pending = _pending(6)
        serial_session = _session(tmp_path, workers=None)
        prefilled_session = _session(tmp_path, workers=3)

        serial = [_confirm_collection_kill(r, ids, serial_session, tmp_path) for r, ids in pending]
        _prefill_collection_kill_confirmations(pending, prefilled_session, tmp_path)
        prefilled = [_confirm_collection_kill(r, ids, prefilled_session, tmp_path) for r, ids in pending]

        assert [(r.status, r.killing_test) for r in prefilled] == [(r.status, r.killing_test) for r in serial]
        assert [r.status for r in prefilled].count(GremlinResultStatus.ERROR) == 2


@pytest.mark.medium
class DescribePrefillInterruption:
    @pytest.mark.parametrize('error', [KeyboardInterrupt, RuntimeError])
    def it_starts_no_further_confirmations_once_one_is_interrupted_or_fails(
        self, fake_control: MagicMock, tmp_path: Path, error: type[BaseException]
    ) -> None:
        fake_control.side_effect = error('stop')

        with pytest.raises(error):
            _prefill_collection_kill_confirmations(_pending(6), _session(tmp_path, workers=1), tmp_path)

        assert fake_control.call_count == 1
