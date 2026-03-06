"""Tests for BatchExecutor integration with PoolConfig.

These tests verify that BatchExecutor correctly integrates with PoolConfig
to use optimized settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.parallel.batch_executor import BatchExecutor
from pytest_gremlins.parallel.pool_config import PoolConfig

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class DescribeBatchExecutorWithConfig:
    """Tests for BatchExecutor using PoolConfig."""

    def it_creates_from_pool_config(self) -> None:
        """BatchExecutor can be created from a PoolConfig."""
        config = PoolConfig(max_workers=4, timeout=60, batch_size=15)
        executor = BatchExecutor.from_config(config)

        assert executor.batch_size == 15
        assert executor.max_workers == 4

    def it_uses_optimal_settings_via_from_config(self) -> None:
        """from_config creates an executor with optimal settings."""
        config = PoolConfig(warmup=True, batch_size=20)
        executor = BatchExecutor.from_config(config)

        # The executor should store the config
        assert executor.config == config
        assert executor.batch_size == 20

    def it_default_constructor_creates_default_config(self) -> None:
        """Default constructor creates an executor with default config."""
        executor = BatchExecutor()

        # Should have reasonable defaults
        assert executor.batch_size == 10
        assert executor.max_workers >= 1


@pytest.mark.medium
class DescribeBatchExecutorConfigIntegration:
    """Integration tests for BatchExecutor with PoolConfig."""

    def it_uses_config_start_method(self, tmp_path: Path) -> None:
        """Execute creates pool with configured start method."""
        config = PoolConfig(max_workers=1, start_method='spawn', warmup=True, batch_size=2, timeout=5)
        executor = BatchExecutor.from_config(config)

        results = executor.execute(
            gremlin_ids=['g001', 'g002'],
            test_command=['python', '-c', 'pass'],
            rootdir=str(tmp_path),
            instrumented_dir=None,
            env_vars={},
        )

        # Results should be returned for all gremlins
        assert len(results) == 2
        assert {r.gremlin_id for r in results} == {'g001', 'g002'}

    def it_warms_up_pool_before_executing(self, tmp_path: Path) -> None:
        """Execute benefits from warmup when enabled."""
        config = PoolConfig(max_workers=1, warmup=True, batch_size=2, timeout=5)
        executor = BatchExecutor.from_config(config)

        results = executor.execute(
            gremlin_ids=['g001'],
            test_command=['python', '-c', 'pass'],
            rootdir=str(tmp_path),
            instrumented_dir=None,
            env_vars={},
        )

        assert len(results) == 1
        assert results[0].gremlin_id == 'g001'
