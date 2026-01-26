"""PrioritizedSelector for ordering tests by specificity.

The PrioritizedSelector extends coverage-guided test selection by ordering
tests based on their specificity - tests that cover fewer lines are more
specific and more likely to catch mutations quickly.

This optimization enables faster gremlin detection:
1. Most specific tests run first (high probability of catching mutation)
2. pytest's -x flag exits on first failure
3. If a specific test catches the mutation, we skip running broad tests

Example:
    >>> from pytest_gremlins.coverage.mapper import CoverageMap
    >>> cm = CoverageMap()
    >>> cm.add('src/auth.py', 42, 'test_specific')
    >>> cm.add('src/auth.py', 42, 'test_broad')
    >>> cm.add('src/auth.py', 43, 'test_broad')
    >>> selector = PrioritizedSelector(cm)
    >>> # test_specific covers fewer lines, so it's returned first
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pytest_gremlins.coverage.mapper import CoverageMap
    from pytest_gremlins.instrumentation.gremlin import Gremlin


class PrioritizedSelector:
    """Selects and prioritizes tests by specificity for faster gremlin detection.

    Tests that cover fewer source lines are considered more "specific" and
    are more likely to catch mutations. By running specific tests first,
    we can often detect mutations faster with pytest's -x (exit-first) flag.

    Attributes:
        coverage_map: The CoverageMap containing line-to-test mappings.
        _specificity_cache: Cached test specificity scores (lines covered per test).
    """

    def __init__(self, coverage_map: CoverageMap) -> None:
        """Create a PrioritizedSelector with the given coverage map.

        Args:
            coverage_map: A CoverageMap containing line-to-test mappings.
        """
        self.coverage_map = coverage_map
        self._specificity_cache: dict[str, int] | None = None

    def get_test_specificity(self) -> dict[str, int]:
        """Compute specificity scores for all tests (lower = more specific).

        Specificity is measured as the number of source lines a test covers.
        Tests covering fewer lines are more specific and more likely to
        catch mutations in those lines.

        Returns:
            Dict mapping test names to their line count (specificity score).
        """
        if self._specificity_cache is not None:
            return self._specificity_cache

        test_lines: dict[str, set[str]] = {}

        for file_path, line_number in self.coverage_map.locations():
            tests = self.coverage_map.get_tests(file_path, line_number)
            location_key = f'{file_path}:{line_number}'
            for test_name in tests:
                if test_name not in test_lines:
                    test_lines[test_name] = set()
                test_lines[test_name].add(location_key)

        self._specificity_cache = {test_name: len(lines) for test_name, lines in test_lines.items()}
        return self._specificity_cache

    def select_tests_prioritized(self, gremlin: Gremlin) -> list[str]:
        """Select tests for a gremlin, ordered by specificity (most specific first).

        Args:
            gremlin: The gremlin to select tests for.

        Returns:
            List of test names ordered by specificity (fewest lines first).
            Tests with equal specificity are sorted alphabetically for determinism.
        """
        return self.select_tests_for_location_prioritized(
            gremlin.file_path,
            gremlin.line_number,
        )

    def select_tests_for_location_prioritized(
        self,
        file_path: str,
        line_number: int,
    ) -> list[str]:
        """Select and prioritize tests for a specific source location.

        Args:
            file_path: Path to the source file.
            line_number: Line number in the source file.

        Returns:
            List of test names ordered by specificity (fewest lines first).
        """
        tests = self.coverage_map.get_tests(file_path, line_number)
        if not tests:
            return []

        specificity = self.get_test_specificity()

        # Sort by specificity (ascending - fewer lines first), then alphabetically
        return sorted(
            tests,
            key=lambda t: (specificity.get(t, float('inf')), t),
        )

    def select_tests_with_stats(
        self,
        gremlin: Gremlin,
    ) -> tuple[list[str], dict[str, Any]]:
        """Select prioritized tests for a gremlin and return statistics.

        Args:
            gremlin: The gremlin to select tests for.

        Returns:
            Tuple of (prioritized tests list, statistics dict). Stats include:
                - selected_count: Number of tests selected
                - coverage_location: The location string (file:line)
                - most_specific_test: Name of the most specific test (if any)
                - specificity_range: Tuple of (min, max) lines covered
        """
        tests = self.select_tests_prioritized(gremlin)
        specificity = self.get_test_specificity()

        stats: dict[str, Any] = {
            'selected_count': len(tests),
            'coverage_location': f'{gremlin.file_path}:{gremlin.line_number}',
        }

        if tests:
            test_specificities = [specificity.get(t, 0) for t in tests]
            stats['most_specific_test'] = tests[0]
            stats['specificity_range'] = (min(test_specificities), max(test_specificities))
        else:
            stats['most_specific_test'] = None
            stats['specificity_range'] = (0, 0)

        return tests, stats
