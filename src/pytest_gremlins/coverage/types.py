"""TypedDict definitions for coverage module return types.

These replace ``dict[str, Any]`` in collector, selector, and
prioritized_selector with precise types that capture the actual
data shape of coverage statistics.
"""

from __future__ import annotations

from typing import TypedDict


class CollectorStats(TypedDict):
    """Statistics returned by :meth:`CoverageCollector.get_stats`."""

    total_tests: int
    total_locations: int
    total_mappings: int


class SelectionStats(TypedDict):
    """Statistics returned by :meth:`TestSelector.select_tests_with_stats`."""

    selected_count: int
    coverage_location: str


class PrioritizedSelectionStats(TypedDict):
    """Statistics returned by :meth:`PrioritizedSelector.select_tests_with_stats`."""

    selected_count: int
    coverage_location: str
    most_specific_test: str | None
    specificity_range: tuple[int, int]
