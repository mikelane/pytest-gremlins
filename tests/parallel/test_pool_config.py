"""Tests for PoolConfig - optimized worker pool configuration.

PoolConfig provides a centralized way to configure the PersistentWorkerPool
with various optimization settings like process start method, warmup, etc.
"""

from __future__ import annotations

import multiprocessing
import sys

import pytest

from pytest_gremlins.parallel.pool_config import (
    PoolConfig,
    get_optimal_start_method,
)


@pytest.mark.small
class DescribePoolConfigCreation:
    """Tests for PoolConfig instantiation."""

    def it_creates_with_defaults(self) -> None:
        """PoolConfig can be created with default values."""
        config = PoolConfig()
        assert config.max_workers >= 1

    def it_creates_with_specified_workers(self) -> None:
        """PoolConfig respects specified worker count."""
        config = PoolConfig(max_workers=4)
        assert config.max_workers == 4

    def it_creates_with_specified_timeout(self) -> None:
        """PoolConfig respects specified timeout."""
        config = PoolConfig(timeout=60)
        assert config.timeout == 60

    def it_default_timeout_is_30_seconds(self) -> None:
        """PoolConfig defaults to 30 second timeout."""
        config = PoolConfig()
        assert config.timeout == 30

    def it_creates_with_start_method(self) -> None:
        """PoolConfig accepts a process start method."""
        config = PoolConfig(start_method='spawn')
        assert config.start_method == 'spawn'

    def it_default_start_method_is_auto(self) -> None:
        """PoolConfig defaults to 'auto' start method."""
        config = PoolConfig()
        assert config.start_method == 'auto'

    def it_creates_with_warmup_enabled(self) -> None:
        """PoolConfig accepts warmup configuration."""
        config = PoolConfig(warmup=True)
        assert config.warmup is True

    def it_default_warmup_is_true(self) -> None:
        """PoolConfig enables warmup by default for performance."""
        config = PoolConfig()
        assert config.warmup is True

    def it_creates_with_batch_size(self) -> None:
        """PoolConfig accepts batch size configuration."""
        config = PoolConfig(batch_size=20)
        assert config.batch_size == 20

    def it_default_batch_size_is_10(self) -> None:
        """PoolConfig defaults to batch size of 10."""
        config = PoolConfig()
        assert config.batch_size == 10


@pytest.mark.small
class DescribePoolConfigValidation:
    """Tests for PoolConfig validation."""

    def it_raises_error_for_invalid_start_method(self) -> None:
        """Invalid start method raises ValueError."""
        with pytest.raises(ValueError, match='Invalid start method'):
            PoolConfig(start_method='invalid')

    @pytest.mark.parametrize('method', ['auto', 'spawn', 'fork', 'forkserver'])
    def it_accepts_valid_start_methods(self, method: str) -> None:
        """Valid start methods are accepted."""
        config = PoolConfig(start_method=method)
        assert config.start_method == method

    def it_max_workers_must_be_positive(self) -> None:
        """max_workers must be positive."""
        with pytest.raises(ValueError, match='max_workers must be positive'):
            PoolConfig(max_workers=0)

        with pytest.raises(ValueError, match='max_workers must be positive'):
            PoolConfig(max_workers=-1)

    def it_timeout_must_be_positive(self) -> None:
        """timeout must be positive."""
        with pytest.raises(ValueError, match='timeout must be positive'):
            PoolConfig(timeout=0)

    def it_requires_positive_batch_size(self) -> None:
        """batch_size must be positive."""
        with pytest.raises(ValueError, match='batch_size must be positive'):
            PoolConfig(batch_size=0)


@pytest.mark.small
class DescribeGetOptimalStartMethod:
    """Tests for get_optimal_start_method function."""

    def it_returns_valid_method(self) -> None:
        """Returns a valid multiprocessing start method."""
        method = get_optimal_start_method()
        assert method in ('spawn', 'fork', 'forkserver')

    def it_returns_available_method(self) -> None:
        """Returns a method that is available on the current platform."""
        method = get_optimal_start_method()
        assert method in multiprocessing.get_all_start_methods()

    def it_prefers_forkserver_on_supported_platforms(self) -> None:
        """Prefers forkserver on platforms that support it."""
        method = get_optimal_start_method()
        available = multiprocessing.get_all_start_methods()
        if 'forkserver' in available:
            assert method == 'forkserver'

    def it_falls_back_to_spawn_on_windows(self) -> None:
        """Falls back to spawn on Windows (where forkserver is unavailable)."""
        if sys.platform == 'win32':
            method = get_optimal_start_method()
            assert method == 'spawn'


@pytest.mark.small
class DescribePoolConfigMpContext:
    """Tests for PoolConfig multiprocessing context creation."""

    def it_returns_mp_context(self) -> None:
        """get_mp_context returns a multiprocessing context."""
        config = PoolConfig(start_method='spawn')
        ctx = config.get_mp_context()
        assert ctx.get_start_method() == 'spawn'

    def it_uses_specified_start_method_for_mp_context(self) -> None:
        """get_mp_context uses the specified start method."""
        config = PoolConfig(start_method='spawn')
        ctx = config.get_mp_context()
        # The context should use spawn method
        assert ctx.get_start_method() == 'spawn'

    def it_uses_optimal_method_when_auto_is_set(self) -> None:
        """get_mp_context with 'auto' uses the optimal method."""
        config = PoolConfig(start_method='auto')
        ctx = config.get_mp_context()
        optimal = get_optimal_start_method()
        assert ctx.get_start_method() == optimal


@pytest.mark.small
class DescribePoolConfigExecutor:
    """Tests for PoolConfig executor strategy field."""

    def it_defaults_to_subprocess(self) -> None:
        config = PoolConfig()
        assert config.executor == 'subprocess'

    @pytest.mark.parametrize('executor', ['auto', 'subprocess', 'fork', 'inprocess'])
    def it_accepts_valid_executors(self, executor: str) -> None:
        config = PoolConfig(executor=executor)
        assert config.executor == executor

    def it_rejects_unknown_executor(self) -> None:
        with pytest.raises(ValueError, match='executor must be one of'):
            PoolConfig(executor='magic')


@pytest.mark.small
class DescribePoolConfigEquality:
    """Tests for PoolConfig equality and hashing."""

    def it_considers_equal_configs_as_equal(self) -> None:
        """Two configs with same values are equal."""
        config1 = PoolConfig(max_workers=4, timeout=30)
        config2 = PoolConfig(max_workers=4, timeout=30)
        assert config1 == config2

    def it_considers_different_configs_as_not_equal(self) -> None:
        """Two configs with different values are not equal."""
        config1 = PoolConfig(max_workers=4)
        config2 = PoolConfig(max_workers=8)
        assert config1 != config2
