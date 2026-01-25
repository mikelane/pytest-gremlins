#!/usr/bin/env python
"""Benchmark pytest-gremlins vs mutmut.

This script provides fair, reproducible benchmarks comparing pytest-gremlins
with mutmut across various configurations and project sizes.

Usage:
    python benchmarks/run_benchmarks.py --project synthetic --output results/
    python benchmarks/run_benchmarks.py --project attrs --output results/
    python benchmarks/run_benchmarks.py --all --output results/

Fair Benchmarking Principles:
- Same test suite for both tools
- Same mutation operators (where possible)
- Same hardware/environment
- Multiple runs with statistics
- Both tools with optimal settings for their architecture

Known Limitations:
- mutmut 3.x has a Python 3.14 compatibility issue (set_start_method RuntimeError)
- For fair benchmarks, use Python 3.12 or 3.13
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run.

    Attributes:
        tool: Name of the tool (mutmut or gremlins).
        project: Name of the test project.
        config: Configuration name (e.g., 'default', 'parallel').
        wall_time_seconds: Total execution time in seconds.
        mutations_total: Total number of mutations generated.
        mutations_killed: Number of mutations caught by tests.
        peak_memory_mb: Peak memory usage in MB (if available).
        run_number: Which run this is (for multiple runs).
        error: Error message if the run failed.
    """

    tool: str
    project: str
    config: str
    wall_time_seconds: float
    mutations_total: int = 0
    mutations_killed: int = 0
    peak_memory_mb: float = 0.0
    run_number: int = 1
    error: str | None = None


@dataclass
class BenchmarkSummary:
    """Summary statistics for multiple runs.

    Attributes:
        tool: Name of the tool.
        project: Name of the test project.
        config: Configuration name.
        mean_time: Mean execution time in seconds.
        stddev_time: Standard deviation of execution time.
        min_time: Minimum execution time.
        max_time: Maximum execution time.
        mutations_total: Total mutations (should be consistent).
        mutations_killed: Mutations killed (should be consistent).
        runs: Number of runs.
    """

    tool: str
    project: str
    config: str
    mean_time: float
    stddev_time: float
    min_time: float
    max_time: float
    mutations_total: int
    mutations_killed: int
    runs: int


@dataclass
class EnvironmentInfo:
    """Information about the benchmark environment.

    Attributes:
        timestamp: When the benchmark was run.
        platform: Operating system info.
        python_version: Python version.
        cpu_info: CPU information.
        cpu_count: Number of CPU cores.
        memory_gb: Total memory in GB.
        mutmut_version: mutmut version if available.
        gremlins_version: pytest-gremlins version if available.
    """

    timestamp: str
    platform: str
    python_version: str
    cpu_info: str
    cpu_count: int
    memory_gb: float
    mutmut_version: str = 'unknown'
    gremlins_version: str = 'unknown'


@dataclass
class ProjectConfig:
    """Configuration for a benchmark project.

    Attributes:
        name: Project name.
        source_url: Git URL to clone the project.
        source_dir: Relative path to source directory.
        test_dir: Relative path to test directory.
        setup_commands: Commands to run after cloning.
        mutmut_configs: Configuration options for mutmut runs.
        gremlins_configs: Configuration options for gremlins runs.
    """

    name: str
    source_url: str | None = None
    source_dir: str = 'src'
    test_dir: str = 'tests'
    setup_commands: list[str] = field(default_factory=list)
    mutmut_configs: dict[str, list[str]] = field(default_factory=dict)
    gremlins_configs: dict[str, list[str]] = field(default_factory=dict)


SYNTHETIC_PROJECT = ProjectConfig(
    name='synthetic',
    source_url=None,  # Will be created locally
    source_dir='src',
    test_dir='tests',
    setup_commands=['uv venv', 'uv pip install pytest mutmut coverage'],
    # mutmut 3.x has limited CLI options - most config is in pyproject.toml
    mutmut_configs={
        'default': [],
        'max-4-children': ['--max-children=4'],  # Parallel workers
    },
    gremlins_configs={
        'sequential': ['--gremlins', '--gremlin-targets=src/'],
        'parallel': ['--gremlins', '--gremlin-targets=src/', '--gremlin-parallel'],
        'with-cache': ['--gremlins', '--gremlin-targets=src/', '--gremlin-cache'],
        'full': ['--gremlins', '--gremlin-targets=src/', '--gremlin-parallel', '--gremlin-cache'],
    },
)


