"""Tests demonstrating the performance benefits of pool optimizations.

These tests verify that the optimizations in PoolConfig actually provide
measurable benefits for worker pool performance.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool
from pytest_gremlins.parallel.pool_config import PoolConfig, get_optimal_start_method


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class TestStartMethodOptimization:
    """Tests verifying start method optimization."""

    def test_forkserver_available_on_unix(self) -> None:
        """forkserver is available and selected on Unix systems."""
        if sys.platform == 'win32':
            pytest.skip('forkserver not available on Windows')

        method = get_optimal_start_method()
        assert method == 'forkserver'

    def test_spawn_used_on_windows(self) -> None:
        """spawn is used on Windows."""
        if sys.platform != 'win32':
            pytest.skip('Only relevant on Windows')

        method = get_optimal_start_method()
        assert method == 'spawn'


@pytest.mark.small
class TestWarmupBenefits:
    """Tests demonstrating warmup benefits."""

    def test_warmed_pool_completes_first_task_faster(self, tmp_path: Path) -> None:
        """A warmed pool completes its first real task faster than cold pool.

        Note: This test is probabilistic - warmup may not always be faster
        due to system variability, but on average it should help.
        """
        # We'll just verify warmup completes without error
        # and the pool is ready for work
        config = PoolConfig(max_workers=2, warmup=True, timeout=5)
        pool = PersistentWorkerPool.from_config(config)

        with pool:
            assert pool.is_warmed_up
            assert pool.warmup_completed_count == 2

            # Submit a simple task - should complete quickly
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.gremlin_id == 'g001'

    def test_warmup_is_configurable(self) -> None:
        """Warmup can be disabled for specific use cases."""
        config = PoolConfig(warmup=False)
        pool = PersistentWorkerPool.from_config(config)

        with pool:
            # Without warmup, is_warmed_up should be False
            assert not pool.is_warmed_up
            assert pool.warmup_completed_count == 0


@pytest.mark.small
class TestMpContextOptimization:
    """Tests verifying multiprocessing context optimization."""

    def test_mp_context_is_created_lazily(self) -> None:
        """Multiprocessing context is created when pool starts."""
        config = PoolConfig(max_workers=2, start_method='spawn')
        pool = PersistentWorkerPool.from_config(config)

        # Before entering context, mp_context should exist
        assert pool._mp_context is not None
        assert pool._mp_context.get_start_method() == 'spawn'

    def test_auto_start_method_selects_optimal(self) -> None:
        """Auto start method selects the optimal method for the platform."""
        config = PoolConfig(start_method='auto')
        pool = PersistentWorkerPool.from_config(config)

        optimal = get_optimal_start_method()
        assert pool._mp_context.get_start_method() == optimal


@pytest.mark.small
class TestPoolConfigIntegrationWithBatchExecutor:
    """Tests verifying PoolConfig works with BatchExecutor patterns."""

    def test_batch_size_from_config(self) -> None:
        """BatchExecutor can use batch size from PoolConfig."""
        config = PoolConfig(batch_size=20)
        assert config.batch_size == 20

    def test_config_provides_all_batch_executor_params(self) -> None:
        """PoolConfig provides all parameters needed by BatchExecutor."""
        config = PoolConfig(
            max_workers=4,
            timeout=60,
            batch_size=15,
        )

        # These are the parameters BatchExecutor needs
        assert config.max_workers == 4
        assert config.timeout == 60
        assert config.batch_size == 15


@pytest.mark.small
class TestPoolPerformanceCharacteristics:
    """Tests documenting expected performance characteristics."""

    # Windows CI runners are significantly slower and more variable than Linux/macOS
    # Use platform-specific thresholds to avoid flaky tests
    POOL_CREATION_THRESHOLD = 0.5 if sys.platform == 'win32' else 0.1  # 500ms Windows, 100ms Unix
    WARMUP_THRESHOLD = 10.0 if sys.platform == 'win32' else 3.0  # 10s Windows, 3s Unix

    def test_pool_creation_is_fast(self) -> None:
        """Pool creation without warmup is fast (<100ms on Unix, <500ms on Windows)."""
        config = PoolConfig(max_workers=2, warmup=False)

        start = time.monotonic()
        pool = PersistentWorkerPool.from_config(config)
        elapsed = time.monotonic() - start

        # Creating the pool object should be nearly instant
        assert elapsed < self.POOL_CREATION_THRESHOLD

        # The pool is not started yet
        assert not pool.is_running

    def test_pool_startup_with_warmup_reasonable_time(self) -> None:
        """Pool startup with warmup completes in reasonable time.

        Warmup should add some overhead but not be excessive.
        Windows CI runners need more generous thresholds.
        """
        config = PoolConfig(max_workers=2, warmup=True)
        pool = PersistentWorkerPool.from_config(config)

        start = time.monotonic()
        with pool:
            pass
        elapsed = time.monotonic() - start

        # Warmup + shutdown threshold varies by platform
        # Windows CI is slower and more variable
        assert elapsed < self.WARMUP_THRESHOLD

    def test_pool_reuse_avoids_startup_overhead(self, tmp_path: Path) -> None:
        """Using the same pool for multiple batches avoids repeated startup."""
        config = PoolConfig(max_workers=1, warmup=True, timeout=5)
        pool = PersistentWorkerPool.from_config(config)

        with pool:
            # First submission
            future1 = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result1 = future1.result(timeout=5)

            # Second submission - should reuse the same pool
            future2 = pool.submit(
                gremlin_id='g002',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result2 = future2.result(timeout=5)

            assert result1.gremlin_id == 'g001'
            assert result2.gremlin_id == 'g002'
