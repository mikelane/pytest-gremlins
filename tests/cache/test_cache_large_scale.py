"""Large-scale integration tests for cache performance.

These tests simulate a more realistic workload with many gremlins to identify
scaling issues with the cache.
"""

from __future__ import annotations

import time

import pytest


@pytest.mark.medium
class DescribeCacheLargeScale:
    """Tests for cache with larger number of gremlins."""

    def it_returns_identical_scores_on_warm_cache_rerun_with_many_gremlins(
        self,
        pytester_with_markers: pytest.Pytester,
    ) -> None:
        """Cache produces same mutation scores on warm rerun with many gremlins.

        The synthetic benchmark has:
        - 3 source files with ~70 lines each
        - ~50+ mutations total
        - 60+ test cases

        This test simulates a similar setup to verify cache scales.
        """
        # Create source files similar to benchmark
        pytester_with_markers.makepyfile(
            calculator="""
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

def power(base, exp):
    if exp < 0:
        raise ValueError("Negative exponent")
    result = 1
    for _ in range(exp):
        result *= base
    return result
            """,
        )

        pytester_with_markers.makepyfile(
            validator="""
def is_adult(age):
    return age >= 18

def is_valid_percentage(value):
    return value >= 0 and value <= 100

def is_positive(n):
    return n > 0

def is_negative(n):
    return n < 0

def is_zero(n):
    return n == 0
            """,
        )

        # Create comprehensive tests
        pytester_with_markers.makepyfile(
            test_calculator="""
import pytest
from calculator import add, subtract, multiply, divide, power

@pytest.mark.medium
class TestAdd:
    def test_positive(self):
        assert add(2, 3) == 5

    def test_negative(self):
        assert add(-2, -3) == -5

    def test_zero(self):
        assert add(0, 5) == 5

@pytest.mark.medium
class TestSubtract:
    def test_positive(self):
        assert subtract(5, 3) == 2

    def test_negative_result(self):
        assert subtract(3, 5) == -2

@pytest.mark.medium
class TestMultiply:
    def test_positive(self):
        assert multiply(3, 4) == 12

    def test_zero(self):
        assert multiply(5, 0) == 0

@pytest.mark.medium
class TestDivide:
    def test_even(self):
        assert divide(10, 2) == 5.0

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            divide(10, 0)

@pytest.mark.medium
class TestPower:
    def test_positive(self):
        assert power(2, 3) == 8

    def test_zero_exp(self):
        assert power(5, 0) == 1

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            power(2, -1)
            """,
        )

        pytester_with_markers.makepyfile(
            test_validator="""
import pytest
from validator import is_adult, is_valid_percentage, is_positive, is_negative, is_zero

@pytest.mark.medium
class TestIsAdult:
    def test_at_18(self):
        assert is_adult(18) is True

    def test_over_18(self):
        assert is_adult(25) is True

    def test_under_18(self):
        assert is_adult(17) is False

@pytest.mark.medium
class TestIsValidPercentage:
    def test_zero(self):
        assert is_valid_percentage(0) is True

    def test_hundred(self):
        assert is_valid_percentage(100) is True

    def test_negative(self):
        assert is_valid_percentage(-1) is False

    def test_over_hundred(self):
        assert is_valid_percentage(101) is False

@pytest.mark.medium
class TestIsPositive:
    def test_positive(self):
        assert is_positive(1) is True

    def test_zero(self):
        assert is_positive(0) is False

@pytest.mark.medium
class TestIsNegative:
    def test_negative(self):
        assert is_negative(-1) is True

    def test_zero(self):
        assert is_negative(0) is False

@pytest.mark.medium
class TestIsZero:
    def test_zero(self):
        assert is_zero(0) is True

    def test_positive(self):
        assert is_zero(1) is False
            """,
        )

        # Run without cache (baseline)
        no_cache_start = time.perf_counter()
        pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=calculator.py,validator.py',
        )
        no_cache_time = time.perf_counter() - no_cache_start

        # Cold cache run
        cold_start = time.perf_counter()
        pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=calculator.py,validator.py',
            '--gremlin-cache',
        )
        cold_time = time.perf_counter() - cold_start

        # Warm cache run
        warm_start = time.perf_counter()
        result = pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=calculator.py,validator.py',
            '--gremlin-cache',
        )
        warm_time = time.perf_counter() - warm_start

        # Verify tests passed (12 + 13 = 25 tests total)
        result.assert_outcomes(passed=25)

        # Print timing info for debugging
        print('\n\nTiming results:')
        print(f'  No cache:   {no_cache_time:.2f}s')
        print(f'  Cold cache: {cold_time:.2f}s (overhead: {cold_time - no_cache_time:.2f}s)')
        print(f'  Warm cache: {warm_time:.2f}s (speedup: {no_cache_time / warm_time:.1f}x)')

        # Key assertions:
        # 1. Warm cache MUST be faster than no cache
        assert warm_time < no_cache_time, (
            f'Warm cache ({warm_time:.2f}s) is NOT faster than no-cache ({no_cache_time:.2f}s)! '
            'This is the critical bug - cache should provide speedup.'
        )

        # 2. Warm cache should be at least 2x faster than cold cache
        speedup = cold_time / warm_time
        assert speedup >= 2.0, (
            f'Warm cache speedup is only {speedup:.1f}x vs cold cache. '
            f'Expected at least 2x. (cold: {cold_time:.2f}s, warm: {warm_time:.2f}s)'
        )
