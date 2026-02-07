"""Tests for the CoverageCollector that gathers coverage data per-test."""

from __future__ import annotations

from unittest.mock import MagicMock

from pytest_gremlins.coverage.collector import CoverageCollector
from pytest_gremlins.coverage.mapper import CoverageMap


class TestCoverageCollectorCreation:
    """Test CoverageCollector initialization."""

    def test_collector_creates_empty_coverage_map(self):
        collector = CoverageCollector()
        assert isinstance(collector.coverage_map, CoverageMap)
        assert len(collector.coverage_map) == 0


class TestCoverageCollectorRecording:
    """Test recording coverage data for a test."""

    def test_record_coverage_adds_lines_to_map(self):
        collector = CoverageCollector()
        coverage_data = {
            'src/auth.py': [10, 11, 12],
            'src/utils.py': [5],
        }
        collector.record_test_coverage('test_login', coverage_data)

        assert collector.coverage_map.get_tests('src/auth.py', 10) == {'test_login'}
        assert collector.coverage_map.get_tests('src/auth.py', 11) == {'test_login'}
        assert collector.coverage_map.get_tests('src/auth.py', 12) == {'test_login'}
        assert collector.coverage_map.get_tests('src/utils.py', 5) == {'test_login'}

    def test_record_coverage_multiple_tests_same_file(self):
        collector = CoverageCollector()
        collector.record_test_coverage('test_login', {'src/auth.py': [10, 11]})
        collector.record_test_coverage('test_logout', {'src/auth.py': [10, 20]})

        assert collector.coverage_map.get_tests('src/auth.py', 10) == {'test_login', 'test_logout'}
        assert collector.coverage_map.get_tests('src/auth.py', 11) == {'test_login'}
        assert collector.coverage_map.get_tests('src/auth.py', 20) == {'test_logout'}

    def test_record_coverage_empty_coverage_data(self):
        collector = CoverageCollector()
        collector.record_test_coverage('test_noop', {})
        assert len(collector.coverage_map) == 0


class TestCoverageCollectorFromCoveragePy:
    """Test converting coverage.py data format to our format."""

    def test_extract_from_coverage_data(self):
        collector = CoverageCollector()

        # Mimic coverage.py's CoverageData structure
        mock_coverage_data = MagicMock()
        mock_coverage_data.measured_files.return_value = ['src/auth.py', 'src/utils.py']
        mock_coverage_data.lines.side_effect = lambda f: {
            'src/auth.py': [10, 11, 12],
            'src/utils.py': [5, 6],
        }[f]

        result = collector.extract_lines_from_coverage_data(mock_coverage_data)

        assert result == {
            'src/auth.py': [10, 11, 12],
            'src/utils.py': [5, 6],
        }

    def test_extract_from_coverage_data_handles_none_lines(self):
        collector = CoverageCollector()

        # Mimic coverage.py's CoverageData structure where a file has no lines
        mock_coverage_data = MagicMock()
        mock_coverage_data.measured_files.return_value = ['src/auth.py', 'src/empty.py']
        mock_coverage_data.lines.side_effect = lambda f: {
            'src/auth.py': [10, 11],
            'src/empty.py': None,  # No lines recorded
        }[f]

        result = collector.extract_lines_from_coverage_data(mock_coverage_data)

        assert result == {
            'src/auth.py': [10, 11],
            # src/empty.py is excluded because lines() returned None
        }

    def test_extract_from_coverage_data_handles_empty_lines(self):
        collector = CoverageCollector()

        mock_coverage_data = MagicMock()
        mock_coverage_data.measured_files.return_value = ['src/auth.py', 'src/empty.py']
        mock_coverage_data.lines.side_effect = lambda f: {
            'src/auth.py': [10, 11],
            'src/empty.py': [],  # Empty list of lines
        }[f]

        result = collector.extract_lines_from_coverage_data(mock_coverage_data)

        assert result == {
            'src/auth.py': [10, 11],
            # src/empty.py is excluded because lines() returned empty list
        }


class TestCoverageCollectorTestTracking:
    """Test tracking which tests have been recorded."""

    def test_recorded_tests_initially_empty(self):
        collector = CoverageCollector()
        assert collector.recorded_tests == set()

    def test_recorded_tests_tracks_recorded_tests(self):
        collector = CoverageCollector()
        collector.record_test_coverage('test_login', {'src/auth.py': [10]})
        collector.record_test_coverage('test_logout', {'src/auth.py': [20]})
        assert collector.recorded_tests == {'test_login', 'test_logout'}


class TestCoverageCollectorStats:
    """Test coverage collection statistics."""

    def test_stats_empty_collector(self):
        collector = CoverageCollector()
        stats = collector.get_stats()
        assert stats['total_tests'] == 0
        assert stats['total_locations'] == 0
        assert stats['total_mappings'] == 0

    def test_stats_with_data(self):
        collector = CoverageCollector()
        collector.record_test_coverage('test_login', {'src/auth.py': [10, 11]})
        collector.record_test_coverage('test_logout', {'src/auth.py': [10, 20]})

        stats = collector.get_stats()
        assert stats['total_tests'] == 2
        assert stats['total_locations'] == 3  # lines 10, 11, 20
        assert stats['total_mappings'] == 4  # 2+1+1 mappings
