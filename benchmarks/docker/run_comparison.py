#!/usr/bin/env python
"""Run fair benchmark comparison between pytest-gremlins and mutmut.

This script runs inside a Docker container with both tools installed
and a compatible Python version (3.12) to avoid mutmut's macOS issues.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class BenchmarkResult:
    """Result from a benchmark run."""
    tool: str
    config: str
    wall_time_seconds: float
    mutations_total: int
    mutations_killed: int
    error: str | None = None


def create_synthetic_project(work_dir: Path) -> Path:
    """Create a synthetic benchmark project."""
    project_dir = work_dir / 'synthetic_project'
    src_dir = project_dir / 'src' / 'synthetic'
    test_dir = project_dir / 'tests'

    src_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)

    # Create __init__.py
    (src_dir / '__init__.py').write_text('"""Synthetic benchmark package."""\n')

    # Create calculator.py - arithmetic operations
    (src_dir / 'calculator.py').write_text('''\
"""Basic calculator with arithmetic operations."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract b from a."""
    return a - b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def divide(a: int, b: int) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def power(base: int, exponent: int) -> int:
    """Raise base to exponent."""
    if exponent < 0:
        raise ValueError("Negative exponents not supported")
    result = 1
    for _ in range(exponent):
        result *= base
    return result
''')

    # Create validator.py - comparison and boolean operations
    (src_dir / 'validator.py').write_text('''\
"""Validation functions with comparisons and booleans."""


def is_adult(age: int) -> bool:
    """Check if person is an adult (18 or older)."""
    return age >= 18


def is_valid_percentage(value: float) -> bool:
    """Check if value is a valid percentage (0-100)."""
    return value >= 0 and value <= 100


def is_in_range(value: int, min_val: int, max_val: int) -> bool:
    """Check if value is within range (inclusive)."""
    return value >= min_val and value <= max_val


def validate_email_length(email: str) -> bool:
    """Check if email length is valid (3-254 chars)."""
    length = len(email)
    return length >= 3 and length <= 254


def is_positive(number: int) -> bool:
    """Check if number is positive."""
    return number > 0


def is_negative(number: int) -> bool:
    """Check if number is negative."""
    return number < 0


def is_zero(number: int) -> bool:
    """Check if number is zero."""
    return number == 0
''')

    # Create processor.py - more complex logic
    (src_dir / 'processor.py').write_text('''\
"""Data processing functions."""


def clamp(value: int, min_val: int, max_val: int) -> int:
    """Clamp value to range."""
    if value < min_val:
        return min_val
    if value > max_val:
        return max_val
    return value


def grade_score(score: int) -> str:
    """Convert numeric score to letter grade."""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def factorial(n: int) -> int:
    """Calculate factorial of n."""
    if n < 0:
        raise ValueError("Factorial not defined for negative numbers")
    if n <= 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def fibonacci(n: int) -> int:
    """Calculate nth Fibonacci number."""
    if n < 0:
        raise ValueError("Fibonacci not defined for negative numbers")
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def count_evens(numbers: list[int]) -> int:
    """Count even numbers in list."""
    count = 0
    for num in numbers:
        if num % 2 == 0:
            count += 1
    return count
''')

    # Create comprehensive tests
    (test_dir / '__init__.py').write_text('')

    (test_dir / 'test_calculator.py').write_text('''\
"""Tests for calculator module."""
import pytest
from synthetic.calculator import add, subtract, multiply, divide, power


class TestAdd:
    def test_add_positive_numbers(self):
        assert add(2, 3) == 5

    def test_add_negative_numbers(self):
        assert add(-2, -3) == -5

    def test_add_mixed_signs(self):
        assert add(-2, 3) == 1

    def test_add_zero(self):
        assert add(0, 5) == 5


class TestSubtract:
    def test_subtract_positive_numbers(self):
        assert subtract(5, 3) == 2

    def test_subtract_negative_result(self):
        assert subtract(3, 5) == -2

    def test_subtract_zero(self):
        assert subtract(5, 0) == 5


class TestMultiply:
    def test_multiply_positive(self):
        assert multiply(3, 4) == 12

    def test_multiply_by_zero(self):
        assert multiply(5, 0) == 0

    def test_multiply_negative(self):
        assert multiply(-3, 4) == -12


