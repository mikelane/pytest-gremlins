"""Tests for the Gremlin dataclass that represents a mutation."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin


@pytest.fixture
def sample_gremlin():
    return Gremlin(
        gremlin_id='g001',
        file_path='example.py',
        line_number=10,
        original_node=ast.parse('a < b', mode='eval').body,
        mutated_node=ast.parse('a <= b', mode='eval').body,
        operator_name='comparison',
        description='< to <=',
    )


class TestGremlinCreation:
    """Test Gremlin dataclass creation and attributes."""

    def test_gremlin_stores_id(self, sample_gremlin):
        assert sample_gremlin.gremlin_id == 'g001'

    def test_gremlin_stores_file_path(self, sample_gremlin):
        assert sample_gremlin.file_path == 'example.py'

    def test_gremlin_stores_line_number(self, sample_gremlin):
        assert sample_gremlin.line_number == 10

    def test_gremlin_stores_operator_name(self, sample_gremlin):
        assert sample_gremlin.operator_name == 'comparison'

    def test_gremlin_stores_description(self, sample_gremlin):
        assert sample_gremlin.description == '< to <='

    def test_gremlin_is_immutable(self, sample_gremlin):
        with pytest.raises(AttributeError):
            sample_gremlin.gremlin_id = 'g002'
