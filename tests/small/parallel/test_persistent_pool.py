"""Tests for PersistentWorkerPool class.

This module tests the persistent worker pool that reduces subprocess overhead
by keeping workers alive across multiple gremlin tests.

The persistent pool addresses the primary bottleneck identified in profiling:
subprocess spawning takes 500-700ms per gremlin. By keeping workers warm,
we pay this cost once per worker instead of once per gremlin.
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.parallel.pool_config import PoolConfig
from pytest_gremlins.reporting.results import GremlinResultStatus


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class TestPersistentWorkerPoolCreation:
    """Tests for PersistentWorkerPool instantiation."""

    def test_creates_with_default_workers(self) -> None:
        """PersistentWorkerPool defaults to CPU count when no worker count specified."""
        pool = PersistentWorkerPool()
        assert pool.max_workers >= 1

    def test_creates_with_specified_workers(self) -> None:
        """PersistentWorkerPool respects specified worker count."""
        pool = PersistentWorkerPool(max_workers=4)
        assert pool.max_workers == 4

    def test_creates_with_timeout(self) -> None:
        """PersistentWorkerPool stores the specified timeout."""
        pool = PersistentWorkerPool(timeout=60)
        assert pool.timeout == 60

    def test_default_timeout_is_30_seconds(self) -> None:
        """PersistentWorkerPool defaults to 30 second timeout."""
        pool = PersistentWorkerPool()
        assert pool.timeout == 30

    def test_from_config_creates_pool_with_config_values(self) -> None:
        """from_config creates pool using PoolConfig settings."""
        config = PoolConfig(max_workers=8, timeout=45)
        pool = PersistentWorkerPool.from_config(config)
        assert pool.max_workers == 8
        assert pool.timeout == 45
        assert pool.config is config

    def test_config_property_returns_poolconfig(self) -> None:
        """config property returns the PoolConfig used by the pool."""
        config = PoolConfig(max_workers=4)
        pool = PersistentWorkerPool(config=config)
        assert pool.config is config

    def test_creates_with_config_timeout_override(self) -> None:
        """Explicit timeout parameter overrides config timeout."""
        config = PoolConfig(max_workers=4, timeout=60)
        # Explicit timeout of 45 overrides config's 60
        pool = PersistentWorkerPool(config=config, timeout=45)
        assert pool.timeout == 45

    def test_creates_with_config_max_workers_override(self) -> None:
        """Explicit max_workers parameter overrides config max_workers."""
        config = PoolConfig(max_workers=8, timeout=30)
        # Explicit max_workers of 2 overrides config's 8
        pool = PersistentWorkerPool(config=config, max_workers=2)
        assert pool.max_workers == 2


@pytest.mark.small
class TestPersistentWorkerPoolContextManager:
    """Tests for PersistentWorkerPool context manager protocol."""

    def test_can_use_as_context_manager(self) -> None:
        """PersistentWorkerPool supports context manager protocol."""
        with PersistentWorkerPool(max_workers=2) as pool:
            assert pool is not None
            assert pool.max_workers == 2

    def test_context_manager_starts_workers(self) -> None:
        """PersistentWorkerPool starts workers on context entry."""
        with PersistentWorkerPool(max_workers=2) as pool:
            assert pool.is_running

    def test_context_manager_shuts_down_on_exit(self) -> None:
        """PersistentWorkerPool shuts down cleanly on context exit."""
        pool = PersistentWorkerPool(max_workers=2)
        with pool:
            pass
        assert not pool.is_running

    def test_warmup_enabled_by_default(self) -> None:
        """Pool warms up workers by default when using context manager."""
        config = PoolConfig(max_workers=2, warmup=True)
        pool = PersistentWorkerPool(config=config)
        with pool:
            assert pool.is_warmed_up
            assert pool.warmup_completed_count == 2

    def test_warmup_disabled_when_configured(self) -> None:
        """Pool does not warmup when warmup is disabled in config."""
        config = PoolConfig(max_workers=2, warmup=False)
        pool = PersistentWorkerPool(config=config)
        with pool:
            assert not pool.is_warmed_up
            assert pool.warmup_completed_count == 0

    def test_shutdown_when_never_started_is_safe(self) -> None:
        """Calling shutdown on pool that was never started is safe."""
        pool = PersistentWorkerPool(max_workers=2)
        # Never enter context, but call shutdown via __exit__
        pool.__exit__(None, None, None)
        assert not pool.is_running


@pytest.mark.small
class TestPersistentWorkerPoolSubmit:
    """Tests for submitting work to the persistent pool."""

    def test_submit_requires_active_context(self, tmp_path: Path) -> None:
        """Submit raises error when pool is not running."""
        pool = PersistentWorkerPool(max_workers=2)
        with pytest.raises(RuntimeError, match='not running'):
            pool.submit(
                gremlin_id='g001',
                test_command=['pytest'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )

    def test_submit_returns_future(self, tmp_path: Path) -> None:
        """Submit returns a Future object."""
        with PersistentWorkerPool(max_workers=2) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            assert isinstance(future, Future)

    def test_submit_multiple_gremlins(self, tmp_path: Path) -> None:
        """Multiple gremlins can be submitted to pool."""
        with PersistentWorkerPool(max_workers=2) as pool:
            futures = []
            for i in range(3):
                future = pool.submit(
                    gremlin_id=f'g{i:03d}',
                    test_command=['python', '-c', 'pass'],
                    rootdir=str(tmp_path),
                    instrumented_dir=None,
                    env_vars={},
                )
                futures.append(future)
            assert len(futures) == 3
            assert all(isinstance(f, Future) for f in futures)

    def test_submit_sets_sources_file_env_when_instrumented_dir_provided(self, tmp_path: Path) -> None:
        """submit sets PYTEST_GREMLINS_SOURCES_FILE when instrumented_dir is provided."""
        script = tmp_path / 'test_script.py'
        script.write_text("""
