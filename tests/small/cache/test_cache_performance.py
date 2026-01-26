"""Performance tests for content hashing (pure computation).

These tests verify that hashing operations are fast. They use only
in-memory computation with no I/O, suitable for SMALL tests.

Tests that use SQLite I/O have been moved to tests/medium/test_store_performance.py.
"""

import time

import pytest

from pytest_gremlins.cache.hasher import ContentHasher


@pytest.mark.small
class TestHasherPerformance:
    """Performance tests for content hashing."""

    def test_string_hashing_is_fast(self) -> None:
        """Hashing a typical source file completes in under 1ms."""
        hasher = ContentHasher()

        # Simulate a typical 500-line Python file (~15KB)
        content = '\n'.join([f'def function_{i}(): return {i}' for i in range(500)])

        start = time.perf_counter()
        for _ in range(100):
            hasher.hash_string(content)
        elapsed = time.perf_counter() - start

        # 100 hashes should take less than 100ms (1ms per hash)
        assert elapsed < 0.1, f'String hashing took {elapsed * 1000:.1f}ms for 100 hashes'

    def test_combined_hash_is_fast(self) -> None:
        """Combining multiple hashes completes in under 0.1ms."""
        hasher = ContentHasher()

        # 10 test file hashes
        hashes = [hasher.hash_string(f'test_content_{i}') for i in range(10)]

        start = time.perf_counter()
        for _ in range(1000):
            hasher.hash_combined(hashes)
        elapsed = time.perf_counter() - start

        # 1000 combines should take less than 100ms (0.1ms per combine)
        assert elapsed < 0.1, f'Combined hash took {elapsed * 1000:.1f}ms for 1000 combines'
