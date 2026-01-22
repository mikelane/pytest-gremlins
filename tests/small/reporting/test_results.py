"""Tests for GremlinResult dataclass that tracks mutation test outcomes."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.reporting.results import GremlinResult, GremlinResultStatus


class TestGremlinResultStatus:
    """Tests for GremlinResultStatus enum."""

    def test_status_has_zapped_value(self):
        assert GremlinResultStatus.ZAPPED.value == 'zapped'

    def test_status_has_survived_value(self):
        assert GremlinResultStatus.SURVIVED.value == 'survived'

    def test_status_has_timeout_value(self):
        assert GremlinResultStatus.TIMEOUT.value == 'timeout'

    def test_status_has_error_value(self):
        assert GremlinResultStatus.ERROR.value == 'error'


@pytest.fixture
def sample_gremlin():
    return Gremlin(
        gremlin_id='g001',
        file_path='src/auth.py',
        line_number=42,
        original_node=ast.parse('age >= 18', mode='eval').body,
        mutated_node=ast.parse('age > 18', mode='eval').body,
        operator_name='comparison',
        description='>= to >',
    )


class TestGremlinResultCreation:
    """Tests for GremlinResult dataclass creation and attributes."""

    def test_result_stores_gremlin(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        assert result.gremlin == sample_gremlin

    def test_result_stores_status(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.status == GremlinResultStatus.SURVIVED

    def test_result_stores_killing_test_when_zapped(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
            killing_test='test_age_boundary',
        )
        assert result.killing_test == 'test_age_boundary'

    def test_result_killing_test_defaults_to_none(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.killing_test is None

    def test_result_stores_execution_time(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
            execution_time_ms=42.5,
        )
        assert result.execution_time_ms == 42.5

    def test_result_execution_time_defaults_to_none(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        assert result.execution_time_ms is None

    def test_result_is_immutable(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        with pytest.raises(AttributeError):
            result.status = GremlinResultStatus.SURVIVED


class TestGremlinResultProperties:
    """Tests for computed properties on GremlinResult."""

    def test_is_zapped_returns_true_when_zapped(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        assert result.is_zapped is True

    def test_is_zapped_returns_false_when_survived(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.is_zapped is False

    def test_is_survived_returns_true_when_survived(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.SURVIVED,
        )
        assert result.is_survived is True

    def test_is_survived_returns_false_when_zapped(self, sample_gremlin):
        result = GremlinResult(
            gremlin=sample_gremlin,
            status=GremlinResultStatus.ZAPPED,
        )
        assert result.is_survived is False
