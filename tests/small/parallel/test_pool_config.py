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
class TestPoolConfigCreation:
    """Tests for PoolConfig instantiation."""

    def test_creates_with_defaults(self) -> None:
        """PoolConfig can be created with default values."""
        config = PoolConfig()
        assert config.max_workers is not None
        assert config.max_workers >= 1

    def test_creates_with_specified_workers(self) -> None:
        """PoolConfig respects specified worker count."""
        config = PoolConfig(max_workers=4)
        assert config.max_workers == 4

    def test_creates_with_specified_timeout(self) -> None:
        """PoolConfig respects specified timeout."""
        config = PoolConfig(timeout=60)
        assert config.timeout == 60

    def test_default_timeout_is_30_seconds(self) -> None:
        """PoolConfig defaults to 30 second timeout."""
        config = PoolConfig()
        assert config.timeout == 30

    def test_creates_with_start_method(self) -> None:
        """PoolConfig accepts a process start method."""
        config = PoolConfig(start_method='spawn')
        assert config.start_method == 'spawn'

    def test_default_start_method_is_auto(self) -> None:
        """PoolConfig defaults to 'auto' start method."""
        config = PoolConfig()
        assert config.start_method == 'auto'

    def test_creates_with_warmup_enabled(self) -> None:
        """PoolConfig accepts warmup configuration."""
        config = PoolConfig(warmup=True)
        assert config.warmup is True

    def test_default_warmup_is_true(self) -> None:
        """PoolConfig enables warmup by default for performance."""
        config = PoolConfig()
        assert config.warmup is True

    def test_creates_with_batch_size(self) -> None:
        """PoolConfig accepts batch size configuration."""
        config = PoolConfig(batch_size=20)
        assert config.batch_size == 20

    def test_default_batch_size_is_10(self) -> None:
        """PoolConfig defaults to batch size of 10."""
        config = PoolConfig()
        assert config.batch_size == 10


@pytest.mark.small
class TestPoolConfigValidation:
    """Tests for PoolConfig validation."""

    def test_invalid_start_method_raises_error(self) -> None:
        """Invalid start method raises ValueError."""
        with pytest.raises(ValueError, match='Invalid start method'):
            PoolConfig(start_method='invalid')

    def test_valid_start_methods_are_accepted(self) -> None:
        """Valid start methods are accepted."""
        for method in ('auto', 'spawn', 'fork', 'forkserver'):
            config = PoolConfig(start_method=method)
            assert config.start_method == method

    def test_max_workers_must_be_positive(self) -> None:
        """max_workers must be positive."""
        with pytest.raises(ValueError, match='max_workers must be positive'):
            PoolConfig(max_workers=0)

        with pytest.raises(ValueError, match='max_workers must be positive'):
            PoolConfig(max_workers=-1)

    def test_timeout_must_be_positive(self) -> None:
        """timeout must be positive."""
        with pytest.raises(ValueError, match='timeout must be positive'):
            PoolConfig(timeout=0)

    def test_batch_size_must_be_positive(self) -> None:
        """batch_size must be positive."""
        with pytest.raises(ValueError, match='batch_size must be positive'):
            PoolConfig(batch_size=0)


@pytest.mark.small
class TestGetOptimalStartMethod:
    """Tests for get_optimal_start_method function."""

    def test_returns_valid_method(self) -> None:
        """Returns a valid multiprocessing start method."""
        method = get_optimal_start_method()
        assert method in ('spawn', 'fork', 'forkserver')

    def test_returns_available_method(self) -> None:
        """Returns a method that is available on the current platform."""
        method = get_optimal_start_method()
        assert method in multiprocessing.get_all_start_methods()

    def test_prefers_forkserver_on_supported_platforms(self) -> None:
        """Prefers forkserver on platforms that support it."""
        method = get_optimal_start_method()
        available = multiprocessing.get_all_start_methods()
        if 'forkserver' in available:
            assert method == 'forkserver'

    def test_falls_back_to_spawn_on_windows(self) -> None:
        """Falls back to spawn on Windows (where forkserver is unavailable)."""
        if sys.platform == 'win32':
            method = get_optimal_start_method()
            assert method == 'spawn'


@pytest.mark.small
class TestPoolConfigMpContext:
    """Tests for PoolConfig multiprocessing context creation."""

    def test_get_mp_context_returns_context(self) -> None:
        """get_mp_context returns a multiprocessing context."""
        config = PoolConfig(start_method='spawn')
        ctx = config.get_mp_context()
        assert ctx is not None

    def test_get_mp_context_uses_specified_method(self) -> None:
        """get_mp_context uses the specified start method."""
        config = PoolConfig(start_method='spawn')
        ctx = config.get_mp_context()
        # The context should use spawn method
        assert ctx.get_start_method() == 'spawn'

    def test_get_mp_context_with_auto_uses_optimal(self) -> None:
        """get_mp_context with 'auto' uses the optimal method."""
        config = PoolConfig(start_method='auto')
        ctx = config.get_mp_context()
        optimal = get_optimal_start_method()
        assert ctx.get_start_method() == optimal


@pytest.mark.small
class TestPoolConfigEquality:
    """Tests for PoolConfig equality and hashing."""

    def test_equal_configs_are_equal(self) -> None:
        """Two configs with same values are equal."""
        config1 = PoolConfig(max_workers=4, timeout=30)
        config2 = PoolConfig(max_workers=4, timeout=30)
        assert config1 == config2

    def test_different_configs_are_not_equal(self) -> None:
        """Two configs with different values are not equal."""
        config1 = PoolConfig(max_workers=4)
        config2 = PoolConfig(max_workers=8)
        assert config1 != config2
