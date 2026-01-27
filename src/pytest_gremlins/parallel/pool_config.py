"""Configuration for optimized worker pool settings.

This module provides the PoolConfig class for configuring the PersistentWorkerPool
with various optimization settings:

- **Process Start Method**: Choose between 'spawn', 'fork', or 'forkserver'.
  'forkserver' is generally fastest on Linux/macOS as it forks from a pre-warmed
  server process. On Windows, only 'spawn' is available.

- **Worker Warmup**: Pre-warm workers immediately after pool creation to reduce
  latency on the first batch of work.

- **Batch Size**: Configure how many gremlins are processed per subprocess call.

Example:
    >>> config = PoolConfig(max_workers=4, start_method='forkserver', warmup=True)
    >>> config.max_workers
    4
    >>> config.start_method
    'forkserver'
"""

from __future__ import annotations

from dataclasses import dataclass, field
import multiprocessing
import os
from typing import Literal


StartMethod = Literal['auto', 'spawn', 'fork', 'forkserver']
VALID_START_METHODS: frozenset[str] = frozenset(('auto', 'spawn', 'fork', 'forkserver'))


def get_optimal_start_method() -> Literal['spawn', 'fork', 'forkserver']:
    """Determine the optimal process start method for the current platform.

    The start method affects subprocess creation performance:
    - 'forkserver': Fastest on Linux/macOS. Forks from a pre-warmed server process.
    - 'spawn': Default on Windows. Creates fresh interpreter, slowest but safest.
    - 'fork': Fast but unsafe with threads or certain libraries.

    Returns:
        The optimal start method for the current platform.

    Example:
        >>> method = get_optimal_start_method()
        >>> method in ('spawn', 'fork', 'forkserver')
        True
    """
    available = multiprocessing.get_all_start_methods()

    # Prefer forkserver on platforms that support it (Linux, macOS)
    # It's faster than spawn and safer than fork
    if 'forkserver' in available:
        return 'forkserver'

    # Fall back to spawn (always available)
    return 'spawn'


def _default_max_workers() -> int:
    """Return the default number of workers."""
    return os.cpu_count() or 4


@dataclass(frozen=True, eq=True)
class PoolConfig:
    """Configuration for the persistent worker pool.

    This dataclass encapsulates all configuration options for the worker pool,
    allowing for easy customization and validation of pool settings.

    Attributes:
        max_workers: Maximum number of worker processes. Defaults to CPU count.
        timeout: Timeout in seconds for individual gremlin tests. Defaults to 30.
        start_method: Process start method ('auto', 'spawn', 'fork', 'forkserver').
        warmup: Whether to pre-warm workers on pool startup. Defaults to True.
        batch_size: Number of gremlins per batch. Defaults to 10.

    Example:
        >>> config = PoolConfig(max_workers=4, timeout=60)
        >>> config.max_workers
        4
        >>> config.timeout
        60
    """

    max_workers: int = field(default_factory=_default_max_workers)
    timeout: int = 30
    start_method: StartMethod = 'auto'
    warmup: bool = True
    batch_size: int = 10

    def __post_init__(self) -> None:
        """Validate configuration values.

        Raises:
            ValueError: If any configuration value is invalid.
        """
        if self.start_method not in VALID_START_METHODS:
            msg = f'Invalid start method: {self.start_method!r}. Valid methods are: {sorted(VALID_START_METHODS)}'
            raise ValueError(msg)

        if self.max_workers <= 0:
            msg = f'max_workers must be positive, got {self.max_workers}'
            raise ValueError(msg)

        if self.timeout <= 0:
            msg = f'timeout must be positive, got {self.timeout}'
            raise ValueError(msg)

        if self.batch_size <= 0:
            msg = f'batch_size must be positive, got {self.batch_size}'
            raise ValueError(msg)

    def get_mp_context(self) -> multiprocessing.context.BaseContext:
        """Create a multiprocessing context with the configured start method.

        If start_method is 'auto', uses the optimal method for the platform.

        Returns:
            A multiprocessing context configured with the appropriate start method.

        Example:
            >>> config = PoolConfig(start_method='spawn')
            >>> ctx = config.get_mp_context()
            >>> ctx.get_start_method()
            'spawn'
        """
        method = self.start_method
        if method == 'auto':
            method = get_optimal_start_method()

        return multiprocessing.get_context(method)
