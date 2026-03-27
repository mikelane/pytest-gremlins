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

from pytest_gremlins.parallel.lightweight import build_lightweight_command
from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.parallel.pool_config import PoolConfig
from pytest_gremlins.reporting.results import GremlinResultStatus

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class DescribeBuildLightweightCommandEnvChecks:
    """Tests for build_lightweight_command env var validation (no filesystem)."""

    def it_returns_none_when_sources_file_not_in_env_vars(self) -> None:
        """Missing PYTEST_GREMLINS_SOURCES_FILE means no lightweight runner."""
        result = build_lightweight_command(
            test_command=['python', 'bootstrap.py', '-x', 'tests/test_foo.py::test_bar'],
            env_vars={},
        )
        assert result is None

    def it_returns_none_when_sources_file_is_empty_string(self) -> None:
        """Empty PYTEST_GREMLINS_SOURCES_FILE means no lightweight runner."""
        result = build_lightweight_command(
            test_command=['python', 'bootstrap.py', '-x', 'tests/test_foo.py::test_bar'],
            env_vars={'PYTEST_GREMLINS_SOURCES_FILE': ''},
        )
        assert result is None


@pytest.mark.medium
class DescribeBuildLightweightCommandFilesystem:
    """Tests for build_lightweight_command with filesystem interactions."""

    def it_returns_none_when_runner_script_does_not_exist(self, tmp_path: Path) -> None:
        """Non-existent runner script path means no lightweight runner."""
        sources_file = str(tmp_path / 'sources.json')
        # Do NOT create gremlin_lightweight_runner.py
        result = build_lightweight_command(
            test_command=['python', 'bootstrap.py', '-x', 'tests/test_foo.py::test_bar'],
            env_vars={'PYTEST_GREMLINS_SOURCES_FILE': sources_file},
        )
        assert result is None

    def it_returns_none_when_no_test_ids_in_args(self, tmp_path: Path) -> None:
        """No arguments containing '::' means no test IDs to extract."""
        sources_file = str(tmp_path / 'sources.json')
        runner_path = tmp_path / 'gremlin_lightweight_runner.py'
        runner_path.write_text('# runner')
        result = build_lightweight_command(
            test_command=['python', 'bootstrap.py', '-x', '--no-header'],
            env_vars={'PYTEST_GREMLINS_SOURCES_FILE': sources_file},
        )
        assert result is None

    def it_returns_lightweight_command_when_all_conditions_met(self, tmp_path: Path) -> None:
        """Returns [python, runner_path, *test_ids] when runner exists and test IDs found."""
        sources_file = str(tmp_path / 'sources.json')
        runner_path = tmp_path / 'gremlin_lightweight_runner.py'
        runner_path.write_text('# runner')
        result = build_lightweight_command(
            test_command=['python', 'bootstrap.py', '-x', 'tests/test_foo.py::test_bar'],
            env_vars={'PYTEST_GREMLINS_SOURCES_FILE': sources_file},
        )
        assert result is not None
        assert result[0] == 'python'
        assert result[1] == str(runner_path)
        assert result[2] == 'tests/test_foo.py::test_bar'

    def it_extracts_multiple_test_ids_from_command(self, tmp_path: Path) -> None:
        """Extracts all arguments containing '::' as test node IDs."""
        sources_file = str(tmp_path / 'sources.json')
        runner_path = tmp_path / 'gremlin_lightweight_runner.py'
        runner_path.write_text('# runner')
        result = build_lightweight_command(
            test_command=[
                'python',
                'bootstrap.py',
                '-x',
                'tests/test_foo.py::test_bar',
                'tests/test_baz.py::TestClass::test_method',
            ],
            env_vars={'PYTEST_GREMLINS_SOURCES_FILE': sources_file},
        )
        assert result is not None
        assert len(result) == 4
        assert result[2] == 'tests/test_foo.py::test_bar'
        assert result[3] == 'tests/test_baz.py::TestClass::test_method'

    def it_skips_non_test_id_args_before_extracting(self, tmp_path: Path) -> None:
        """Only args after index 2 (skipping python and bootstrap) are checked for '::'."""
        sources_file = str(tmp_path / 'sources.json')
        runner_path = tmp_path / 'gremlin_lightweight_runner.py'
        runner_path.write_text('# runner')
        # The first two args (python, bootstrap.py) are never checked
        result = build_lightweight_command(
            test_command=['python', 'bootstrap.py', '--verbose', 'tests/test_a.py::test_x'],
            env_vars={'PYTEST_GREMLINS_SOURCES_FILE': sources_file},
        )
        assert result is not None
        assert result == ['python', str(runner_path), 'tests/test_a.py::test_x']


