"""Tests for source-code diff utilities."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.reporting.diff import (
    _compute_diff,
    _node_to_source,
)


@pytest.mark.small
class DescribeNodeToSource:
    def it_returns_source_string_for_valid_node(self):
        node = ast.parse('x + 1', mode='eval').body
        assert _node_to_source(node) == 'x + 1'

    def it_returns_empty_string_when_unparsing_fails(self):
        node = ast.parse('x + 1', mode='eval').body
        del node.left  # break the node so ast.unparse raises
        assert _node_to_source(node) == ''


@pytest.mark.small
class DescribeComputeDiff:
    def it_returns_empty_list_for_identical_strings(self):
        assert _compute_diff('x + 1', 'x + 1') == []

    def it_returns_diff_lines_for_changed_strings(self):
        lines = _compute_diff('x + 1', 'x + 2')
        assert any('-' in line for line in lines)
        assert any('+' in line for line in lines)
