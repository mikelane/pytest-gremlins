"""Shared fixtures for reporting tests.

Provides factory fixtures for creating test gremlins and results,
eliminating duplication across reporting test modules.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
import dataclasses

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)

# Type aliases for factory fixture return types
MakeGremlinFactory = Callable[..., Gremlin]
MakeResultFactory = Callable[..., GremlinResult]


@pytest.fixture
def make_gremlin() -> MakeGremlinFactory:
    """Factory fixture for creating test gremlins.

    Supports all parameters needed across reporting tests:
    file_path, line_number, column_offset, end_line_number,
    end_column_offset, operator_name, and description.
    """
    counter = 0

    def _make_gremlin(
        file_path: str = 'test.py',
        line_number: int = 1,
        column_offset: int = 0,
        end_line_number: int | None = None,
        end_column_offset: int | None = None,
        operator_name: str = 'comparison',
        description: str = '>= to >',
    ) -> Gremlin:
        nonlocal counter
        counter += 1
        node = ast.parse('x >= 0', mode='eval').body
        node.lineno = line_number
        node.col_offset = column_offset
        node.end_lineno = end_line_number or line_number
        node.end_col_offset = end_column_offset or (column_offset + 6)
        return Gremlin(
            gremlin_id=f'g{counter:03d}',
            file_path=file_path,
            line_number=line_number,
            original_node=node,
            mutated_node=ast.parse('x > 0', mode='eval').body,
            operator_name=operator_name,
            description=description,
        )

    return _make_gremlin


@pytest.fixture
def make_result(make_gremlin: MakeGremlinFactory) -> MakeResultFactory:
    """Factory fixture for creating test results.

    Supports all parameters needed across reporting tests:
    status, file_path, line_number, operator_name, description,
    killing_test, execution_time_ms, and selected_tests.
    """

    def _make_result(
        status: GremlinResultStatus = GremlinResultStatus.ZAPPED,
        file_path: str = 'test.py',
        line_number: int = 1,
        operator_name: str = 'comparison',
        description: str = '>= to >',
        killing_test: str | None = None,
        execution_time_ms: float | None = None,
        pardon_reason: str | None = None,
        error_output: str = '',
        selected_tests: list[str] | None = None,
    ) -> GremlinResult:
        gremlin = make_gremlin(
            file_path=file_path,
            line_number=line_number,
            operator_name=operator_name,
            description=description,
        )
        if status == GremlinResultStatus.PARDONED:
            gremlin = dataclasses.replace(
                gremlin,
                pardoned=True,
                pardon_reason=pardon_reason or 'equivalent: default test reason',
            )
        return GremlinResult(
            gremlin=gremlin,
            status=status,
            killing_test=killing_test,
            execution_time_ms=execution_time_ms,
            error_output=error_output,
            selected_tests=selected_tests if selected_tests is not None else [],
        )

    return _make_result
