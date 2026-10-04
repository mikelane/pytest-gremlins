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

from pytest_gremlins.reporting.results import (
    TIMEOUT_NOT_CONFIRMED_PREFIX,
    GremlinResultStatus,
)


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
    mutant_timeout: int | None = None

    @classmethod
    def from_results(cls, results: Sequence[GremlinResult], mutant_timeout: int | None = None) -> MutationScore:
        """Create a MutationScore from a sequence of GremlinResults.

        Args:
            results: Sequence of GremlinResult objects to aggregate.
            mutant_timeout: Per-gremlin timeout in seconds the run used, named in the timeout warning.

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
            mutant_timeout=mutant_timeout,
        )

    @property
    def downgraded_timeouts(self) -> int:
        """Number of timeouts downgraded to errors because the unmutated tests also timed out."""
        return sum(
            1
            for r in self.results
            if r.status == GremlinResultStatus.ERROR and (r.error_output or '').startswith(TIMEOUT_NOT_CONFIRMED_PREFIX)
        )

    @property
    def timeout_warning(self) -> str | None:
        """Explain downgraded timeouts, or ``None`` when there were none.

        Returns:
            One line giving the count, the timeout, and the options that raise it.
        """
        count = self.downgraded_timeouts
        if not count:
            return None
        noun = 'timeout' if count == 1 else 'timeouts'
        timeout = f'{self.mutant_timeout}s' if self.mutant_timeout is not None else 'the mutant timeout'
        return (
            f'{count} {noun} counted as errors, not kills: the unmutated tests also exceeded {timeout}. '
            'Raise it with --gremlin-mutant-timeout or [tool.pytest-gremlins].mutant_timeout.'
        )

    @property
    def percentage(self) -> float:
        """Calculate mutation score as a percentage.

        The score is (zapped + timeout) / (total - pardoned) * 100.
        A timeout counts as zapped because the test detected something wrong, but only
        a confirmed one: a timeout whose unmutated selection also times out is an error.
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
            file_path: MutationScore.from_results(file_results, mutant_timeout=self.mutant_timeout)
            for file_path, file_results in results_by_file.items()
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
