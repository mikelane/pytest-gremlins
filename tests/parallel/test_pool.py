"""Tests for WorkerPool class.

These tests verify the worker pool lifecycle management and execution behavior.
"""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
import sys
import tempfile

import pytest

from pytest_gremlins.parallel.pool import WorkerPool
from pytest_gremlins.reporting.results import GremlinResultStatus


@pytest.mark.small
class DescribeWorkerPoolCreation:
    """Tests for WorkerPool instantiation."""

    def it_creates_with_default_workers(self) -> None:
        """WorkerPool defaults to CPU count when no worker count specified."""
        pool = WorkerPool()
        assert pool.max_workers >= 1

    def it_creates_with_specified_workers(self) -> None:
        """WorkerPool respects specified worker count."""
        pool = WorkerPool(max_workers=4)
        assert pool.max_workers == 4

    def it_creates_with_timeout(self) -> None:
        """WorkerPool stores the specified timeout."""
        pool = WorkerPool(timeout=60)
        assert pool.timeout == 60

    def it_default_timeout_is_30_seconds(self) -> None:
        """WorkerPool defaults to 30 second timeout."""
        pool = WorkerPool()
        assert pool.timeout == 30


@pytest.mark.small
class DescribeWorkerPoolContextManager:
    """Tests for WorkerPool context manager protocol."""

    def it_can_use_as_context_manager(self) -> None:
        """WorkerPool supports context manager protocol."""
        with WorkerPool(max_workers=2) as pool:
            assert isinstance(pool, WorkerPool)
            assert pool.max_workers == 2

    def it_context_manager_shuts_down_on_exit(self) -> None:
        """WorkerPool shuts down cleanly on context exit."""
        pool = WorkerPool(max_workers=2)
        with pool:
            pass
        assert pool._shutdown_called


@pytest.mark.small
class DescribeWorkerPoolShutdown:
    """Tests for WorkerPool shutdown behavior."""

    def it_allows_calling_shutdown_multiple_times_without_error(self) -> None:
        """Calling shutdown multiple times is safe."""
        pool = WorkerPool(max_workers=2)
        pool.shutdown()
        pool.shutdown()  # Second call should not raise
        assert pool._shutdown_called

    def it_shutdown_waits_for_pending_work(self) -> None:
        """Shutdown waits for pending work to complete by default."""
        pool = WorkerPool(max_workers=2)
        pool.shutdown(wait=True)
        assert pool._shutdown_called

    def it_shutdown_can_cancel_pending_work(self) -> None:
        """Shutdown can cancel pending work when wait=False."""
        pool = WorkerPool(max_workers=2)
        pool.shutdown(wait=False)
        assert pool._shutdown_called


class DescribeWorkerPoolSubmit:
    """Tests for submitting work to the worker pool."""

    @pytest.mark.small
    def it_submit_requires_active_context(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium  # Pool shutdown waits for subprocess completion
    def it_submit_returns_future(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium  # Pool shutdown waits for subprocess completion
    def it_submit_multiple_gremlins(self, tmp_path: Path) -> None:
        """Multiple gremlins can be submitted to pool."""
        with WorkerPool(max_workers=2) as pool:
            future_0 = pool.submit(
                gremlin_id='g000',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            future_1 = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            future_2 = pool.submit(
                gremlin_id='g002',
                test_command=['python', '-c', 'pass'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            assert isinstance(future_0, Future)
            assert isinstance(future_1, Future)
            assert isinstance(future_2, Future)


class DescribeWorkerPoolExecution:
    """Tests for actual execution in worker pool."""

    @pytest.mark.medium  # Spawns real subprocess via WorkerPool
    def it_successful_test_returns_zapped_status(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium  # Spawns real subprocess via WorkerPool
    def it_failed_test_returns_survived_status(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium  # Spawns real subprocess via WorkerPool
    def it_non_test_exit_code_returns_error_status(self, tmp_path: Path) -> None:
        """Non-test failures (e.g., import/collection errors) are ERROR, not ZAPPED."""
        with WorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'import sys; sys.exit(2)'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.ERROR

    @pytest.mark.medium  # Intentionally waits for timeout (>1s)
    def it_timeout_returns_timeout_status(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium  # Spawns real subprocess via WorkerPool
    def it_includes_gremlin_id(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium  # Spawns real subprocess via WorkerPool
    def it_env_vars_passed_to_subprocess(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium  # Spawns real subprocess via WorkerPool
    def it_suppresses_coverage_process_start_in_subprocess(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """COVERAGE_PROCESS_START is not inherited by mutation subprocesses.

        sitecustomize.py fires at Python startup before --no-cov takes effect,
        so it must be explicitly suppressed in the subprocess environment.
        """
        monkeypatch.setenv('COVERAGE_PROCESS_START', '/some/pyproject.toml')

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('import os, sys\ncps = os.environ.get("COVERAGE_PROCESS_START", "")\nsys.exit(1 if cps else 0)\n')
            script_path = f.name

        try:
            with WorkerPool(max_workers=1, timeout=5) as pool:
                future = pool.submit(
                    gremlin_id='g001',
                    test_command=[sys.executable, script_path],
                    rootdir=str(tmp_path),
                    instrumented_dir=None,
                    env_vars={},
                )
                result = future.result(timeout=10)
                # SURVIVED (exit 0) means COVERAGE_PROCESS_START was empty/unset
                assert result.status == GremlinResultStatus.SURVIVED
        finally:
            Path(script_path).unlink()

    @pytest.mark.medium  # Spawns real subprocess via WorkerPool
    def it_instrumented_dir_sets_sources_env_var(self, tmp_path: Path) -> None:
        """When instrumented_dir is provided, PYTEST_GREMLINS_SOURCES_FILE is set in the subprocess env."""
        expected_sources_path = str(tmp_path / 'sources.json')

        # Script exits 0 if PYTEST_GREMLINS_SOURCES_FILE matches the expected path
        script_content = (
            f'import os, sys\n'
            f'sys.exit(0 if os.environ.get("PYTEST_GREMLINS_SOURCES_FILE") == {expected_sources_path!r} else 1)\n'
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script_content)
            script_path = f.name

        try:
            with WorkerPool(max_workers=1, timeout=5) as pool:
                future = pool.submit(
                    gremlin_id='g001',
                    test_command=[sys.executable, script_path],
                    rootdir=str(tmp_path),
                    instrumented_dir=str(tmp_path),
                    env_vars={},
                )
                result = future.result(timeout=5)
                # exit 0 = no test failures = SURVIVED (env var was set correctly)
                assert result.status == GremlinResultStatus.SURVIVED
        finally:
            Path(script_path).unlink()