def get_environment_info() -> EnvironmentInfo:
    """Collect information about the benchmark environment.

    Returns:
        EnvironmentInfo with system details.
    """
    import psutil  # noqa: PLC0415

    # Get mutmut version
    mutmut_version = 'not installed'
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'mutmut', 'version'],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            mutmut_version = result.stdout.strip()
    except Exception:  # noqa: S110
        pass

    # Get gremlins version
    gremlins_version = 'not installed'
    try:
        import pytest_gremlins  # noqa: PLC0415

        gremlins_version = pytest_gremlins.__version__
    except Exception:  # noqa: S110
        pass

    return EnvironmentInfo(
        timestamp=datetime.now().isoformat(),
        platform=f'{platform.system()} {platform.release()}',
        python_version=platform.python_version(),
        cpu_info=platform.processor() or 'unknown',
        cpu_count=os.cpu_count() or 1,
        memory_gb=round(psutil.virtual_memory().total / (1024**3), 1),
        mutmut_version=mutmut_version,
        gremlins_version=gremlins_version,
    )


def create_synthetic_project(work_dir: Path) -> Path:
    """Create a synthetic benchmark project.

    Creates a small but representative Python project with:
    - Multiple source files with various mutation targets
    - Comprehensive tests that cover most code
    - Realistic code patterns (conditionals, loops, arithmetic)

    Args:
        work_dir: Directory to create the project in.

    Returns:
        Path to the created project.
    """
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

    # Create pyproject.toml
    # Note: mutmut 3.x uses different config keys than 2.x
    (project_dir / 'pyproject.toml').write_text("""\
[project]
name = "synthetic-benchmark"
version = "0.1.0"
requires-python = ">=3.11"

[tool.mutmut]
paths_to_mutate = ["src/synthetic/"]
pytest_add_cli_args_test_selection = ["tests/"]
""")

    return project_dir


def check_python_version_for_mutmut() -> str | None:
    """Check if the Python version is compatible with mutmut.

    Returns:
        Error message if incompatible, None if compatible.
    """
    version = sys.version_info
    if version >= (3, 14):
        return (
            f'mutmut 3.x has a known incompatibility with Python {version.major}.{version.minor}. '
            'The set_start_method() call fails. Use Python 3.12 or 3.13 for fair benchmarks.'
        )
    return None


def run_mutmut(  # noqa: C901, PLR0912
    project_dir: Path,
    config_name: str,
    extra_args: list[str],
) -> BenchmarkResult:
    """Run mutmut benchmark.

    Note: mutmut 3.x uses config from pyproject.toml, not CLI flags.
    The old flags like --paths-to-mutate and --tests-dir don't exist.

    Args:
        project_dir: Path to the project directory.
        config_name: Name of this configuration.
        extra_args: Additional command-line arguments.

    Returns:
        BenchmarkResult with timing and mutation data.
    """
    # Check Python version compatibility
    version_error = check_python_version_for_mutmut()
    if version_error:
        return BenchmarkResult(
            tool='mutmut',
            project='synthetic',
            config=config_name,
            wall_time_seconds=0,
            error=version_error,
        )

    # Clear any previous mutmut state
    cache_dir = project_dir / '.mutmut-cache'
    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    # mutmut 3.x reads config from pyproject.toml
    # Only pass extra_args that are valid for mutmut 3.x
    valid_args = [arg for arg in extra_args if arg.startswith('--max-children')]
    cmd = [
        sys.executable,
        '-m',
        'mutmut',
        'run',
        *valid_args,
    ]

    env = os.environ.copy()
    env['PYTHONPATH'] = str(project_dir / 'src')

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

        # Check for the Python 3.14 set_start_method error
        if 'set_start_method' in result.stderr and 'RuntimeError' in result.stderr:
            return BenchmarkResult(
                tool='mutmut',
                project='synthetic',
                config=config_name,
                wall_time_seconds=wall_time,
                error='mutmut Python 3.14 incompatibility: set_start_method RuntimeError',
            )

        # Parse mutmut results
        mutations_total = 0
        mutations_killed = 0

        # Try to get results from mutmut results command
        results_cmd = [sys.executable, '-m', 'mutmut', 'results']
        results_output = subprocess.run(
            results_cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            check=False,
        )

        if results_output.returncode == 0:
            output = results_output.stdout
            # Parse output for counts
            for line in output.splitlines():
                if 'killed' in line.lower():
                    # Try to extract numbers
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part.isdigit() and 'killed' in ' '.join(parts[max(0, i - 2) : i + 2]).lower():
                            mutations_killed = int(part)
                if 'survived' in line.lower() or 'total' in line.lower():
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part.isdigit() and 'survived' in ' '.join(parts[max(0, i - 2) : i + 2]).lower():
                            mutations_total = mutations_killed + int(part)

        # Fallback: try to count from cache
        if mutations_total == 0 and cache_dir.exists():
            # mutmut stores results in SQLite, but for now estimate from output
            mutations_total = result.stdout.count('mutant') + result.stderr.count('mutant')

        return BenchmarkResult(
            tool='mutmut',
            project='synthetic',
            config=config_name,
            wall_time_seconds=wall_time,
            mutations_total=mutations_total,
            mutations_killed=mutations_killed,
        )

    except subprocess.TimeoutExpired:
        return BenchmarkResult(
            tool='mutmut',
            project='synthetic',
            config=config_name,
            wall_time_seconds=600,
            error='Timeout after 600 seconds',
        )
    except Exception as e:
        return BenchmarkResult(
            tool='mutmut',
            project='synthetic',
            config=config_name,
            wall_time_seconds=0,
            error=str(e),
        )


