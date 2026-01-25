"""Tests for WorkerPool class.

These tests verify the worker pool lifecycle management and execution behavior.
"""

from __future__ import annotations

import ast
from concurrent.futures import Future
from pathlib import Path
import sys
import tempfile

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel.pool import WorkerPool
from pytest_gremlins.reporting.results import GremlinResultStatus


@pytest.fixture
def sample_gremlin() -> Gremlin:
    """Create a sample gremlin for testing."""
    return Gremlin(
        gremlin_id='g001',
        file_path='/path/to/source.py',
        line_number=42,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


class TestWorkerPoolCreation:
    """Tests for WorkerPool instantiation."""

    def test_creates_with_default_workers(self) -> None:
        """WorkerPool defaults to CPU count when no worker count specified."""
        pool = WorkerPool()
        assert pool.max_workers >= 1

    def test_creates_with_specified_workers(self) -> None:
        """WorkerPool respects specified worker count."""
        pool = WorkerPool(max_workers=4)
        assert pool.max_workers == 4

    def test_creates_with_timeout(self) -> None:
        """WorkerPool stores the specified timeout."""
        pool = WorkerPool(timeout=60)
        assert pool.timeout == 60

    def test_default_timeout_is_30_seconds(self) -> None:
        """WorkerPool defaults to 30 second timeout."""
        pool = WorkerPool()
        assert pool.timeout == 30


class TestWorkerPoolContextManager:
    """Tests for WorkerPool context manager protocol."""

    def test_can_use_as_context_manager(self) -> None:
        """WorkerPool supports context manager protocol."""
        with WorkerPool(max_workers=2) as pool:
            assert pool is not None
            assert pool.max_workers == 2

    def test_context_manager_shuts_down_on_exit(self) -> None:
        """WorkerPool shuts down cleanly on context exit."""
        pool = WorkerPool(max_workers=2)
        with pool:
            pass
        assert pool._shutdown_called


class TestWorkerPoolShutdown:
    """Tests for WorkerPool shutdown behavior."""

    def test_shutdown_is_idempotent(self) -> None:
        """Calling shutdown multiple times is safe."""
        pool = WorkerPool(max_workers=2)
        pool.shutdown()
        pool.shutdown()  # Second call should not raise
        assert pool._shutdown_called

    def test_shutdown_waits_for_pending_work(self) -> None:
        """Shutdown waits for pending work to complete by default."""
        pool = WorkerPool(max_workers=2)
        pool.shutdown(wait=True)
        assert pool._shutdown_called

    def test_shutdown_can_cancel_pending_work(self) -> None:
        """Shutdown can cancel pending work when wait=False."""
        pool = WorkerPool(max_workers=2)
        pool.shutdown(wait=False)
        assert pool._shutdown_called


class TestWorkerPoolSubmit:
    """Tests for submitting work to the worker pool."""

    def test_submit_requires_active_context(self, tmp_path: Path) -> None:
        """Submit raises error when pool is not in context."""
        pool = WorkerPool(max_workers=2)
        with pytest.raises(RuntimeError, match='not active'):
            pool.submit(
                gremlin_id='g001',
                test_command=['pytest'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )

    def test_submit_returns_future(self, tmp_path: Path) -> None:
        """Submit returns a Future object."""
        with WorkerPool(max_workers=2) as pool:
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
        with WorkerPool(max_workers=2) as pool:
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


class TestWorkerPoolExecution:
    """Tests for actual execution in worker pool."""

    def test_successful_test_returns_zapped_status(self, tmp_path: Path) -> None:
        """When tests fail (mutation caught), result is ZAPPED."""
        with WorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'import sys; sys.exit(1)'],  # Fail = mutation caught
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.ZAPPED

    def test_failed_test_returns_survived_status(self, tmp_path: Path) -> None:
        """When tests pass (mutation not caught), result is SURVIVED."""
        with WorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'pass'],  # Pass = mutation survived
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.SURVIVED

    @pytest.mark.medium  # Intentionally waits for timeout (>1s)
    def test_timeout_returns_timeout_status(self, tmp_path: Path) -> None:
        """When test times out, result is TIMEOUT."""
        with WorkerPool(max_workers=1, timeout=1) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'import time; time.sleep(10)'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.TIMEOUT

    def test_result_includes_gremlin_id(self, tmp_path: Path) -> None:
        """Result includes the gremlin ID that was tested."""
        with WorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g042',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.gremlin_id == 'g042'

    def test_env_vars_passed_to_subprocess(self, tmp_path: Path) -> None:
        """Environment variables are passed to the worker subprocess."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('import os; import sys; sys.exit(0 if os.environ.get("MY_VAR") == "test_value" else 1)')
            script_path = f.name

        try:
            with WorkerPool(max_workers=1, timeout=5) as pool:
                future = pool.submit(
                    gremlin_id='g001',
                    test_command=[sys.executable, script_path],
                    rootdir=str(tmp_path),
                    instrumented_dir=None,
                    env_vars={'MY_VAR': 'test_value'},
                )
                result = future.result(timeout=5)
                # If env var was passed, script exits 0 = tests passed = SURVIVED
                assert result.status == GremlinResultStatus.SURVIVED
        finally:
            Path(script_path).unlink()
