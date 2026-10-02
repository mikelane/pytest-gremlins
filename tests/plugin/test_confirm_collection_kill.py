"""A collection kill is confirmed against the gremlin's own selection before it is scored (issue #550)."""

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
    ControlRunOutcome,
    run_control,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.exit_codes import COLLECTION_KILLING_TEST
from pytest_gremlins.plugin import (
    GremlinSession,
    _cache_gremlin_result,
    _confirm_collection_kill,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

LOADS = ControlRunOutcome(loads_cleanly=True, output='', seconds=0.1)
FAILS = ControlRunOutcome(loads_cleanly=False, output='ImportError: no module named helperlib', seconds=0.1)


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


def _collection_kill(gremlin_id: str = 'g001') -> GremlinResult:
    return GremlinResult(
        gremlin=_gremlin(gremlin_id), status=GremlinResultStatus.ZAPPED, killing_test=COLLECTION_KILLING_TEST
    )


@pytest.fixture
def session(tmp_path: Path) -> GremlinSession:
    return GremlinSession(enabled=True, instrumented_dir=tmp_path)


@pytest.fixture
def fake_control(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    control = create_autospec(run_control, return_value=LOADS)
    monkeypatch.setattr('pytest_gremlins.plugin.run_control', control)
    return control


@pytest.mark.medium
class DescribeConfirmCollectionKill:
    @pytest.mark.usefixtures('fake_control')
    def it_keeps_a_kill_when_the_unmutated_selection_loads(self, session: GremlinSession, tmp_path: Path) -> None:
        result = _confirm_collection_kill(_collection_kill(), ['t.py::test_a'], session, tmp_path)

        assert (result.status, result.killing_test) == (GremlinResultStatus.ZAPPED, COLLECTION_KILLING_TEST)

    def it_downgrades_a_kill_to_error_when_the_unmutated_selection_fails_to_load(
        self, session: GremlinSession, fake_control: MagicMock, tmp_path: Path
    ) -> None:
        fake_control.return_value = FAILS

        result = _confirm_collection_kill(_collection_kill(), ['t.py::test_b'], session, tmp_path)

        assert result.status == GremlinResultStatus.ERROR
        assert result.killing_test is None
        assert 'helperlib' in (result.error_output or '')

    def it_checks_the_exact_node_ids_of_the_selection(
        self, session: GremlinSession, fake_control: MagicMock, tmp_path: Path
    ) -> None:
        _confirm_collection_kill(_collection_kill(), ['t.py::test_b', 't.py::test_a'], session, tmp_path)

        assert fake_control.call_args.args[1] == ['t.py::test_b', 't.py::test_a']

    def it_checks_each_distinct_selection_once(
        self, session: GremlinSession, fake_control: MagicMock, tmp_path: Path
    ) -> None:
        for gremlin_id in ('g001', 'g002', 'g003'):
            _confirm_collection_kill(_collection_kill(gremlin_id), ['t.py::test_a'], session, tmp_path)
        _confirm_collection_kill(_collection_kill('g004'), ['t.py::test_b'], session, tmp_path)

        assert fake_control.call_count == 2

    def it_treats_the_same_node_ids_in_another_order_as_one_selection(
        self, session: GremlinSession, fake_control: MagicMock, tmp_path: Path
    ) -> None:
        _confirm_collection_kill(_collection_kill('g001'), ['a', 'b'], session, tmp_path)
        _confirm_collection_kill(_collection_kill('g002'), ['b', 'a'], session, tmp_path)

        assert fake_control.call_count == 1

    @pytest.mark.parametrize(
        'result',
        [
            pytest.param(
                GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.ZAPPED, killing_test='unknown'),
                id='ordinary-kill',
            ),
            pytest.param(GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.SURVIVED), id='survivor'),
            pytest.param(
                GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.ERROR, error_output='boom'), id='error'
            ),
        ],
    )
    def it_leaves_every_other_verdict_alone_without_running_anything(
        self, session: GremlinSession, fake_control: MagicMock, tmp_path: Path, result: GremlinResult
    ) -> None:
        assert _confirm_collection_kill(result, ['t.py::test_a'], session, tmp_path) is result
        fake_control.assert_not_called()


@pytest.mark.medium
class DescribeCachingOfUnattributableVerdicts:
    @pytest.fixture
    def cached_session(self, tmp_path: Path) -> tuple[GremlinSession, MagicMock]:
        cache = create_autospec(IncrementalCache, instance=True)
        session = GremlinSession(
            enabled=True,
            cache_enabled=True,
            cache=cache,
            source_hashes={'/path/to/source.py': 'hash'},
            instrumented_dir=tmp_path,
        )
        return session, cache

    def it_caches_an_ordinary_verdict(self, cached_session: tuple[GremlinSession, MagicMock]) -> None:
        session, cache = cached_session

        _cache_gremlin_result(_gremlin(), [], _collection_kill(), session)

        cache.cache_result_deferred.assert_called_once()

    def it_does_not_cache_a_kill_downgraded_to_error(
        self,
        cached_session: tuple[GremlinSession, MagicMock],
        fake_control: MagicMock,
        tmp_path: Path,
    ) -> None:
        session, cache = cached_session
        fake_control.return_value = FAILS
        downgraded = _confirm_collection_kill(_collection_kill(), ['t.py::test_b'], session, tmp_path)

        _cache_gremlin_result(_gremlin(), [], downgraded, session)

        cache.cache_result_deferred.assert_not_called()

    def it_does_not_cache_any_verdict_once_load_failures_are_unattributable(
        self, cached_session: tuple[GremlinSession, MagicMock]
    ) -> None:
        session, cache = cached_session
        session.load_failures_attributable = False

        _cache_gremlin_result(_gremlin(), [], _collection_kill(), session)

        cache.cache_result_deferred.assert_not_called()
