"""Mutation score calculation for gremlin test results.

The mutation score represents test suite effectiveness at catching mutations:
  score = zapped / total * 100

A higher score means tests are better at catching bugs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_gremlins.reporting.results import GremlinResult

from pytest_gremlins.reporting.results import GremlinResultStatus


@dataclass(frozen=True)
class MutationScore:
    """Aggregated mutation testing score.

    Attributes:
        total: Total number of gremlins tested.
        zapped: Number of gremlins caught by tests.
        survived: Number of gremlins that escaped tests.
        timeout: Number of gremlins that caused test timeouts.
        error: Number of gremlins that caused errors.
        results: The underlying list of results.
    """

    total: int
    zapped: int
    survived: int
    timeout: int
    error: int
    results: tuple[GremlinResult, ...]

    @classmethod
    def from_results(cls, results: Sequence[GremlinResult]) -> MutationScore:
        """Create a MutationScore from a sequence of GremlinResults.

        Args:
            results: Sequence of GremlinResult objects to aggregate.

        Returns:
            MutationScore with counts for each status.
        """
        zapped = sum(1 for r in results if r.status == GremlinResultStatus.ZAPPED)
        survived = sum(1 for r in results if r.status == GremlinResultStatus.SURVIVED)
        timeout = sum(1 for r in results if r.status == GremlinResultStatus.TIMEOUT)
        error = sum(1 for r in results if r.status == GremlinResultStatus.ERROR)

        return cls(
            total=len(results),
            zapped=zapped,
            survived=survived,
            timeout=timeout,
            error=error,
            results=tuple(results),
        )

    @property
    def percentage(self) -> float:
        """Calculate mutation score as a percentage.

        The score is (zapped + timeout) / total * 100.
        Timeouts count as zapped because the test detected something wrong.

        Returns:
            Mutation score percentage (0.0 to 100.0).
        """
        if self.total == 0:
            return 0.0
        return (self.zapped + self.timeout) / self.total * 100

    def by_file(self) -> dict[str, MutationScore]:
        """Break down mutation score by file.

        Returns:
            Dictionary mapping file paths to their MutationScore.
        """
        results_by_file: dict[str, list[GremlinResult]] = defaultdict(list)
        for result in self.results:
            results_by_file[result.gremlin.file_path].append(result)

        return {
            file_path: MutationScore.from_results(file_results) for file_path, file_results in results_by_file.items()
        }

    def top_survivors(self, limit: int = 10) -> list[GremlinResult]:
        """Get the top surviving gremlins.

        Args:
            limit: Maximum number of survivors to return.

        Returns:
            List of GremlinResult objects for survived gremlins.
        """
        survivors = [r for r in self.results if r.is_survived]
        return survivors[:limit]
