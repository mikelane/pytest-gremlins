"""TestSelector for choosing which tests to run for a gremlin.

The TestSelector uses coverage data to select only the tests that
actually execute the code where a gremlin is located. This is the
key optimization that reduces test runs from O(gremlins * tests)
to O(gremlins * relevant_tests).

Example:
    >>> from pytest_gremlins.coverage.mapper import CoverageMap
    >>> coverage_map = CoverageMap()
    >>> coverage_map.add('src/auth.py', 42, 'test_login')
    >>> selector = TestSelector(coverage_map)
    >>> selector.select_tests_for_location('src/auth.py', 42)
    {'test_login'}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Iterable

    from pytest_gremlins.coverage.mapper import CoverageMap
    from pytest_gremlins.instrumentation.gremlin import Gremlin


class TestSelector:
    """Selects tests to run for each gremlin based on coverage data.

    Given a CoverageMap and a gremlin, the TestSelector returns only
    the tests that execute the code where the gremlin is located.

    Attributes:
        coverage_map: The CoverageMap containing line-to-test mappings.
    """

    def __init__(self, coverage_map: CoverageMap) -> None:
        """Create a TestSelector with the given coverage map.

        Args:
            coverage_map: A CoverageMap containing line-to-test mappings.
        """
        self.coverage_map = coverage_map

    def select_tests(self, gremlin: Gremlin) -> set[str]:
        """Select tests to run for a gremlin.

        Args:
            gremlin: The gremlin to select tests for.

        Returns:
            Set of test function names that cover the gremlin's location.
        """
        return self.select_tests_for_location(gremlin.file_path, gremlin.line_number)

    def select_tests_for_location(
        self,
        file_path: str,
        line_number: int,
    ) -> set[str]:
        """Select tests that cover a specific source location.

        Args:
            file_path: Path to the source file.
            line_number: Line number in the source file.

        Returns:
            Set of test function names that cover this location.
        """
        return self.coverage_map.get_tests(file_path, line_number)

    def select_tests_for_gremlins(
        self,
        gremlins: Iterable[Gremlin],
    ) -> set[str]:
        """Select all tests needed to cover a collection of gremlins.

        This is useful for batch operations where you want to find
        all tests needed to evaluate multiple gremlins.

        Args:
            gremlins: Collection of gremlins to select tests for.

        Returns:
            Set of all test function names that cover any of the gremlins.
        """
        result: set[str] = set()
        for gremlin in gremlins:
            result.update(self.select_tests(gremlin))
        return result

    def select_tests_with_stats(
        self,
        gremlin: Gremlin,
    ) -> tuple[set[str], dict[str, Any]]:
        """Select tests for a gremlin and return statistics.

        Args:
            gremlin: The gremlin to select tests for.

        Returns:
            Tuple of (selected tests, statistics dict). Stats include:
                - selected_count: Number of tests selected
                - coverage_location: The location string (file:line)
        """
        tests = self.select_tests(gremlin)
        stats = {
            'selected_count': len(tests),
            'coverage_location': f'{gremlin.file_path}:{gremlin.line_number}',
        }
        return tests, stats