class TestDivide:
    def test_divide_evenly(self):
        assert divide(10, 2) == 5.0

    def test_divide_with_remainder(self):
        assert divide(7, 2) == 3.5

    def test_divide_by_zero_raises(self):
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            divide(10, 0)


class TestPower:
    def test_power_positive(self):
        assert power(2, 3) == 8

    def test_power_zero_exponent(self):
        assert power(5, 0) == 1

    def test_power_one_exponent(self):
        assert power(5, 1) == 5

    def test_power_negative_exponent_raises(self):
        with pytest.raises(ValueError, match="Negative exponents"):
            power(2, -1)
''')

    (test_dir / 'test_validator.py').write_text('''\
"""Tests for validator module."""
from synthetic.validator import (
    is_adult,
    is_valid_percentage,
    is_in_range,
    validate_email_length,
    is_positive,
    is_negative,
    is_zero,
)


class TestIsAdult:
    def test_adult_at_18(self):
        assert is_adult(18) is True

    def test_adult_over_18(self):
        assert is_adult(25) is True

    def test_not_adult_under_18(self):
        assert is_adult(17) is False


class TestIsValidPercentage:
    def test_valid_zero(self):
        assert is_valid_percentage(0) is True

    def test_valid_hundred(self):
        assert is_valid_percentage(100) is True

    def test_valid_middle(self):
        assert is_valid_percentage(50) is True

    def test_invalid_negative(self):
        assert is_valid_percentage(-1) is False

    def test_invalid_over_hundred(self):
        assert is_valid_percentage(101) is False


class TestIsInRange:
    def test_in_range_min(self):
        assert is_in_range(0, 0, 10) is True

    def test_in_range_max(self):
        assert is_in_range(10, 0, 10) is True

    def test_in_range_middle(self):
        assert is_in_range(5, 0, 10) is True

    def test_below_range(self):
        assert is_in_range(-1, 0, 10) is False

    def test_above_range(self):
        assert is_in_range(11, 0, 10) is False


class TestValidateEmailLength:
    def test_valid_min_length(self):
        assert validate_email_length("a@b") is True

    def test_valid_normal_length(self):
        assert validate_email_length("test@example.com") is True

    def test_invalid_too_short(self):
        assert validate_email_length("ab") is False


class TestIsPositive:
    def test_positive(self):
        assert is_positive(1) is True

    def test_zero_not_positive(self):
        assert is_positive(0) is False

    def test_negative_not_positive(self):
        assert is_positive(-1) is False


class TestIsNegative:
    def test_negative(self):
        assert is_negative(-1) is True

    def test_zero_not_negative(self):
        assert is_negative(0) is False

    def test_positive_not_negative(self):
        assert is_negative(1) is False


class TestIsZero:
    def test_zero(self):
        assert is_zero(0) is True

    def test_positive_not_zero(self):
        assert is_zero(1) is False

    def test_negative_not_zero(self):
        assert is_zero(-1) is False
''')

    (test_dir / 'test_processor.py').write_text('''\
"""Tests for processor module."""
import pytest
from synthetic.processor import clamp, grade_score, factorial, fibonacci, count_evens


class TestClamp:
    def test_clamp_below_min(self):
        assert clamp(5, 10, 20) == 10

    def test_clamp_above_max(self):
        assert clamp(25, 10, 20) == 20

    def test_clamp_in_range(self):
        assert clamp(15, 10, 20) == 15

    def test_clamp_at_min(self):
        assert clamp(10, 10, 20) == 10

    def test_clamp_at_max(self):
        assert clamp(20, 10, 20) == 20


class TestGradeScore:
    def test_grade_a(self):
        assert grade_score(95) == "A"
        assert grade_score(90) == "A"

    def test_grade_b(self):
        assert grade_score(85) == "B"
        assert grade_score(80) == "B"

    def test_grade_c(self):
        assert grade_score(75) == "C"
        assert grade_score(70) == "C"

    def test_grade_d(self):
        assert grade_score(65) == "D"
        assert grade_score(60) == "D"

    def test_grade_f(self):
        assert grade_score(55) == "F"
        assert grade_score(0) == "F"


class TestFactorial:
    def test_factorial_zero(self):
        assert factorial(0) == 1

    def test_factorial_one(self):
        assert factorial(1) == 1

    def test_factorial_small(self):
        assert factorial(5) == 120

    def test_factorial_negative_raises(self):
        with pytest.raises(ValueError, match="not defined for negative"):
            factorial(-1)


