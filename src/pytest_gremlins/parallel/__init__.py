"""Parallel execution module for pytest-gremlins.

This module provides components for running mutation testing in parallel:

- WorkerPool: Manages concurrent worker processes
- DistributionStrategy: Partitions gremlins across workers
- ResultAggregator: Collects and merges results from workers
"""

from __future__ import annotations
