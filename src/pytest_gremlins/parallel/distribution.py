"""Gremlin distribution strategies for parallel execution.

This module provides strategies for distributing gremlins across worker processes
to achieve balanced workloads and efficient parallel execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from pytest_gremlins.instrumentation.gremlin import Gremlin


class DistributionStrategy(Protocol):
    """Protocol for gremlin distribution strategies.

    Implementations partition gremlins into buckets for parallel workers.
    """

    def distribute(
        self,
        gremlins: list[Gremlin],
        num_workers: int,
        test_counts: dict[str, int] | None = None,
    ) -> list[list[Gremlin]]:
        """Distribute gremlins across workers.

        Args:
            gremlins: List of gremlins to distribute.
            num_workers: Number of worker processes.
            test_counts: Optional mapping of gremlin_id to number of covering tests.

        Returns:
            List of num_workers buckets, each containing gremlins for that worker.
        """
        ...


class RoundRobinDistribution:
    """Simple round-robin distribution strategy.

    Assigns gremlin N to worker N % num_workers. Fast and deterministic,
    but doesn't account for varying execution times.

    Example:
        >>> strategy = RoundRobinDistribution()
        >>> gremlins = [g0, g1, g2, g3, g4]
        >>> result = strategy.distribute(gremlins, num_workers=3)
        >>> # result[0] = [g0, g3], result[1] = [g1, g4], result[2] = [g2]
    """

    def distribute(
        self,
        gremlins: list[Gremlin],
        num_workers: int,
        test_counts: dict[str, int] | None = None,  # noqa: ARG002
    ) -> list[list[Gremlin]]:
        """Distribute gremlins round-robin across workers.

        Args:
            gremlins: List of gremlins to distribute.
            num_workers: Number of worker processes.
            test_counts: Ignored for round-robin distribution.

        Returns:
            List of num_workers buckets with gremlins distributed round-robin.
        """
        buckets: list[list[Gremlin]] = [[] for _ in range(num_workers)]

        for i, gremlin in enumerate(gremlins):
            worker_idx = i % num_workers
            buckets[worker_idx].append(gremlin)

        return buckets


class WeightedDistribution:
    """Weighted distribution strategy that balances by test count.

    Assigns expensive gremlins (many covering tests) to different workers
    to avoid hotspots where one worker gets all the slow gremlins.

    Uses a greedy algorithm: sort gremlins by weight descending, then assign
    each gremlin to the worker with the smallest current total weight.

    Example:
        >>> strategy = WeightedDistribution()
        >>> gremlins = [g0, g1, g2, g3]  # g0, g1 are heavy (100 tests each)
        >>> test_counts = {'g0': 100, 'g1': 100, 'g2': 10, 'g3': 10}
        >>> result = strategy.distribute(gremlins, num_workers=2, test_counts=test_counts)
        >>> # Heavy gremlins distributed to different workers for balance
    """

    def distribute(
        self,
        gremlins: list[Gremlin],
        num_workers: int,
        test_counts: dict[str, int] | None = None,
    ) -> list[list[Gremlin]]:
        """Distribute gremlins weighted by test count.

        Args:
            gremlins: List of gremlins to distribute.
            num_workers: Number of worker processes.
            test_counts: Mapping of gremlin_id to number of covering tests.
                        Gremlins not in this map get weight of 1.

        Returns:
            List of num_workers buckets with gremlins balanced by weight.
        """
        buckets: list[list[Gremlin]] = [[] for _ in range(num_workers)]

        if not gremlins:
            return buckets

        # If no test counts, fall back to round-robin
        if test_counts is None:
            return RoundRobinDistribution().distribute(gremlins, num_workers)

        # Sort gremlins by weight (test count) descending
        # Gremlins not in test_counts get weight of 1
        weighted_gremlins = sorted(
            gremlins,
            key=lambda g: test_counts.get(g.gremlin_id, 1),
            reverse=True,
        )

        # Track total weight per worker
        worker_weights = [0] * num_workers

        # Greedy assignment: assign each gremlin to least-loaded worker
        for gremlin in weighted_gremlins:
            weight = test_counts.get(gremlin.gremlin_id, 1)
            # Find worker with minimum current weight
            min_worker = min(range(num_workers), key=lambda w: worker_weights[w])
            buckets[min_worker].append(gremlin)
            worker_weights[min_worker] += weight

        return buckets