class TestFibonacci:
    def test_fibonacci_zero(self):
        assert fibonacci(0) == 0

    def test_fibonacci_one(self):
        assert fibonacci(1) == 1

    def test_fibonacci_small(self):
        assert fibonacci(10) == 55

    def test_fibonacci_negative_raises(self):
        with pytest.raises(ValueError, match="not defined for negative"):
            fibonacci(-1)


class TestCountEvens:
    def test_count_evens_mixed(self):
        assert count_evens([1, 2, 3, 4, 5, 6]) == 3

    def test_count_evens_all_even(self):
        assert count_evens([2, 4, 6]) == 3

    def test_count_evens_all_odd(self):
        assert count_evens([1, 3, 5]) == 0

    def test_count_evens_empty(self):
        assert count_evens([]) == 0
''')

    # Create pyproject.toml for mutmut 2.x
    (project_dir / 'pyproject.toml').write_text("""\
[project]
name = "synthetic-benchmark"
version = "0.1.0"
requires-python = ">=3.11"
""")

    return project_dir


def run_mutmut(project_dir: Path, runs: int = 3) -> list[BenchmarkResult]:
    """Run mutmut benchmark."""
    results = []

    env = os.environ.copy()
    env['PYTHONPATH'] = str(project_dir / 'src')

    for run in range(1, runs + 1):
        print(f"  mutmut run {run}/{runs}...", end=" ", flush=True)

        # Clear cache
        cache_path = project_dir / '.mutmut-cache'
        if cache_path.exists():
            if cache_path.is_dir():
                shutil.rmtree(cache_path)
            else:
                cache_path.unlink()

        cmd = [
            sys.executable, '-m', 'mutmut', 'run',
            '--paths-to-mutate=src/',
            '--tests-dir=tests/',
        ]

        start_time = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            wall_time = time.perf_counter() - start_time

            # Parse results
            mutations_total = 0
            mutations_killed = 0

            # mutmut 2.x output pattern
            import re
            output = result.stdout + result.stderr
            pattern = r'(\d+)/(\d+)\s+🎉\s+(\d+)'
            matches = list(re.finditer(pattern, output))
            if matches:
                match = matches[-1]
                mutations_total = int(match.group(2))
                mutations_killed = int(match.group(3))

            print(f"{wall_time:.2f}s ({mutations_killed}/{mutations_total} killed)")

            results.append(BenchmarkResult(
                tool='mutmut',
                config='default',
                wall_time_seconds=wall_time,
                mutations_total=mutations_total,
                mutations_killed=mutations_killed,
            ))

        except subprocess.TimeoutExpired:
            print("TIMEOUT")
            results.append(BenchmarkResult(
                tool='mutmut',
                config='default',
                wall_time_seconds=600,
                mutations_total=0,
                mutations_killed=0,
                error='Timeout',
            ))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append(BenchmarkResult(
                tool='mutmut',
                config='default',
                wall_time_seconds=0,
                mutations_total=0,
                mutations_killed=0,
                error=str(e),
            ))

    return results


def run_gremlins(project_dir: Path, config_name: str, extra_args: list[str], runs: int = 3) -> list[BenchmarkResult]:
    """Run pytest-gremlins benchmark."""
    results = []

    env = os.environ.copy()
    env['PYTHONPATH'] = str(project_dir / 'src')

    for run in range(1, runs + 1):
        print(f"  gremlins {config_name} run {run}/{runs}...", end=" ", flush=True)

        # Clear cache
        cache_dir = project_dir / '.gremlins_cache'
        if cache_dir.exists():
            shutil.rmtree(cache_dir)

        cmd = [
            sys.executable, '-m', 'pytest',
            'tests/',
            '--gremlins',
            '--gremlin-targets=src/',
            *extra_args,
        ]

        start_time = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            wall_time = time.perf_counter() - start_time

            # Parse results
            mutations_total = 0
            mutations_killed = 0

            output = result.stdout + result.stderr
            for line in output.splitlines():
                if 'Zapped:' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'Zapped:' and i + 1 < len(parts):
                            try:
                                mutations_killed = int(parts[i + 1])
                            except ValueError:
                                pass
                if 'Survived:' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'Survived:' and i + 1 < len(parts):
                            try:
                                survived = int(parts[i + 1])
                                mutations_total = mutations_killed + survived
                            except ValueError:
                                pass

            print(f"{wall_time:.2f}s ({mutations_killed}/{mutations_total} killed)")

            results.append(BenchmarkResult(
                tool='gremlins',
                config=config_name,
                wall_time_seconds=wall_time,
                mutations_total=mutations_total,
                mutations_killed=mutations_killed,
            ))

        except subprocess.TimeoutExpired:
            print("TIMEOUT")
            results.append(BenchmarkResult(
                tool='gremlins',
                config=config_name,
                wall_time_seconds=600,
                mutations_total=0,
                mutations_killed=0,
                error='Timeout',
            ))
        except Exception as e:
            print(f"ERROR: {e}")
            results.append(BenchmarkResult(
                tool='gremlins',
                config=config_name,
                wall_time_seconds=0,
                mutations_total=0,
                mutations_killed=0,
                error=str(e),
            ))

    return results


def main() -> int:
    """Run the benchmark comparison."""
    import statistics

    print("=" * 60)
    print("pytest-gremlins vs mutmut Benchmark Comparison")
    print("=" * 60)
    print()

    # Show versions
    print("Environment:")
    print(f"  Python: {sys.version.split()[0]}")

    try:
        result = subprocess.run(
            [sys.executable, '-m', 'mutmut', 'version'],
            capture_output=True, text=True, check=False
        )
        print(f"  mutmut: {result.stdout.strip()}")
    except Exception:
        print("  mutmut: unknown")

    try:
        import pytest_gremlins
        print(f"  pytest-gremlins: {pytest_gremlins.__version__}")
    except Exception:
        print("  pytest-gremlins: unknown")

    print()

    runs = 3

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        project_dir = create_synthetic_project(work_dir)

        # Verify tests work
        print("Verifying test suite...")
        env = os.environ.copy()
        env['PYTHONPATH'] = str(project_dir / 'src')
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests/', '-v', '--tb=short'],
            cwd=str(project_dir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"Test suite failed:\n{result.stdout}\n{result.stderr}")
            return 1
        print("  Tests pass ✓")
        print()

        all_results: list[BenchmarkResult] = []

        # Run mutmut
        print("Running mutmut benchmarks...")
        all_results.extend(run_mutmut(project_dir, runs=runs))
        print()

        # Run gremlins - sequential
        print("Running pytest-gremlins benchmarks...")
        all_results.extend(run_gremlins(project_dir, 'sequential', [], runs=runs))

        # Run gremlins - parallel
        all_results.extend(run_gremlins(project_dir, 'parallel', ['--gremlin-parallel'], runs=runs))

        # Run gremlins - full
        all_results.extend(run_gremlins(
            project_dir, 'full',
            ['--gremlin-parallel', '--gremlin-cache', '--gremlin-batch'],
            runs=runs
        ))
        print()

    # Compute summaries
    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print()

    groups: dict[tuple[str, str], list[BenchmarkResult]] = {}
    for r in all_results:
        if r.error:
            continue
        key = (r.tool, r.config)
        if key not in groups:
            groups[key] = []
        groups[key].append(r)

    summaries = []
    for (tool, config), group in sorted(groups.items()):
        times = [r.wall_time_seconds for r in group]
        mean_time = statistics.mean(times)
        stddev = statistics.stdev(times) if len(times) > 1 else 0
        mutations = group[-1].mutations_total
        killed = group[-1].mutations_killed
        summaries.append({
            'tool': tool,
            'config': config,
            'mean': mean_time,
            'stddev': stddev,
            'mutations': mutations,
            'killed': killed,
        })
        print(f"{tool:12} {config:12} {mean_time:8.2f}s (+/- {stddev:.2f}s)  {killed}/{mutations} killed")

    print()

    # Compute speedups
    mutmut_time = next((s['mean'] for s in summaries if s['tool'] == 'mutmut'), None)
    if mutmut_time:
        print("Speedup vs mutmut:")
        for s in summaries:
            if s['tool'] == 'gremlins':
                speedup = mutmut_time / s['mean'] if s['mean'] > 0 else 0
                print(f"  {s['config']:12} {speedup:.2f}x faster")

    print()

    # Output JSON for programmatic use
    output = {
        'results': [asdict(r) for r in all_results],
        'summaries': summaries,
    }
    print("JSON Output:")
    print(json.dumps(output, indent=2))

    return 0


if __name__ == '__main__':
    sys.exit(main())
