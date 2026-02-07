"""Tests for prioritized test selection that orders tests by specificity.

The PrioritizedSelector returns tests ordered by specificity (fewer lines covered
= more specific = higher priority). This enables faster gremlin detection by
running the most specific tests first with pytest's -x flag.
"""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.coverage.mapper import CoverageMap
from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.instrumentation.gremlin import Gremlin


@pytest.fixture
def sample_gremlin():
    """Create a sample gremlin for testing."""
    return Gremlin(
        gremlin_id='g001',
        file_path='src/auth.py',
        line_number=42,
        original_node=ast.parse('a < b', mode='eval').body,
        mutated_node=ast.parse('a <= b', mode='eval').body,
        operator_name='comparison',
        description='< to <=',
    )


@pytest.fixture
def coverage_map_with_specificity():
    """Create a CoverageMap where tests have different coverage breadths.

    - test_specific covers only 1 line (line 42)
    - test_medium covers 3 lines (42, 43, 44)
    - test_broad covers 10 lines (42-51)
    """
    cm = CoverageMap()
    # test_specific: covers only line 42 (most specific)
    cm.add('src/auth.py', 42, 'test_specific')

    # test_medium: covers lines 42-44 (medium specificity)
    for line in range(42, 45):
        cm.add('src/auth.py', line, 'test_medium')

    # test_broad: covers lines 42-51 (least specific)
    for line in range(42, 52):
        cm.add('src/auth.py', line, 'test_broad')

    return cm


class TestPrioritizedSelectorCreation:
    """Test PrioritizedSelector initialization."""

    def test_prioritized_selector_stores_coverage_map(self, coverage_map_with_specificity):
        selector = PrioritizedSelector(coverage_map_with_specificity)
        assert selector.coverage_map is coverage_map_with_specificity


class TestPrioritizedSelectorSelectTests:
    """Test selecting tests in priority order."""

    def test_select_tests_returns_tests_ordered_by_specificity(
        self,
        coverage_map_with_specificity,
        sample_gremlin,
    ):
        """Most specific test (fewest lines covered) returned first."""

        selector = PrioritizedSelector(coverage_map_with_specificity)
        result = selector.select_tests_prioritized(sample_gremlin)

        # Result is a list ordered by specificity (most specific first)
        assert isinstance(result, list)
        assert len(result) == 3
        # test_specific covers only 1 line -> highest priority
        assert result[0] == 'test_specific'
        # test_medium covers 3 lines -> medium priority
        assert result[1] == 'test_medium'
        # test_broad covers 10 lines -> lowest priority
        assert result[2] == 'test_broad'

    def test_select_tests_returns_empty_for_uncovered_gremlin(
        self,
        coverage_map_with_specificity,
    ):
        selector = PrioritizedSelector(coverage_map_with_specificity)
        gremlin = Gremlin(
            gremlin_id='g999',
            file_path='src/unknown.py',
            line_number=1,
            original_node=ast.parse('x', mode='eval').body,
            mutated_node=ast.parse('y', mode='eval').body,
            operator_name='test',
            description='test',
        )
        result = selector.select_tests_prioritized(gremlin)
        assert result == []

    def test_select_tests_maintains_order_stability_for_equal_specificity(
        self,
    ):
        """Tests with equal specificity maintain consistent ordering."""

        cm = CoverageMap()
        # All tests cover exactly 2 lines each
        cm.add('src/auth.py', 42, 'test_alpha')
        cm.add('src/auth.py', 43, 'test_alpha')
        cm.add('src/auth.py', 42, 'test_beta')
        cm.add('src/auth.py', 43, 'test_beta')
        cm.add('src/auth.py', 42, 'test_gamma')
        cm.add('src/auth.py', 43, 'test_gamma')

        selector = PrioritizedSelector(cm)
        gremlin = Gremlin(
            gremlin_id='g001',
            file_path='src/auth.py',
            line_number=42,
            original_node=ast.parse('x', mode='eval').body,
            mutated_node=ast.parse('y', mode='eval').body,
            operator_name='test',
            description='test',
        )

        result = selector.select_tests_prioritized(gremlin)

        # All 3 tests returned, order is stable (alphabetical for ties)
        assert len(result) == 3
        assert set(result) == {'test_alpha', 'test_beta', 'test_gamma'}
        # For equal specificity, sort alphabetically for determinism
        assert result == ['test_alpha', 'test_beta', 'test_gamma']


class TestTestSpecificityComputation:
    """Test computing test specificity (lines covered)."""

    def test_compute_specificity_returns_line_counts(self, coverage_map_with_specificity):
        selector = PrioritizedSelector(coverage_map_with_specificity)
        specificity = selector.get_test_specificity()

        # Lower number = more specific (fewer lines)
        assert specificity['test_specific'] == 1
        assert specificity['test_medium'] == 3
        assert specificity['test_broad'] == 10

    def test_compute_specificity_caches_result(self, coverage_map_with_specificity):
        selector = PrioritizedSelector(coverage_map_with_specificity)

        # First call computes
        specificity1 = selector.get_test_specificity()
        # Second call returns cached
        specificity2 = selector.get_test_specificity()

        assert specificity1 is specificity2  # Same object (cached)


class TestPrioritizedSelectorStats:
    """Test statistics from prioritized selection."""

    def test_stats_include_specificity_info(
        self,
        coverage_map_with_specificity,
        sample_gremlin,
    ):
        selector = PrioritizedSelector(coverage_map_with_specificity)
        _tests, stats = selector.select_tests_with_stats(sample_gremlin)

        assert stats['selected_count'] == 3
        assert stats['coverage_location'] == 'src/auth.py:42'
        # New stats for prioritization
        assert 'most_specific_test' in stats
        assert stats['most_specific_test'] == 'test_specific'
        assert 'specificity_range' in stats
        assert stats['specificity_range'] == (1, 10)  # min, max lines covered

    def test_stats_for_uncovered_gremlin_has_none_values(self):
        cm = CoverageMap()
        cm.add('src/auth.py', 42, 'test_something')  # Different file

        selector = PrioritizedSelector(cm)
        gremlin = Gremlin(
            gremlin_id='g999',
            file_path='src/unknown.py',
            line_number=1,
            original_node=ast.parse('x', mode='eval').body,
            mutated_node=ast.parse('y', mode='eval').body,
            operator_name='test',
            description='test',
        )

        tests, stats = selector.select_tests_with_stats(gremlin)

        assert tests == []
        assert stats['selected_count'] == 0
        assert stats['most_specific_test'] is None
        assert stats['specificity_range'] == (0, 0)
