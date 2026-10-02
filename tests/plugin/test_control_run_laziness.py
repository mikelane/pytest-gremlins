"""The unmutated control run only happens when a gremlin actually has to run (issue #550)."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

from pytest_gremlins.control_run import (
    UNATTRIBUTABLE_MARKER,
    ControlRunOutcome,
    run_control,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    GremlinSession,
    _verify_suite_loads_unmutated,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

LOADS = ControlRunOutcome(loads_cleanly=True, output='', seconds=0.1)
FAILS = ControlRunOutcome(loads_cleanly=False, output='ImportError: boom', seconds=0.1)
NODE_IDS = {'test_a': 't.py::test_a', 'test_b': 't.py::test_b', 'test_c': 't.py::test_c'}


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


@pytest.fixture
def session(tmp_path: Path) -> GremlinSession:
    return GremlinSession(
        enabled=True,
        instrumented_dir=tmp_path,
        gremlins=[_gremlin('g1'), _gremlin('g2'), _gremlin('g3')],
        test_node_ids=dict(NODE_IDS),
    )


@pytest.fixture
def control(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Stub the selection, the cache lookup and the control subprocess; return the control stub."""
    selections = {'g1': ['test_a'], 'g2': ['test_b'], 'g3': ['test_c']}
    monkeypatch.setattr(
        'pytest_gremlins.plugin._select_tests_for_gremlin_prioritized', lambda g, _s: selections[g.gremlin_id]
    )
    monkeypatch.setattr('pytest_gremlins.plugin._get_rootdir', lambda _config: tmp_path)
    stub = create_autospec(run_control, return_value=LOADS)
    monkeypatch.setattr('pytest_gremlins.plugin.run_control', stub)
    return stub


def _cache_hits(monkeypatch: pytest.MonkeyPatch, cached_ids: set[str]) -> None:
    def lookup(gremlin: Gremlin, _tests: object, _session: object) -> GremlinResult | None:
        if gremlin.gremlin_id in cached_ids:
            return GremlinResult(gremlin=gremlin, status=GremlinResultStatus.SURVIVED)
        return None

    monkeypatch.setattr('pytest_gremlins.plugin._check_cache_for_gremlin', lookup)


@pytest.mark.medium
class DescribeLazyControlRun:
    def it_spawns_nothing_and_prints_nothing_when_every_gremlin_is_cached(
        self,
        session: GremlinSession,
        control,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _cache_hits(monkeypatch, {'g1', 'g2', 'g3'})
        control.return_value = FAILS

        _verify_suite_loads_unmutated(SimpleNamespace(config=None), session)  # type: ignore[arg-type]

        control.assert_not_called()
        assert capsys.readouterr().err == ''
        assert session.load_failures_attributable is True

    def it_controls_only_the_tests_of_the_uncached_gremlins(
        self,
        session: GremlinSession,
        control,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _cache_hits(monkeypatch, {'g1'})

        _verify_suite_loads_unmutated(SimpleNamespace(config=None), session)  # type: ignore[arg-type]

        assert control.call_args.args[1] == ['t.py::test_b', 't.py::test_c']

    def it_ignores_pardoned_gremlins(
        self,
        session: GremlinSession,
        control,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _cache_hits(monkeypatch, set())
        monkeypatch.setattr(
            'pytest_gremlins.plugin._immediate_result_if_pardoned',
            lambda g: GremlinResult(gremlin=g, status=GremlinResultStatus.PARDONED) if g.gremlin_id != 'g3' else None,
        )

        _verify_suite_loads_unmutated(SimpleNamespace(config=None), session)  # type: ignore[arg-type]

        assert control.call_args.args[1] == ['t.py::test_c']

    def it_still_disables_attribution_when_an_uncached_gremlin_cannot_load(
        self,
        session: GremlinSession,
        control,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _cache_hits(monkeypatch, {'g1', 'g2'})
        control.return_value = FAILS

        _verify_suite_loads_unmutated(SimpleNamespace(config=None), session)  # type: ignore[arg-type]

        assert session.load_failures_attributable is False
        assert (tmp_path / UNATTRIBUTABLE_MARKER).exists()
        assert capsys.readouterr().err.count('fails to load in the gremlin subprocess') == 1