def run_gremlins(  # noqa: C901
    project_dir: Path,
    config_name: str,
    extra_args: list[str],
) -> BenchmarkResult:
    """Run pytest-gremlins benchmark.

    Args:
        project_dir: Path to the project directory.
        config_name: Name of this configuration.
        extra_args: Additional command-line arguments.

    Returns:
        BenchmarkResult with timing and mutation data.
    """
    # Clear any previous gremlins cache
    cache_dir = project_dir / '.gremlins_cache'
    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    cmd = [
        sys.executable,
        '-m',
        'pytest',
        'tests/',
        *extra_args,
    ]

    env = os.environ.copy()
    env['PYTHONPATH'] = str(project_dir / 'src')

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

        # Parse gremlins results from output
        mutations_total = 0
        mutations_killed = 0

        output = result.stdout + result.stderr

        # Look for patterns like "Zapped: X gremlins" and "Survived: Y gremlins"
        for line in output.splitlines():
            if 'Zapped:' in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'Zapped:' and i + 1 < len(parts):
                        with contextlib.suppress(ValueError):
                            mutations_killed = int(parts[i + 1])
            if 'Survived:' in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'Survived:' and i + 1 < len(parts):
                        with contextlib.suppress(ValueError):
                            survived = int(parts[i + 1])
                            mutations_total = mutations_killed + survived

        return BenchmarkResult(
            tool='gremlins',
            project='synthetic',
            config=config_name,
            wall_time_seconds=wall_time,
            mutations_total=mutations_total,
            mutations_killed=mutations_killed,
        )

    except subprocess.TimeoutExpired:
        return BenchmarkResult(
            tool='gremlins',
            project='synthetic',
            config=config_name,
            wall_time_seconds=600,
            error='Timeout after 600 seconds',
        )
    except Exception as e:
        return BenchmarkResult(
            tool='gremlins',
            project='synthetic',
            config=config_name,
            wall_time_seconds=0,
            error=str(e),
        )