@pytest.mark.small
class DescribePersistentWorkerPoolCreation:
    """Tests for PersistentWorkerPool instantiation."""

    def it_creates_with_default_workers(self) -> None:
        """PersistentWorkerPool defaults to CPU count when no worker count specified."""
        pool = PersistentWorkerPool()
        assert pool.max_workers >= 1

    def it_creates_with_specified_workers(self) -> None:
        """PersistentWorkerPool respects specified worker count."""
        pool = PersistentWorkerPool(max_workers=4)
        assert pool.max_workers == 4

    def it_creates_with_timeout(self) -> None:
        """PersistentWorkerPool stores the specified timeout."""
        pool = PersistentWorkerPool(timeout=60)
        assert pool.timeout == 60

    def it_default_timeout_is_30_seconds(self) -> None:
        """PersistentWorkerPool defaults to 30 second timeout."""
        pool = PersistentWorkerPool()
        assert pool.timeout == 30

    def it_creates_pool_with_config_values_via_from_config(self) -> None:
        """from_config creates pool using PoolConfig settings."""
        config = PoolConfig(max_workers=8, timeout=45)
        pool = PersistentWorkerPool.from_config(config)
        assert pool.max_workers == 8
        assert pool.timeout == 45
        assert pool.config is config

    def it_returns_poolconfig_from_config_property(self) -> None:
        """config property returns the PoolConfig used by the pool."""
        config = PoolConfig(max_workers=4)
        pool = PersistentWorkerPool(config=config)
        assert pool.config is config

    def it_creates_with_config_timeout_override(self) -> None:
        """Explicit timeout parameter overrides config timeout."""
        config = PoolConfig(max_workers=4, timeout=60)
        # Explicit timeout of 45 overrides config's 60
        pool = PersistentWorkerPool(config=config, timeout=45)
        assert pool.timeout == 45

    def it_creates_with_config_max_workers_override(self) -> None:
        """Explicit max_workers parameter overrides config max_workers."""
        config = PoolConfig(max_workers=8, timeout=30)
        # Explicit max_workers of 2 overrides config's 8
        pool = PersistentWorkerPool(config=config, max_workers=2)
        assert pool.max_workers == 2


class DescribePersistentWorkerPoolContextManager:
    """Tests for PersistentWorkerPool context manager protocol."""

    @pytest.mark.medium
    def it_can_use_as_context_manager(self) -> None:
        """PersistentWorkerPool supports context manager protocol."""
        with PersistentWorkerPool(max_workers=2) as pool:
            assert isinstance(pool, PersistentWorkerPool)
            assert pool.max_workers == 2

    @pytest.mark.medium
    def it_context_manager_starts_workers(self) -> None:
        """PersistentWorkerPool starts workers on context entry."""
        with PersistentWorkerPool(max_workers=2) as pool:
            assert pool.is_running

    @pytest.mark.medium
    def it_context_manager_shuts_down_on_exit(self) -> None:
        """PersistentWorkerPool shuts down cleanly on context exit."""
        pool = PersistentWorkerPool(max_workers=2)
        with pool:
            pass
        assert not pool.is_running

    @pytest.mark.medium
    def it_enables_warmup_by_default(self) -> None:
        """Pool warms up workers by default when using context manager."""
        config = PoolConfig(max_workers=2, warmup=True)
        pool = PersistentWorkerPool(config=config)
        with pool:
            assert pool.is_warmed_up
            assert pool.warmup_completed_count == 2

    @pytest.mark.medium
    def it_disables_warmup_when_configured(self) -> None:
        """Pool does not warmup when warmup is disabled in config."""
        config = PoolConfig(max_workers=2, warmup=False)
        pool = PersistentWorkerPool(config=config)
        with pool:
            assert not pool.is_warmed_up
            assert pool.warmup_completed_count == 0

    @pytest.mark.small
    def it_handles_shutdown_safely_when_never_started(self) -> None:
        """Calling shutdown on pool that was never started is safe."""
        pool = PersistentWorkerPool(max_workers=2)
        # Never enter context, but call shutdown via __exit__
        pool.__exit__(None, None, None)
        assert not pool.is_running


