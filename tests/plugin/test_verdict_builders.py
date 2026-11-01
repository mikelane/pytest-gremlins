"""The helpers that build a gremlin's verdict live in ``verdicts.py`` (issue #875).

The cache-version guard hashes ``verdicts.py`` and not ``plugin.py``, so every place that builds a
``GremlinResult`` from a launch failure, a worker result or a cached row must be here.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.control_run import (
    SELECTION_FAILS_TO_LOAD_PREFIX,
    TIMEOUT_CONFIRMATION_LAUNCH_ERROR_PREFIX,
)
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.lightweight import REWRITE_API_BROKEN_PREFIX
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import (
    TIMEOUT_NOT_CONFIRMED_PREFIX,
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.verdicts import (
    _cache_row_from_result,
    _is_cacheable,
    _launch_failure_result,
    _node_ids_write_failure_output,
    _result_from_cached_row,
    _result_from_worker,
)

if TYPE_CHECKING:
    from pytest_gremlins.cache.types import CachedGremlinResult


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


@pytest.mark.small
class DescribeLaunchFailureResult:
    def it_is_an_error_naming_the_write_failure_and_keeping_the_selection(self) -> None:
        gremlin = _gremlin()

        result = _launch_failure_result(gremlin, OSError('disk full'), ['t.py::test_a'])

        assert result == GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.ERROR,
            error_output='Could not write the node ids file for the gremlin test command: disk full',
            selected_tests=['t.py::test_a'],
        )

    def it_truncates_the_message_to_two_thousand_characters(self) -> None:
        assert len(_node_ids_write_failure_output(OSError('x' * 5000))) == 2000


@pytest.mark.small
class DescribeResultFromWorker:
    def it_carries_every_worker_field_and_the_selection(self) -> None:
        gremlin = _gremlin()
        worker = WorkerResult(
            gremlin_id='g001',
            status=GremlinResultStatus.ZAPPED,
            killing_test='t.py::test_a',
            execution_time_ms=12.5,
            error_output='boom',
        )

        result = _result_from_worker(gremlin, worker, ['t.py::test_a'])

        assert result == GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.ZAPPED,
            killing_test='t.py::test_a',
            execution_time_ms=12.5,
            error_output='boom',
            selected_tests=['t.py::test_a'],
        )

    def it_keeps_a_launch_failure_error_as_an_error(self) -> None:
        worker = WorkerResult(gremlin_id='g001', status=GremlinResultStatus.ERROR, error_output='no file')

        assert _result_from_worker(_gremlin(), worker, []).status == GremlinResultStatus.ERROR


@pytest.mark.small
class DescribeResultFromCachedRow:
    def it_rebuilds_the_result_from_every_cached_field(self) -> None:
        gremlin = _gremlin()
        row: CachedGremlinResult = {
            'status': 'zapped',
            'killing_test': 't.py::test_a',
            'execution_time_ms': 3.0,
            'error_output': 'e',
        }

        assert _result_from_cached_row(gremlin, row) == GremlinResult(
            gremlin=gremlin,
            status=GremlinResultStatus.ZAPPED,
            killing_test='t.py::test_a',
            execution_time_ms=3.0,
            error_output='e',
        )

    def it_defaults_a_missing_error_output_to_empty(self) -> None:
        row: CachedGremlinResult = {'status': 'survived', 'killing_test': None, 'execution_time_ms': None}

        assert _result_from_cached_row(_gremlin(), row).error_output == ''


@pytest.mark.small
class DescribeIsCacheable:
    @pytest.mark.parametrize(
        'prefix',
        [
            SELECTION_FAILS_TO_LOAD_PREFIX,
            TIMEOUT_NOT_CONFIRMED_PREFIX,
            TIMEOUT_CONFIRMATION_LAUNCH_ERROR_PREFIX,
            REWRITE_API_BROKEN_PREFIX,
        ],
        ids=['selection-fails-to-load', 'timeout-not-confirmed', 'timeout-launch-error', 'rewrite-api-broken'],
    )
    def it_refuses_a_verdict_downgraded_for_a_harness_problem(self, prefix: str) -> None:
        result = GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.ERROR, error_output=f'{prefix} detail')

        assert _is_cacheable(result, load_failures_attributable=True) is False

    def it_accepts_an_ordinary_error(self) -> None:
        result = GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.ERROR, error_output='plain failure')

        assert _is_cacheable(result, load_failures_attributable=True) is True

    def it_accepts_a_result_with_no_error_output(self) -> None:
        assert _is_cacheable(GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.SURVIVED), True) is True

    def it_refuses_any_result_when_load_failures_are_unattributable(self) -> None:
        result = GremlinResult(gremlin=_gremlin(), status=GremlinResultStatus.ZAPPED)

        assert _is_cacheable(result, load_failures_attributable=False) is False


@pytest.mark.small
class DescribeCacheRowFromResult:
    def it_records_the_status_value_and_every_result_field(self) -> None:
        result = GremlinResult(
            gremlin=_gremlin(),
            status=GremlinResultStatus.ZAPPED,
            killing_test='t.py::test_a',
            execution_time_ms=4.0,
            error_output='e',
        )

        assert _cache_row_from_result(result) == {
            'status': 'zapped',
            'killing_test': 't.py::test_a',
            'execution_time_ms': 4.0,
            'error_output': 'e',
        }

    def it_round_trips_through_the_cached_row_rebuild(self) -> None:
        gremlin = _gremlin()
        result = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.TIMEOUT, execution_time_ms=9.0)

        assert _result_from_cached_row(gremlin, _cache_row_from_result(result)) == result
