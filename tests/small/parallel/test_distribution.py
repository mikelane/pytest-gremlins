"""Tests for gremlin distribution strategies.

These tests verify that gremlins are distributed evenly and correctly across workers.
"""

from __future__ import annotations

import ast

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.distribution import (
    DistributionStrategy,
    RoundRobinDistribution,
    WeightedDistribution,
)


def make_gremlin(gremlin_id: str, file_path: str = '/path/to/source.py', line_number: int = 1) -> Gremlin:
    """Create a test gremlin with minimal required fields."""
    return Gremlin(
        gremlin_id=gremlin_id,
        file_path=file_path,
        line_number=line_number,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


class TestDistributionStrategyProtocol:
    """Tests for the DistributionStrategy protocol."""

    def test_round_robin_implements_protocol(self) -> None:
        """RoundRobinDistribution implements DistributionStrategy protocol."""
        strategy: DistributionStrategy = RoundRobinDistribution()
        assert hasattr(strategy, 'distribute')

    def test_weighted_implements_protocol(self) -> None:
        """WeightedDistribution implements DistributionStrategy protocol."""
        strategy: DistributionStrategy = WeightedDistribution()
        assert hasattr(strategy, 'distribute')


class TestRoundRobinDistribution:
    """Tests for RoundRobinDistribution strategy."""

    def test_empty_gremlins_returns_empty_buckets(self) -> None:
        """Distributing empty list returns empty buckets for each worker."""
        strategy = RoundRobinDistribution()
        result = strategy.distribute([], num_workers=3)
        assert result == [[], [], []]

    def test_single_gremlin_goes_to_first_worker(self) -> None:
        """Single gremlin is assigned to first worker."""
        strategy = RoundRobinDistribution()
        gremlins = [make_gremlin('g001')]
        result = strategy.distribute(gremlins, num_workers=3)
        assert len(result) == 3
        assert len(result[0]) == 1
        assert result[0][0].gremlin_id == 'g001'
        assert result[1] == []
        assert result[2] == []

    def test_distributes_evenly_across_workers(self) -> None:
        """Gremlins are distributed round-robin across workers."""
        strategy = RoundRobinDistribution()
        gremlins = [make_gremlin(f'g{i:03d}') for i in range(6)]
        result = strategy.distribute(gremlins, num_workers=3)

        assert len(result) == 3
        assert len(result[0]) == 2  # g000, g003
        assert len(result[1]) == 2  # g001, g004
        assert len(result[2]) == 2  # g002, g005

    def test_handles_uneven_distribution(self) -> None:
        """Handles case where gremlins don't divide evenly."""
        strategy = RoundRobinDistribution()
        gremlins = [make_gremlin(f'g{i:03d}') for i in range(5)]
        result = strategy.distribute(gremlins, num_workers=3)

        assert len(result) == 3
        assert len(result[0]) == 2  # g000, g003
        assert len(result[1]) == 2  # g001, g004
        assert len(result[2]) == 1  # g002

    def test_single_worker_gets_all_gremlins(self) -> None:
        """With single worker, all gremlins go to that worker."""
        strategy = RoundRobinDistribution()
        gremlins = [make_gremlin(f'g{i:03d}') for i in range(5)]
        result = strategy.distribute(gremlins, num_workers=1)

        assert len(result) == 1
        assert len(result[0]) == 5

    def test_more_workers_than_gremlins(self) -> None:
        """Extra workers get empty buckets."""
        strategy = RoundRobinDistribution()
        gremlins = [make_gremlin('g001'), make_gremlin('g002')]
        result = strategy.distribute(gremlins, num_workers=5)

        assert len(result) == 5
        assert len(result[0]) == 1
        assert len(result[1]) == 1
        assert result[2] == []
        assert result[3] == []
        assert result[4] == []

    def test_distribution_is_deterministic(self) -> None:
        """Same input always produces same output."""
        strategy = RoundRobinDistribution()
        gremlins = [make_gremlin(f'g{i:03d}') for i in range(10)]

        result1 = strategy.distribute(gremlins, num_workers=3)
        result2 = strategy.distribute(gremlins, num_workers=3)

        for i in range(3):
            assert [g.gremlin_id for g in result1[i]] == [g.gremlin_id for g in result2[i]]

    def test_all_gremlins_are_assigned(self) -> None:
        """All input gremlins appear exactly once in output."""
        strategy = RoundRobinDistribution()
        gremlins = [make_gremlin(f'g{i:03d}') for i in range(10)]
        result = strategy.distribute(gremlins, num_workers=3)

        all_ids = []
        for bucket in result:
            all_ids.extend(g.gremlin_id for g in bucket)

        assert sorted(all_ids) == sorted(g.gremlin_id for g in gremlins)


class TestWeightedDistribution:
    """Tests for WeightedDistribution strategy."""

    def test_empty_gremlins_returns_empty_buckets(self) -> None:
        """Distributing empty list returns empty buckets."""
        strategy = WeightedDistribution()
        result = strategy.distribute([], num_workers=3)
        assert result == [[], [], []]

    def test_without_test_counts_uses_round_robin(self) -> None:
        """Without test counts, falls back to round-robin distribution."""
        strategy = WeightedDistribution()
        gremlins = [make_gremlin(f'g{i:03d}') for i in range(6)]
        result = strategy.distribute(gremlins, num_workers=3)

        # Should behave like round-robin when no weights
        assert len(result) == 3
        assert len(result[0]) == 2
        assert len(result[1]) == 2
        assert len(result[2]) == 2

    def test_balances_by_test_count(self) -> None:
        """Heavy gremlins are distributed to different workers."""
        strategy = WeightedDistribution()
        gremlins = [
            make_gremlin('g001'),  # Heavy - 100 tests
            make_gremlin('g002'),  # Heavy - 100 tests
            make_gremlin('g003'),  # Light - 10 tests
            make_gremlin('g004'),  # Light - 10 tests
        ]
        test_counts = {
            'g001': 100,
            'g002': 100,
            'g003': 10,
            'g004': 10,
        }

        result = strategy.distribute(gremlins, num_workers=2, test_counts=test_counts)

        # Heavy gremlins should be on different workers
        worker0_ids = {g.gremlin_id for g in result[0]}
        worker1_ids = {g.gremlin_id for g in result[1]}

        # At least one heavy gremlin on each worker
        heavy = {'g001', 'g002'}
        assert heavy & worker0_ids  # Worker 0 has at least one heavy
        assert heavy & worker1_ids  # Worker 1 has at least one heavy

    def test_all_gremlins_are_assigned(self) -> None:
        """All input gremlins appear exactly once in output."""
        strategy = WeightedDistribution()
        gremlins = [make_gremlin(f'g{i:03d}') for i in range(10)]
        test_counts = {f'g{i:03d}': (i + 1) * 10 for i in range(10)}
        result = strategy.distribute(gremlins, num_workers=3, test_counts=test_counts)

        all_ids = []
        for bucket in result:
            all_ids.extend(g.gremlin_id for g in bucket)

        assert sorted(all_ids) == sorted(g.gremlin_id for g in gremlins)

    def test_missing_test_counts_default_to_one(self) -> None:
        """Gremlins without test count info are assigned weight of 1."""
        strategy = WeightedDistribution()
        gremlins = [
            make_gremlin('g001'),
            make_gremlin('g002'),
            make_gremlin('g003'),
        ]
        # Only provide count for g001
        test_counts = {'g001': 100}

        result = strategy.distribute(gremlins, num_workers=2, test_counts=test_counts)

        all_ids = []
        for bucket in result:
            all_ids.extend(g.gremlin_id for g in bucket)

        assert sorted(all_ids) == ['g001', 'g002', 'g003']

    def test_distribution_is_deterministic(self) -> None:
        """Same input always produces same output."""
        strategy = WeightedDistribution()
        gremlins = [make_gremlin(f'g{i:03d}') for i in range(10)]
        test_counts = {f'g{i:03d}': (i + 1) * 10 for i in range(10)}

        result1 = strategy.distribute(gremlins, num_workers=3, test_counts=test_counts)
        result2 = strategy.distribute(gremlins, num_workers=3, test_counts=test_counts)

        for i in range(3):
            assert [g.gremlin_id for g in result1[i]] == [g.gremlin_id for g in result2[i]]
