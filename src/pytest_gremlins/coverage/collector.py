"""CoverageCollector for gathering coverage data per-test.

The CoverageCollector integrates with coverage.py to record which source
lines are executed by each test. This data feeds into the CoverageMap
for coverage-guided test selection.

Example:
    >>> collector = CoverageCollector()
    >>> collector.record_test_coverage('test_login', {'src/auth.py': [10, 11]})
    >>> collector.coverage_map.get_tests('src/auth.py', 10)
    {'test_login'}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from pytest_gremlins.coverage.mapper import CoverageMap


if TYPE_CHECKING:
    from collections.abc import Iterable


class CoverageDataProtocol(Protocol):
    """Protocol for coverage.py's CoverageData interface.

    This protocol defines the subset of coverage.py's CoverageData
    that we use, allowing type checking without a hard dependency.
    """

    def measured_files(self) -> Iterable[str]:
        """Return an iterable of file paths that have coverage data."""
        ...

    def lines(self, filename: str) -> Iterable[int] | None:
        """Return the lines covered for a file, or None if not measured."""
        ...


class CoverageCollector:
    """Collects coverage data per-test for coverage-guided test selection.

    This class records which source lines are executed during each test,
    building a CoverageMap that can be used to select relevant tests for
    each gremlin location.

    Attributes:
        coverage_map: The CoverageMap storing line-to-test mappings.
        recorded_tests: Set of test names that have been recorded.
    """

    def __init__(self) -> None:
        """Create a new coverage collector."""
        self.coverage_map = CoverageMap()
        self.recorded_tests: set[str] = set()
        self._total_mappings = 0

    def record_test_coverage(
        self,
        test_name: str,
        coverage_data: dict[str, list[int]],
    ) -> None:
        """Record coverage data for a single test.

        Args:
            test_name: Name of the test function.
            coverage_data: Dict mapping file paths to lists of line numbers.
        """
        self.recorded_tests.add(test_name)
        for file_path, lines in coverage_data.items():
            for line_number in lines:
                self.coverage_map.add(file_path, line_number, test_name)
                self._total_mappings += 1

    def extract_lines_from_coverage_data(
        self,
        coverage_data: CoverageDataProtocol,
    ) -> dict[str, list[int]]:
        """Extract line coverage from coverage.py's CoverageData object.

        Args:
            coverage_data: A coverage.py CoverageData object.

        Returns:
            Dict mapping file paths to lists of covered line numbers.
        """
        result: dict[str, list[int]] = {}
        for file_path in coverage_data.measured_files():
            lines = coverage_data.lines(file_path)
            if lines:
                result[file_path] = list(lines)
        return result

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about collected coverage data.

        Returns:
            Dict with keys:
                - total_tests: Number of tests recorded
                - total_locations: Number of unique source locations
                - total_mappings: Total number of test-to-location mappings
        """
        return {
            'total_tests': len(self.recorded_tests),
            'total_locations': len(self.coverage_map),
            'total_mappings': self._total_mappings,
        }
