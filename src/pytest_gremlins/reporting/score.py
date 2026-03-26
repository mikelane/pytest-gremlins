"""Mutation score calculation for gremlin test results.

The mutation score represents test suite effectiveness at catching mutations:
  score = (zapped + timeout) / (total - pardoned) * 100

Pardoned gremlins are excluded from the denominator — they represent
intentionally suppressed mutations (equivalent code, untestable paths, etc.)
and should not penalise the score. A higher score means tests are better
at catching bugs.
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
        pardoned: Number of gremlins explicitly pardoned (excluded from scoring).
        results: The underlying list of results.
    """

    total: int
    zapped: int
    survived: int
    timeout: int
    error: int
    pardoned: int
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
        pardoned = sum(1 for r in results if r.status == GremlinResultStatus.PARDONED)

        return cls(
            total=len(results),
            zapped=zapped,
            survived=survived,
            timeout=timeout,
            error=error,
            pardoned=pardoned,
            results=tuple(results),
        )

    @property
    def percentage(self) -> float:
        """Calculate mutation score as a percentage.

        The score is (zapped + timeout) / (total - pardoned) * 100.
        Timeouts count as zapped because the test detected something wrong.
        Pardoned gremlins are excluded from the denominator — they are
        intentionally suppressed and should not affect the score.

        Returns:
            Mutation score percentage (0.0 to 100.0).
        """
        effective_total = self.total - self.pardoned
        if effective_total == 0:
            return 0.0
        return (self.zapped + self.timeout) / effective_total * 100

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

    def top_errors(self, limit: int = 5) -> list[GremlinResult]:
        """Return the first N errored gremlins that have error_output.

        Args:
            limit: Maximum number of errored results to return.

        Returns:
            List of GremlinResult objects with ERROR status and non-empty error_output.
        """
        return [r for r in self.results if r.status == GremlinResultStatus.ERROR and r.error_output][:limit]
