"""CoverageMap for mapping source locations to test functions.

The CoverageMap is a core data structure that enables coverage-guided test
selection. It maps source file lines to the test functions that execute them.

Example:
    >>> coverage_map = CoverageMap()
    >>> len(coverage_map)
    0
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator


class CoverageMap:
    """Maps source locations (file:line) to test function names.

    This data structure stores coverage information collected during test
    execution and allows efficient lookup of which tests cover a given
    source location.

    Attributes:
        _data: Internal dict mapping "file:line" strings to sets of test names.
    """

    def __init__(self) -> None:
        """Create an empty coverage map."""
        self._data: dict[str, set[str]] = {}

    def __len__(self) -> int:
        """Return the number of source locations in the map."""
        return len(self._data)

    def add(self, file_path: str, line_number: int, test_name: str) -> None:
        """Add a coverage mapping from a source location to a test.

        Args:
            file_path: Path to the source file.
            line_number: Line number in the source file.
            test_name: Name of the test function that covers this line.
        """
        key = f'{file_path}:{line_number}'
        if key not in self._data:
            self._data[key] = set()
        self._data[key].add(test_name)

    def get_tests(self, file_path: str, line_number: int) -> set[str]:
        """Get the set of tests that cover a source location.

        Args:
            file_path: Path to the source file.
            line_number: Line number in the source file.

        Returns:
            A set of test function names that cover this location.
            Returns an empty set if no tests cover this location.
        """
        key = f'{file_path}:{line_number}'
        if key not in self._data:
            return set()
        return self._data[key].copy()

    def __contains__(self, location: tuple[str, int]) -> bool:
        """Check if a source location is in the map.

        Args:
            location: A tuple of (file_path, line_number).

        Returns:
            True if the location has coverage data, False otherwise.
        """
        file_path, line_number = location
        key = f'{file_path}:{line_number}'
        return key in self._data

    def locations(self) -> Iterator[tuple[str, int]]:
        """Iterate over all source locations in the map.

        Yields:
            Tuples of (file_path, line_number) for each location.
        """
        for key in self._data:
            file_path, line_str = key.rsplit(':', 1)
            yield file_path, int(line_str)

    def get_incidentally_tested(
        self,
        threshold: int,
    ) -> list[tuple[str, int, int]]:
        """Find source locations covered by many tests ("incidentally tested").

        Incidentally tested code is often utility or infrastructure code that
        is touched by many tests but not directly targeted. This can indicate
        code that is well-protected or code that is simply executed during
        test setup.

        Args:
            threshold: Minimum number of tests for a location to be included.

        Returns:
            List of (file_path, line_number, test_count) tuples, sorted by
            test_count in descending order.
        """
        results: list[tuple[str, int, int]] = []
        for file_path, line_number in self.locations():
            test_count = len(self._data[f'{file_path}:{line_number}'])
            if test_count >= threshold:
                results.append((file_path, line_number, test_count))
        return sorted(results, key=lambda x: x[2], reverse=True)
