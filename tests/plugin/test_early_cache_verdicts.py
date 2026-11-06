"""Which pooled verdicts are final when a worker returns them, and so safe to cache at once (issue #974)."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.exit_codes import COLLECTION_KILLING_TEST
from pytest_gremlins.plugin import (
    GremlinSession,
    _verdict_is_final,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.verdicts import _confirm_pooled_result


def _result(status: GremlinResultStatus, killing_test: str | None = None) -> GremlinResult:
    gremlin = Gremlin(
        gremlin_id='g001',
        file_path='/path/to/source.py',
        line_number=1,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )
    return GremlinResult(gremlin=gremlin, status=status, killing_test=killing_test)


_FINAL_RESULTS = [
    pytest.param(GremlinResultStatus.SURVIVED, None, id='survived'),
    pytest.param(GremlinResultStatus.ZAPPED, 'tests/test_a.py::test_a', id='zapped-by-a-test'),
    pytest.param(GremlinResultStatus.ERROR, None, id='error'),
    pytest.param(GremlinResultStatus.PARDONED, None, id='pardoned'),
]

_PENDING_RESULTS = [
    pytest.param(GremlinResultStatus.TIMEOUT, None, id='timeout'),
    pytest.param(GremlinResultStatus.ZAPPED, COLLECTION_KILLING_TEST, id='collection-kill'),
]


@pytest.mark.small
class DescribeVerdictIsFinal:
    @pytest.mark.parametrize(('status', 'killing_test'), _FINAL_RESULTS)
    def it_accepts_verdicts_the_confirmation_never_changes(
        self, status: GremlinResultStatus, killing_test: str | None
    ) -> None:
        assert _verdict_is_final(_result(status, killing_test)) is True

    @pytest.mark.parametrize(('status', 'killing_test'), _PENDING_RESULTS)
    def it_rejects_verdicts_the_confirmation_may_change(
        self, status: GremlinResultStatus, killing_test: str | None
    ) -> None:
        assert _verdict_is_final(_result(status, killing_test)) is False

    def it_classifies_every_status(self) -> None:
        classified = {param.values[0] for param in [*_FINAL_RESULTS, *_PENDING_RESULTS]}

        assert classified == set(GremlinResultStatus)

    @pytest.mark.parametrize(('status', 'killing_test'), _FINAL_RESULTS)
    def it_agrees_with_the_confirmation_which_returns_final_verdicts_untouched(
        self, status: GremlinResultStatus, killing_test: str | None
    ) -> None:
        result = _result(status, killing_test)
        session = create_autospec(GremlinSession, instance=True)

        confirmed = _confirm_pooled_result(result, [], [], session, Path())

        assert confirmed is result