import os
import sys
# Check that the sources file env var is set
sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE', '')
if 'instrumented/sources.json' not in sources_file:
    sys.exit(1)
sys.exit(0)
""")

        with PersistentWorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', str(script)],
                rootdir=str(tmp_path),
                instrumented_dir=str(tmp_path / 'instrumented'),
                env_vars={},
            )
            result = future.result(timeout=5)
            # Test passes if sources file was set correctly
            assert result.status == GremlinResultStatus.SURVIVED


@pytest.mark.small
class TestPersistentWorkerPoolExecution:
    """Tests for actual execution in persistent pool."""

    def test_successful_test_returns_zapped_status(self, tmp_path: Path) -> None:
        """When tests fail (mutation caught), result is ZAPPED."""
        with PersistentWorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'import sys; sys.exit(1)'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.ZAPPED

    def test_passed_test_returns_survived_status(self, tmp_path: Path) -> None:
        """When tests pass (mutation not caught), result is SURVIVED."""
        with PersistentWorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.SURVIVED

    def test_result_includes_gremlin_id(self, tmp_path: Path) -> None:
        """Result includes the gremlin ID that was tested."""
        with PersistentWorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g042',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.gremlin_id == 'g042'


@pytest.mark.small
class TestBatchExecution:
    """Tests for batch execution - running multiple gremlins in one subprocess."""

    def test_submit_batch_requires_active_context(self, tmp_path: Path) -> None:
        """submit_batch raises error when pool is not running."""
        pool = PersistentWorkerPool(max_workers=2)
        with pytest.raises(RuntimeError, match='not running'):
            pool.submit_batch(
                gremlin_ids=['g001', 'g002'],
                test_command=['pytest'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )

    def test_submit_batch_returns_future_with_list_of_results(self, tmp_path: Path) -> None:
        """submit_batch returns a Future with results for all gremlins in batch."""
        with PersistentWorkerPool(max_workers=1, timeout=10) as pool:
            future = pool.submit_batch(
                gremlin_ids=['g001', 'g002', 'g003'],
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            results = future.result(timeout=10)
            assert isinstance(results, list)
            assert len(results) == 3
            assert all(isinstance(r, WorkerResult) for r in results)

    def test_submit_batch_tests_each_gremlin_independently(self, tmp_path: Path) -> None:
        """Each gremlin in a batch is tested independently (different env var)."""
        with PersistentWorkerPool(max_workers=1, timeout=10) as pool:
            future = pool.submit_batch(
                gremlin_ids=['g001', 'g002'],
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            results = future.result(timeout=10)
            gremlin_ids = [r.gremlin_id for r in results]
            assert gremlin_ids == ['g001', 'g002']

    def test_submit_batch_stops_on_first_failure(self, tmp_path: Path) -> None:
        """Batch uses early termination - first zapped gremlin stops the batch."""
        # First gremlin survives (tests pass), second fails (tests fail)
        # When using the test command that checks ACTIVE_GREMLIN env var
        script = tmp_path / 'test_script.py'
        script.write_text("""
import os
import sys
gremlin = os.environ.get('ACTIVE_GREMLIN')
# g002 is detected (killed), others survive
sys.exit(1 if gremlin == 'g002' else 0)
""")

        with PersistentWorkerPool(max_workers=1, timeout=10) as pool:
            future = pool.submit_batch(
                gremlin_ids=['g001', 'g002', 'g003'],
                test_command=['python', str(script)],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            results = future.result(timeout=10)

            # g001 survives, g002 is zapped (caught), g003 should be skipped
            assert len(results) == 2
            assert results[0].gremlin_id == 'g001'
            assert results[0].status == GremlinResultStatus.SURVIVED
            assert results[1].gremlin_id == 'g002'
            assert results[1].status == GremlinResultStatus.ZAPPED

    def test_submit_batch_sets_sources_file_env_when_instrumented_dir_provided(self, tmp_path: Path) -> None:
        """submit_batch sets PYTEST_GREMLINS_SOURCES_FILE when instrumented_dir is provided."""
        script = tmp_path / 'test_script.py'
        script.write_text("""
import os
import sys
# Check that the sources file env var is set
sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE', '')
if 'instrumented/sources.json' not in sources_file:
    sys.exit(1)
sys.exit(0)
""")

        with PersistentWorkerPool(max_workers=1, timeout=10) as pool:
            future = pool.submit_batch(
                gremlin_ids=['g001'],
                test_command=['python', str(script)],
                rootdir=str(tmp_path),
                instrumented_dir=str(tmp_path / 'instrumented'),
                env_vars={},
            )
            results = future.result(timeout=10)
            assert len(results) == 1
            assert results[0].status == GremlinResultStatus.SURVIVED
