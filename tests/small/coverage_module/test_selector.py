"""Tests for the TestSelector that chooses tests for a gremlin."""

from __future__ import annotations

import ast

import pytest

from pytest_gremlins.coverage.mapper import CoverageMap
from pytest_gremlins.coverage.selector import TestSelector as Selector
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
def coverage_map():
    """Create a CoverageMap with test data."""
    cm = CoverageMap()
    cm.add('src/auth.py', 42, 'test_login_success')
    cm.add('src/auth.py', 42, 'test_login_failure')
    cm.add('src/auth.py', 100, 'test_register')
    cm.add('src/shipping.py', 17, 'test_calculate_shipping')
    return cm


@pytest.fixture
def selector(coverage_map):
    """Create a Selector with the test coverage map."""
    return Selector(coverage_map)


class TestSelectorCreation:
    """Test Selector initialization."""

    def test_selector_stores_coverage_map(self, coverage_map):
        selector = Selector(coverage_map)
        assert selector.coverage_map is coverage_map


class TestSelectorSelectTests:
    """Test selecting tests for a gremlin."""

    def test_select_tests_returns_matching_tests(self, selector, sample_gremlin):
        result = selector.select_tests(sample_gremlin)
        assert result == {'test_login_success', 'test_login_failure'}

    def test_select_tests_returns_empty_for_uncovered_gremlin(self, selector):
        gremlin = Gremlin(
            gremlin_id='g999',
            file_path='src/unknown.py',
            line_number=1,
            original_node=ast.parse('x', mode='eval').body,
            mutated_node=ast.parse('y', mode='eval').body,
            operator_name='test',
            description='test',
        )
        result = selector.select_tests(gremlin)
        assert result == set()

    def test_select_tests_uses_file_path_and_line_from_gremlin(self, coverage_map):
        selector = Selector(coverage_map)
        gremlin = Gremlin(
            gremlin_id='g002',
            file_path='src/shipping.py',
            line_number=17,
            original_node=ast.parse('x', mode='eval').body,
            mutated_node=ast.parse('y', mode='eval').body,
            operator_name='test',
            description='test',
        )
        result = selector.select_tests(gremlin)
        assert result == {'test_calculate_shipping'}


class TestSelectorSelectTestsForLocation:
    """Test selecting tests using file path and line number directly."""

    def test_select_tests_for_location_returns_matching_tests(self, selector):
        result = selector.select_tests_for_location('src/auth.py', 42)
        assert result == {'test_login_success', 'test_login_failure'}

    def test_select_tests_for_location_returns_empty_for_unknown(self, selector):
        result = selector.select_tests_for_location('unknown.py', 999)
        assert result == set()


class TestSelectorBatchSelection:
    """Test selecting tests for multiple gremlins."""

    def test_select_tests_for_gremlins_returns_all_matching_tests(self, selector):
        gremlins = [
            Gremlin(
                gremlin_id='g001',
                file_path='src/auth.py',
                line_number=42,
                original_node=ast.parse('x', mode='eval').body,
                mutated_node=ast.parse('y', mode='eval').body,
                operator_name='test',
                description='test',
            ),
            Gremlin(
                gremlin_id='g002',
                file_path='src/shipping.py',
                line_number=17,
                original_node=ast.parse('x', mode='eval').body,
                mutated_node=ast.parse('y', mode='eval').body,
                operator_name='test',
                description='test',
            ),
        ]
        result = selector.select_tests_for_gremlins(gremlins)
        assert result == {
            'test_login_success',
            'test_login_failure',
            'test_calculate_shipping',
        }

    def test_select_tests_for_gremlins_deduplicates(self, selector):
        gremlins = [
            Gremlin(
                gremlin_id='g001',
                file_path='src/auth.py',
                line_number=42,
                original_node=ast.parse('x', mode='eval').body,
                mutated_node=ast.parse('y', mode='eval').body,
                operator_name='test',
                description='test',
            ),
            Gremlin(
                gremlin_id='g002',
                file_path='src/auth.py',
                line_number=42,  # Same location
                original_node=ast.parse('x', mode='eval').body,
                mutated_node=ast.parse('y', mode='eval').body,
                operator_name='different',
                description='different',
            ),
        ]
        result = selector.select_tests_for_gremlins(gremlins)
        assert result == {'test_login_success', 'test_login_failure'}


class TestSelectorStats:
    """Test selector statistics."""

    def test_get_selection_stats_empty_result(self, selector):
        gremlin = Gremlin(
            gremlin_id='g999',
            file_path='unknown.py',
            line_number=1,
            original_node=ast.parse('x', mode='eval').body,
            mutated_node=ast.parse('y', mode='eval').body,
            operator_name='test',
            description='test',
        )
        tests, stats = selector.select_tests_with_stats(gremlin)
        assert tests == set()
        assert stats['selected_count'] == 0
        assert stats['coverage_location'] == 'unknown.py:1'

    def test_get_selection_stats_with_matches(self, selector, sample_gremlin):
        tests, stats = selector.select_tests_with_stats(sample_gremlin)
        assert tests == {'test_login_success', 'test_login_failure'}
        assert stats['selected_count'] == 2
        assert stats['coverage_location'] == 'src/auth.py:42'
