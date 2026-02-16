"""Tests for the CoverageMap class that maps source locations to tests."""

from __future__ import annotations

import pytest

from pytest_gremlins.coverage.mapper import CoverageMap


@pytest.fixture
def coverage_map():
    """Create an empty CoverageMap for testing."""
    return CoverageMap()


class TestCoverageMapCreation:
    """Test CoverageMap creation and basic operations."""

    def test_empty_coverage_map_has_no_mappings(self, coverage_map):
        assert len(coverage_map) == 0


class TestCoverageMapAddCoverage:
    """Test adding coverage data to the map."""

    def test_add_single_test_for_line(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login_success')
        assert len(coverage_map) == 1

    def test_add_multiple_tests_for_same_line(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login_success')
        coverage_map.add('src/auth.py', 42, 'test_login_failure')
        assert len(coverage_map) == 1  # Still one location

    def test_add_tests_for_different_lines(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login_success')
        coverage_map.add('src/shipping.py', 17, 'test_calculate_shipping')
        assert len(coverage_map) == 2


class TestCoverageMapGetTests:
    """Test retrieving tests for a source location."""

    def test_get_tests_returns_empty_set_for_unknown_location(self, coverage_map):
        result = coverage_map.get_tests('nonexistent.py', 1)
        assert result == set()

    def test_get_tests_returns_single_test(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login_success')
        result = coverage_map.get_tests('src/auth.py', 42)
        assert result == {'test_login_success'}

    def test_get_tests_returns_multiple_tests(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login_success')
        coverage_map.add('src/auth.py', 42, 'test_login_failure')
        result = coverage_map.get_tests('src/auth.py', 42)
        assert result == {'test_login_success', 'test_login_failure'}

    def test_get_tests_returns_copy_not_internal_set(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login_success')
        result = coverage_map.get_tests('src/auth.py', 42)
        result.add('intruder')  # Modify the result
        assert 'intruder' not in coverage_map.get_tests('src/auth.py', 42)


class TestCoverageMapIncidentallyTested:
    """Test identification of incidentally tested code.

    "Incidentally tested" code is touched by many tests but not directly
    targeted - often utility or infrastructure code.
    """

    def test_get_incidentally_tested_returns_empty_for_empty_map(self, coverage_map):
        result = coverage_map.get_incidentally_tested(threshold=3)
        assert result == []

    def test_get_incidentally_tested_returns_empty_below_threshold(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login')
        coverage_map.add('src/auth.py', 42, 'test_logout')
        result = coverage_map.get_incidentally_tested(threshold=3)
        assert result == []

    def test_get_incidentally_tested_returns_locations_at_threshold(self, coverage_map):
        coverage_map.add('src/utils.py', 10, 'test_a')
        coverage_map.add('src/utils.py', 10, 'test_b')
        coverage_map.add('src/utils.py', 10, 'test_c')
        result = coverage_map.get_incidentally_tested(threshold=3)
        assert result == [('src/utils.py', 10, 3)]

    def test_get_incidentally_tested_returns_sorted_by_test_count(self, coverage_map):
        # Location with 3 tests
        coverage_map.add('src/utils.py', 10, 'test_a')
        coverage_map.add('src/utils.py', 10, 'test_b')
        coverage_map.add('src/utils.py', 10, 'test_c')
        # Location with 5 tests
        coverage_map.add('src/helpers.py', 5, 'test_1')
        coverage_map.add('src/helpers.py', 5, 'test_2')
        coverage_map.add('src/helpers.py', 5, 'test_3')
        coverage_map.add('src/helpers.py', 5, 'test_4')
        coverage_map.add('src/helpers.py', 5, 'test_5')
        result = coverage_map.get_incidentally_tested(threshold=3)
        assert result == [
            ('src/helpers.py', 5, 5),
            ('src/utils.py', 10, 3),
        ]


class TestCoverageMapContains:
    """Test checking if a location is in the map."""

    def test_contains_returns_false_for_unknown_location(self, coverage_map):
        assert ('nonexistent.py', 1) not in coverage_map

    def test_contains_returns_true_for_known_location(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login')
        assert ('src/auth.py', 42) in coverage_map


class TestCoverageMapLocations:
    """Test iterating over all locations in the map."""

    def test_locations_returns_empty_for_empty_map(self, coverage_map):
        assert list(coverage_map.locations()) == []

    def test_locations_returns_all_locations(self, coverage_map):
        coverage_map.add('src/auth.py', 42, 'test_login')
        coverage_map.add('src/shipping.py', 17, 'test_ship')
        result = list(coverage_map.locations())
        assert sorted(result) == [('src/auth.py', 42), ('src/shipping.py', 17)]