class DescribePersistentWorkerPoolSubmit:
    """Tests for submitting work to the persistent pool."""

    @pytest.mark.small
    def it_submit_requires_active_context(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium
    def it_submit_returns_future(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium
    def it_submit_multiple_gremlins(self, tmp_path: Path) -> None:
        """Multiple gremlins can be submitted to pool."""
        with PersistentWorkerPool(max_workers=2) as pool:
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

    @pytest.mark.medium
    def it_submit_sets_sources_file_env_when_instrumented_dir_provided(self, tmp_path: Path) -> None:
        """submit sets PYTEST_GREMLINS_SOURCES_FILE when instrumented_dir is provided."""
        script = tmp_path / 'test_script.py'
        script.write_text(
            """
import os
import sys
# Check that the sources file env var is set
sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE', '')
if 'instrumented/sources.json' not in sources_file:
    sys.exit(1)
sys.exit(0)
""",
        )

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


@pytest.mark.medium
class DescribePersistentWorkerPoolExecution:
    """Tests for actual execution in persistent pool."""

    def it_successful_test_returns_zapped_status(self, tmp_path: Path) -> None:
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

    def it_passed_test_returns_survived_status(self, tmp_path: Path) -> None:
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

    def it_includes_gremlin_id(self, tmp_path: Path) -> None:
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


@pytest.mark.medium
class DescribeReturnCodeSemantics:
    """Tests for 3-way return code handling (0=survived, 1=zapped, other=error)."""

    def it_treats_exit_code_0_as_survived(self, tmp_path: Path) -> None:
        """Exit code 0 (tests passed) means the mutation survived."""
        with PersistentWorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'import sys; sys.exit(0)'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.SURVIVED

    def it_treats_exit_code_1_as_zapped(self, tmp_path: Path) -> None:
        """Exit code 1 (tests failed) means the mutation was caught."""
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

    def it_treats_exit_code_2_as_error(self, tmp_path: Path) -> None:
        """Exit code 2+ (pytest internal error) means error, not zapped."""
        with PersistentWorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'import sys; sys.exit(2)'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.ERROR

    def it_treats_exit_code_5_as_error(self, tmp_path: Path) -> None:
        """Exit code 5 (no tests collected) means error, not zapped."""
        with PersistentWorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit(
                gremlin_id='g001',
                test_command=['python', '-c', 'import sys; sys.exit(5)'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            result = future.result(timeout=5)
            assert result.status == GremlinResultStatus.ERROR

    def it_batch_treats_exit_code_2_as_error(self, tmp_path: Path) -> None:
        """Batch execution also treats exit code 2+ as error, not zapped."""
        with PersistentWorkerPool(max_workers=1, timeout=5) as pool:
            future = pool.submit_batch(
                gremlin_ids=['g001'],
                test_command=['python', '-c', 'import sys; sys.exit(2)'],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            results = future.result(timeout=5)
            assert len(results) == 1
            assert results[0].status == GremlinResultStatus.ERROR


class DescribeBatchExecution:
    """Tests for batch execution - running multiple gremlins in one subprocess."""

    @pytest.mark.small
    def it_submit_batch_requires_active_context(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium
    def it_submit_batch_returns_future_with_list_of_results(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium
    def it_submit_batch_tests_each_gremlin_independently(self, tmp_path: Path) -> None:
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

    @pytest.mark.medium
    def it_tests_all_gremlins_in_batch_even_after_zap(self, tmp_path: Path) -> None:
        """Batch tests all gremlins independently, even after one is zapped."""
        # First gremlin survives (tests pass), second fails (tests fail)
        # When using the test command that checks ACTIVE_GREMLIN env var
        script = tmp_path / 'test_script.py'
        script.write_text(
            """
import os
import sys
gremlin = os.environ.get('ACTIVE_GREMLIN')
# g002 is detected (killed), others survive
sys.exit(1 if gremlin == 'g002' else 0)
""",
        )

        with PersistentWorkerPool(max_workers=1, timeout=10) as pool:
            future = pool.submit_batch(
                gremlin_ids=['g001', 'g002', 'g003'],
                test_command=['python', str(script)],
                rootdir=str(tmp_path),
                instrumented_dir=None,
                env_vars={},
            )
            results = future.result(timeout=10)

            # All gremlins tested: g001 survives, g002 zapped, g003 survives
            assert len(results) == 3
            assert results[0].gremlin_id == 'g001'
            assert results[0].status == GremlinResultStatus.SURVIVED
            assert results[1].gremlin_id == 'g002'
            assert results[1].status == GremlinResultStatus.ZAPPED
            assert results[2].gremlin_id == 'g003'
            assert results[2].status == GremlinResultStatus.SURVIVED

    @pytest.mark.medium
    def it_submit_batch_sets_sources_file_env_when_instrumented_dir_provided(self, tmp_path: Path) -> None:
        """submit_batch sets PYTEST_GREMLINS_SOURCES_FILE when instrumented_dir is provided."""
        script = tmp_path / 'test_script.py'
        script.write_text(
            """
import os
import sys
# Check that the sources file env var is set
sources_file = os.environ.get('PYTEST_GREMLINS_SOURCES_FILE', '')
if 'instrumented/sources.json' not in sources_file:
    sys.exit(1)
sys.exit(0)
""",
        )

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
