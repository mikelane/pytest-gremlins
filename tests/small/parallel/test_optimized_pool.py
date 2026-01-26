"""Tests for optimized PersistentWorkerPool with PoolConfig.

These tests verify that PersistentWorkerPool correctly integrates with
PoolConfig to use optimized settings like custom start methods and warmup.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool
from pytest_gremlins.parallel.pool_config import PoolConfig


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class TestPersistentWorkerPoolWithConfig:
    """Tests for PersistentWorkerPool using PoolConfig."""

    def test_creates_with_pool_config(self) -> None:
        """PersistentWorkerPool can be created with a PoolConfig."""
        config = PoolConfig(max_workers=4, timeout=60)
        pool = PersistentWorkerPool.from_config(config)
        assert pool.max_workers == 4
        assert pool.timeout == 60

    def test_from_config_respects_start_method(self) -> None:
        """from_config creates a pool that will use the specified start method."""
        config = PoolConfig(start_method='spawn')
        pool = PersistentWorkerPool.from_config(config)
        assert pool.config.start_method == 'spawn'

    def test_pool_has_config_attribute(self) -> None:
        """Pool exposes its PoolConfig via config attribute."""
        config = PoolConfig(max_workers=2)
        pool = PersistentWorkerPool.from_config(config)
        assert pool.config == config

    def test_default_constructor_creates_default_config(self) -> None:
        """Default constructor creates a pool with default PoolConfig."""
        pool = PersistentWorkerPool()
        assert pool.config is not None
        assert pool.config.warmup is True

    def test_constructor_args_override_config(self) -> None:
        """Constructor args override PoolConfig defaults."""
        pool = PersistentWorkerPool(max_workers=8, timeout=120)
        assert pool.max_workers == 8
        assert pool.timeout == 120


@pytest.mark.small
class TestPersistentWorkerPoolWarmup:
    """Tests for worker warmup functionality."""

    def test_warmup_enabled_warms_workers_on_start(self) -> None:
        """When warmup is enabled, workers are pre-warmed on context entry."""
        config = PoolConfig(max_workers=2, warmup=True)
        pool = PersistentWorkerPool.from_config(config)

        with pool:
            # Workers should be warmed up
            assert pool.is_warmed_up

    def test_warmup_disabled_does_not_warm_workers(self) -> None:
        """When warmup is disabled, workers are not pre-warmed."""
        config = PoolConfig(max_workers=2, warmup=False)
        pool = PersistentWorkerPool.from_config(config)

        with pool:
            # Workers should NOT be warmed up
            assert not pool.is_warmed_up

    def test_warmup_runs_noop_in_all_workers(self) -> None:
        """Warmup submits a no-op task to each worker."""
        config = PoolConfig(max_workers=2, warmup=True)
        pool = PersistentWorkerPool.from_config(config)

        with pool:
            # After warmup, all workers have executed at least one task
            assert pool.warmup_completed_count == 2

    def test_warmup_does_not_block_indefinitely(self) -> None:
        """Warmup completes within a reasonable time."""
        config = PoolConfig(max_workers=2, warmup=True, timeout=5)
        pool = PersistentWorkerPool.from_config(config)

        start = time.monotonic()
        with pool:
            pass
        elapsed = time.monotonic() - start

        # Warmup should complete quickly (< 2 seconds with 2 workers)
        assert elapsed < 2.0


@pytest.mark.small
class TestPersistentWorkerPoolMpContext:
    """Tests for multiprocessing context usage."""

    def test_uses_mp_context_from_config(self) -> None:
        """Pool uses the multiprocessing context from its config."""
        config = PoolConfig(start_method='spawn')
        pool = PersistentWorkerPool.from_config(config)

        # The pool should store the mp_context
        assert pool._mp_context is not None
        assert pool._mp_context.get_start_method() == 'spawn'

    def test_executor_uses_mp_context(self) -> None:
        """The ProcessPoolExecutor is created with the mp_context."""
        config = PoolConfig(max_workers=1, start_method='spawn', warmup=False)
        pool = PersistentWorkerPool.from_config(config)

        # Mock ProcessPoolExecutor to verify mp_context is passed
        with patch('pytest_gremlins.parallel.persistent_pool.ProcessPoolExecutor') as mock_executor:
            mock_executor.return_value.__enter__ = MagicMock(return_value=mock_executor.return_value)
            mock_executor.return_value.__exit__ = MagicMock(return_value=False)
            mock_executor.return_value.shutdown = MagicMock()

            pool._start()

            # Verify mp_context was passed
            mock_executor.assert_called_once()
            call_kwargs = mock_executor.call_args.kwargs
            assert 'mp_context' in call_kwargs
            assert call_kwargs['mp_context'].get_start_method() == 'spawn'


@pytest.mark.small
class TestPersistentWorkerPoolIntegration:
    """Integration tests for optimized pool with actual execution."""

    def test_pool_executes_work_with_spawn_method(self, tmp_path: Path) -> None:
        """Pool correctly executes work when using spawn start method."""
        config = PoolConfig(max_workers=1, start_method='spawn', warmup=True, timeout=5)
        pool = PersistentWorkerPool.from_config(config)

        with pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.gremlin_id == 'g001'

    def test_pool_executes_batch_with_optimized_settings(self, tmp_path: Path) -> None:
        """Pool correctly executes batches with optimized settings."""
        config = PoolConfig(max_workers=1, start_method='spawn', warmup=True, timeout=10)
        pool = PersistentWorkerPool.from_config(config)

        with pool:
            future = pool.submit_batch(
                gremlin_ids=['g001', 'g002'],
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            results = future.result(timeout=10)
            assert len(results) == 2
            assert results[0].gremlin_id == 'g001'
            assert results[1].gremlin_id == 'g002'
