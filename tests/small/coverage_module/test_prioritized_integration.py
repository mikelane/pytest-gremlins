"""Tests for prioritized selector integration with the plugin.

These tests verify that the plugin uses prioritized test selection
when building filtered test commands.
"""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.coverage.mapper import CoverageMap
from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.instrumentation.gremlin import Gremlin


class TestPrioritizedSelectorCompatibility:
    """Test that PrioritizedSelector can replace TestSelector in plugin usage."""

    @pytest.fixture
    def coverage_map(self):
        """Create a coverage map with tests of varying specificity."""
        cm = CoverageMap()
        # test_specific covers only line 42
        cm.add('src/auth.py', 42, 'test_specific')
        # test_medium covers lines 42-44
        for line in range(42, 45):
            cm.add('src/auth.py', line, 'test_medium')
        # test_broad covers lines 42-51
        for line in range(42, 52):
            cm.add('src/auth.py', line, 'test_broad')
        return cm

    @pytest.fixture
    def sample_gremlin(self):
        """Create a sample gremlin at line 42."""
        return Gremlin(
            gremlin_id='g001',
            file_path='src/auth.py',
            line_number=42,
            original_node=ast.parse('a < b', mode='eval').body,
            mutated_node=ast.parse('a <= b', mode='eval').body,
            operator_name='comparison',
            description='< to <=',
        )

    def test_prioritized_selector_provides_ordered_list_for_command_building(
        self,
        coverage_map,
        sample_gremlin,
    ):
        """Verify prioritized selection returns a list (not set) for command ordering."""
        selector = PrioritizedSelector(coverage_map)
        result = selector.select_tests_prioritized(sample_gremlin)

        # Must be a list to preserve ordering in command building
        assert isinstance(result, list)
        # First test should be most specific
        assert result[0] == 'test_specific'

    def test_prioritized_selector_result_can_be_used_for_node_id_lookup(
        self,
        coverage_map,
        sample_gremlin,
    ):
        """Verify result can be used to look up node IDs (like plugin does)."""
        selector = PrioritizedSelector(coverage_map)
        result = selector.select_tests_prioritized(sample_gremlin)

        # Simulate what plugin does: look up node IDs for selected tests
        test_node_ids = {
            'test_specific': 'tests/test_auth.py::test_specific',
            'test_medium': 'tests/test_auth.py::test_medium',
            'test_broad': 'tests/test_auth.py::test_broad',
        }

        # Build command like plugin does
        node_ids = [test_node_ids[test_name] for test_name in result if test_name in test_node_ids]

        # Ordering should be preserved: most specific first
        assert node_ids[0] == 'tests/test_auth.py::test_specific'
        assert node_ids[1] == 'tests/test_auth.py::test_medium'
        assert node_ids[2] == 'tests/test_auth.py::test_broad'