def run_benchmark_suite(
    project_dir: Path,
    project_config: ProjectConfig,
    runs: int = 3,
) -> list[BenchmarkResult]:
    """Run complete benchmark suite for a project.

    Runs both mutmut and gremlins with various configurations,
    multiple times each for statistical significance.

    Args:
        project_dir: Path to the project directory.
        project_config: Configuration for the project.
        runs: Number of runs per configuration.

    Returns:
        List of BenchmarkResult for all runs.
    """
    results: list[BenchmarkResult] = []

    # Install dependencies
    print(f'Setting up project: {project_config.name}')

    env = os.environ.copy()
    env['PYTHONPATH'] = str(project_dir / 'src')

    # Verify pytest works
    verify_cmd = [sys.executable, '-m', 'pytest', 'tests/', '--collect-only', '-q']
    verify_result = subprocess.run(
        verify_cmd,
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if verify_result.returncode != 0:
        print(f'Warning: Test collection failed: {verify_result.stderr}')

    # Run mutmut benchmarks
    print('\n--- Running mutmut benchmarks ---')
    for config_name, extra_args in project_config.mutmut_configs.items():
        print(f'  Configuration: {config_name}')
        for run in range(1, runs + 1):
            print(f'    Run {run}/{runs}...', end=' ', flush=True)
            result = run_mutmut(project_dir, config_name, extra_args)
            result.run_number = run
            results.append(result)
            if result.error:
                print(f'ERROR: {result.error}')
            else:
                print(f'{result.wall_time_seconds:.2f}s')

    # Run gremlins benchmarks
    print('\n--- Running pytest-gremlins benchmarks ---')
    for config_name, extra_args in project_config.gremlins_configs.items():
        print(f'  Configuration: {config_name}')
        for run in range(1, runs + 1):
            print(f'    Run {run}/{runs}...', end=' ', flush=True)
            result = run_gremlins(project_dir, config_name, extra_args)
            result.run_number = run
            results.append(result)
            if result.error:
                print(f'ERROR: {result.error}')
            else:
                print(f'{result.wall_time_seconds:.2f}s')

    return results


def compute_summaries(results: list[BenchmarkResult]) -> list[BenchmarkSummary]:
    """Compute summary statistics from benchmark results.

    Groups results by tool/project/config and computes mean, stddev, etc.

    Args:
        results: List of BenchmarkResult.

    Returns:
        List of BenchmarkSummary with aggregated statistics.
    """
    # Group by (tool, project, config)
    groups: dict[tuple[str, str, str], list[BenchmarkResult]] = {}
    for result in results:
        if result.error:
            continue
        key = (result.tool, result.project, result.config)
        if key not in groups:
            groups[key] = []
        groups[key].append(result)

    summaries = []
    for (tool, project, config), group in groups.items():
        times = [r.wall_time_seconds for r in group]
        if not times:
            continue

        mean_time = statistics.mean(times)
        stddev_time = statistics.stdev(times) if len(times) > 1 else 0
        min_time = min(times)
        max_time = max(times)

        # Use last run's mutation counts (should be consistent)
        last = group[-1]

        summaries.append(
            BenchmarkSummary(
                tool=tool,
                project=project,
                config=config,
                mean_time=mean_time,
                stddev_time=stddev_time,
                min_time=min_time,
                max_time=max_time,
                mutations_total=last.mutations_total,
                mutations_killed=last.mutations_killed,
                runs=len(group),
            )
        )

    return summaries


def generate_markdown_report(
    env_info: EnvironmentInfo,
    summaries: list[BenchmarkSummary],
    results: list[BenchmarkResult],
) -> str:
    """Generate a markdown report from benchmark results.

    Args:
        env_info: Environment information.
        summaries: Summary statistics.
        results: Raw results.

    Returns:
        Markdown formatted report.
    """
    lines = [
        '# pytest-gremlins Benchmark Results',
        '',
        f'**Date**: {env_info.timestamp}',
        f'**Platform**: {env_info.platform}',
        f'**Python**: {env_info.python_version}',
        f'**CPU**: {env_info.cpu_info} ({env_info.cpu_count} cores)',
        f'**Memory**: {env_info.memory_gb} GB',
        '',
        f'**mutmut version**: {env_info.mutmut_version}',
        f'**pytest-gremlins version**: {env_info.gremlins_version}',
        '',
        '## Summary',
        '',
        '| Tool | Config | Mean Time | Std Dev | Mutations | Killed |',
        '|------|--------|-----------|---------|-----------|--------|',
    ]

    for s in sorted(summaries, key=lambda x: (x.tool, x.config)):
        kill_rate = (s.mutations_killed / s.mutations_total * 100) if s.mutations_total > 0 else 0
        lines.append(
            f'| {s.tool} | {s.config} | {s.mean_time:.2f}s | '
            f'{s.stddev_time:.2f}s | {s.mutations_total} | '
            f'{s.mutations_killed} ({kill_rate:.0f}%) |'
        )

    # Add speedup comparison
    lines.extend(
        [
            '',
            '## Speedup Analysis',
            '',
        ]
    )

    # Find mutmut baseline (default config)
    mutmut_default = next(
        (s for s in summaries if s.tool == 'mutmut' and s.config == 'default'),
        None,
    )

    if mutmut_default:
        lines.append(f'**Baseline**: mutmut default = {mutmut_default.mean_time:.2f}s')
        lines.append('')
        lines.append('| gremlins Config | Time | Speedup vs mutmut default |')
        lines.append('|-----------------|------|---------------------------|')

        for s in summaries:
            if s.tool == 'gremlins':
                speedup = mutmut_default.mean_time / s.mean_time if s.mean_time > 0 else 0
                lines.append(f'| {s.config} | {s.mean_time:.2f}s | {speedup:.1f}x |')

    # Add raw results
    lines.extend(
        [
            '',
            '## Raw Results',
            '',
            '<details>',
            '<summary>Click to expand raw results</summary>',
            '',
            '```json',
            json.dumps([asdict(r) for r in results], indent=2),
            '```',
            '</details>',
            '',
            '## Methodology',
            '',
            '1. Both tools run on the same synthetic benchmark project',
            '2. Each configuration run 3 times (configurable)',
            '3. Results include mean and standard deviation',
            '4. Caches are cleared between runs',
            '5. Same Python version and environment for both tools',
            '',
            '## Interpreting Results',
            '',
            '- **Mean Time**: Average wall-clock time across runs',
            '- **Std Dev**: Variation between runs (lower is more consistent)',
            '- **Mutations**: Total mutations generated (should be similar)',
            '- **Killed**: Mutations caught by tests (test effectiveness)',
            '- **Speedup**: How many times faster than baseline',
            '',
            '### Configuration Descriptions',
            '',
            '**mutmut**:',
            '- `default`: Standard mutmut run',
            '- `no-backup`: Skip backup file creation',
            '',
            '**pytest-gremlins**:',
            '- `sequential`: No parallelization or caching',
            '- `parallel`: Multiple workers for mutation testing',
            '- `with-cache`: Incremental analysis caching',
            '- `full`: All optimizations enabled',
        ]
    )

    return '\n'.join(lines)


def main() -> int:  # noqa: PLR0915
    """Run the benchmark suite.

    Returns:
        Exit code (0 for success).
    """
    parser = argparse.ArgumentParser(
        description='Benchmark pytest-gremlins vs mutmut',
    )
    parser.add_argument(
        '--project',
        choices=['synthetic', 'attrs', 'all'],
        default='synthetic',
        help='Project to benchmark (default: synthetic)',
    )
    parser.add_argument(
        '--runs',
        type=int,
        default=3,
        help='Number of runs per configuration (default: 3)',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('benchmarks/results'),
        help='Output directory for results (default: benchmarks/results)',
    )

    args = parser.parse_args()

    # Check for required dependencies
    try:
        import psutil  # noqa: F401, PLC0415
    except ImportError:
        print('Error: psutil is required. Install with: pip install psutil')
        return 1

    # Collect environment info
    print('Collecting environment information...')
    try:
        env_info = get_environment_info()
    except Exception as e:
        print(f'Warning: Could not collect full environment info: {e}')
        env_info = EnvironmentInfo(
            timestamp=datetime.now().isoformat(),
            platform=f'{platform.system()} {platform.release()}',
            python_version=platform.python_version(),
            cpu_info='unknown',
            cpu_count=os.cpu_count() or 1,
            memory_gb=0,
        )

    print('\nEnvironment:')
    print(f'  Platform: {env_info.platform}')
    print(f'  Python: {env_info.python_version}')
    print(f'  CPU: {env_info.cpu_info} ({env_info.cpu_count} cores)')
    print(f'  mutmut: {env_info.mutmut_version}')
    print(f'  gremlins: {env_info.gremlins_version}')

    all_results: list[BenchmarkResult] = []

    # Run benchmarks
    if args.project in ('synthetic', 'all'):
        print('\n' + '=' * 60)
        print('Running synthetic benchmark')
        print('=' * 60)

        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            project_dir = create_synthetic_project(work_dir)
            results = run_benchmark_suite(project_dir, SYNTHETIC_PROJECT, runs=args.runs)
            all_results.extend(results)

    if args.project in ('attrs', 'all'):
        print('\n' + '=' * 60)
        print('Running attrs benchmark (not implemented yet)')
        print('=' * 60)
        # TODO: Implement real project benchmarks

    # Compute summaries
    summaries = compute_summaries(all_results)

    # Generate report
    report = generate_markdown_report(env_info, summaries, all_results)

    # Save results
    args.output.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = args.output / f'benchmark_{timestamp}.md'
    report_path.write_text(report)
    print(f'\nReport saved to: {report_path}')

    # Also save JSON for programmatic access
    json_path = args.output / f'benchmark_{timestamp}.json'
    json_data = {
        'environment': asdict(env_info),
        'summaries': [asdict(s) for s in summaries],
        'results': [asdict(r) for r in all_results],
    }
    json_path.write_text(json.dumps(json_data, indent=2))
    print(f'JSON data saved to: {json_path}')

    # Print summary
    print('\n' + '=' * 60)
    print('BENCHMARK SUMMARY')
    print('=' * 60)

    for s in sorted(summaries, key=lambda x: (x.tool, x.config)):
        print(f'{s.tool:12} {s.config:15} {s.mean_time:8.2f}s (+/- {s.stddev_time:.2f}s)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
