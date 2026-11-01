"""The helpers that build a gremlin's verdict live in ``verdicts.py`` (issue #875).

The cache-version guard hashes ``verdicts.py`` and not ``plugin.py``, so every place that builds a
``GremlinResult`` from a launch failure, a worker result or a cached row must be here.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.verdicts import (
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
