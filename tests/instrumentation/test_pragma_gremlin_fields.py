"""Tests for pardoned fields on the Gremlin dataclass."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin


@pytest.mark.small
class DescribeGremlinPardonedFields:
    """Tests for pardoned and pardon_reason fields on Gremlin."""

    def it_defaults_pardoned_to_false(self):
        g = Gremlin(
            gremlin_id='g001',
            file_path='example.py',
            line_number=1,
            original_node=ast.parse('a < b', mode='eval').body,
            mutated_node=ast.parse('a <= b', mode='eval').body,
            operator_name='comparison',
            description='< to <=',
        )
        assert g.pardoned is False

    def it_defaults_pardon_reason_to_none(self):
        g = Gremlin(
            gremlin_id='g001',
            file_path='example.py',
            line_number=1,
            original_node=ast.parse('a < b', mode='eval').body,
            mutated_node=ast.parse('a <= b', mode='eval').body,
            operator_name='comparison',
            description='< to <=',
        )
        assert g.pardon_reason is None

    def it_accepts_pardoned_true(self):
        g = Gremlin(
            gremlin_id='g001',
            file_path='example.py',
            line_number=1,
            original_node=ast.parse('a < b', mode='eval').body,
            mutated_node=ast.parse('a <= b', mode='eval').body,
            operator_name='comparison',
            description='< to <=',
            pardoned=True,
            pardon_reason='equivalent: floor division is integer arithmetic',
        )
        assert g.pardoned is True
        assert g.pardon_reason == 'equivalent: floor division is integer arithmetic'

    def it_remains_immutable_with_pardoned_field(self):
        g = Gremlin(
            gremlin_id='g001',
            file_path='example.py',
            line_number=1,
            original_node=ast.parse('a < b', mode='eval').body,
            mutated_node=ast.parse('a <= b', mode='eval').body,
            operator_name='comparison',
            description='< to <=',
        )
        with pytest.raises(AttributeError):
            g.pardoned = True  # type: ignore[misc]
