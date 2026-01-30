# Getting Started

This guide will help you get pytest-gremlins up and running with your project in under five minutes.

## What is Mutation Testing?

Mutation testing measures test suite quality by injecting small bugs (mutations) into your code and checking if your tests catch them. If a mutation survives (tests still pass), you have a gap in your test coverage.

pytest-gremlins calls these mutations "gremlins" - and your job is to zap them with good tests.

## Requirements

Before you begin, ensure you have:

- Python 3.11 or later
- pytest 7.0 or later
- A project with existing tests

## Installation

### Using pip

```bash
pip install pytest-gremlins
```

### Using uv (recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package manager. Install pytest-gremlins as a development dependency:

```bash
uv add --dev pytest-gremlins
```

### Using poetry

```bash
poetry add --group dev pytest-gremlins
```

### Using pipx (for CLI tools)

If you want to run pytest-gremlins across multiple projects without installing it in each:

```bash
pipx install pytest-gremlins
```

### Verifying Installation

Verify the installation by checking pytest's help:

```bash
pytest --help | grep gremlins
```

You should see the `--gremlins` option listed.

## First Mutation Test Walkthrough

Let's walk through mutation testing with a simple example project.

### Step 1: Create a Sample Project

Create a file `calculator.py`:

```python
# calculator.py
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def is_positive(n: int) -> bool:
    """Check if a number is positive."""
    return n > 0

def divide(a: int, b: int) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

### Step 2: Create Tests

Create a file `test_calculator.py`:

```python
# test_calculator.py
import pytest
from calculator import add, is_positive, divide

def test_add_positive_numbers():
    assert add(2, 3) == 5

def test_add_negative_numbers():
    assert add(-1, -1) == -2

def test_is_positive_returns_true():
    assert is_positive(5) is True

def test_is_positive_returns_false():
    assert is_positive(-5) is False

def test_divide_basic():
    assert divide(10, 2) == 5.0

def test_divide_by_zero_raises():
    with pytest.raises(ValueError):
        divide(10, 0)
```

### Step 3: Run Normal Tests First

Ensure your tests pass before running mutation testing:

```bash
pytest test_calculator.py -v
```

Expected output:

```
test_calculator.py::test_add_positive_numbers PASSED
test_calculator.py::test_add_negative_numbers PASSED
test_calculator.py::test_is_positive_returns_true PASSED
test_calculator.py::test_is_positive_returns_false PASSED
test_calculator.py::test_divide_basic PASSED
test_calculator.py::test_divide_by_zero_raises PASSED

6 passed
```

### Step 4: Run Mutation Testing

Now unleash the gremlins:

```bash
pytest --gremlins --gremlin-targets=calculator.py test_calculator.py
```

pytest-gremlins will:

1. **Instrument your code** - Parse source files and embed all possible mutations
2. **Build coverage map** - Run tests once to determine which tests cover which code
3. **Feed the gremlins** - Activate each mutation and run relevant tests
4. **Report results** - Show which gremlins survived (test gaps) and which were zapped

### Step 5: Understand the Output

You will see output similar to:

```text
================== pytest-gremlins mutation report ==================

Zapped: 8 gremlins (80%)
Survived: 2 gremlins (20%)

Top surviving gremlins:
  src/auth.py:42    >= to >     (boundary not tested)
  src/utils.py:17   + to -      (arithmetic not verified)
  src/api.py:88     True to False (return value unchecked)

Run with --gremlin-report=html for detailed report.
=====================================================================
```

**Understanding the results:**

| Term | Meaning |
|------|---------|
| **Zapped** | Your tests caught these mutations - good! |
| **Survived** | Your tests missed these mutations - these are test gaps |
| **Mutation Score** | Percentage of gremlins zapped (higher is better) |

In this example, two gremlins survived:

1. **`> -> >=` on line 7** - Changing `n > 0` to `n >= 0` in `is_positive()` was not caught. This means we are not testing the boundary case `n = 0`.

2. **`== -> !=` on line 12** - Changing `b == 0` to `b != 0` in `divide()` was not caught. This is because our test only checks that the exception is raised, not that normal division works correctly in all cases.

### Step 6: Fix the Test Gaps

Add tests to catch the surviving gremlins:

```python
def test_is_positive_zero():
    """Zero is not positive - catches the >= mutation."""
    assert is_positive(0) is False

def test_divide_non_zero_divisor():
    """Verify division works with non-zero divisor."""
    result = divide(6, 3)
    assert result == 2.0
```

### Step 7: Re-run Mutation Testing

```bash
pytest --gremlins --gremlin-targets=calculator.py test_calculator.py
```

Now you should see:

```
================== pytest-gremlins mutation report ==================

Zapped: 10 gremlins (100%)
Survived: 0 gremlins (0%)

=====================================================================
```

All gremlins zapped - your tests are now more robust.

## Understanding the Workflow

pytest-gremlins follows this workflow for speed:

```
1. Instrument Code
   - Parse Python AST
   - Embed all mutations with switches
   - No file I/O during test runs

2. Build Coverage Map
   - Run tests once with coverage tracking
   - Map tests to lines they cover
   - 10-100x reduction in test runs

3. Test Gremlins
   - For each gremlin, run ONLY relevant tests
   - Stop on first test failure (early exit)
   - Parallel execution available

4. Report Results
   - Console summary (default)
   - HTML reports for detailed analysis
   - JSON for CI integration
```

## Common Beginner Questions

### How long does mutation testing take?

Mutation testing is computationally intensive because it runs your test suite multiple times. pytest-gremlins uses several optimizations:

- **Coverage-guided selection**: Only runs tests that cover the mutated code
- **Early exit**: Stops testing a gremlin as soon as one test fails
- **Incremental caching**: Skips unchanged code on subsequent runs (use `--gremlin-cache`)
- **Parallel execution**: Distributes gremlins across CPU cores (use `--gremlin-parallel`)

For a first run, expect 10-100x the time of a normal test run. Subsequent cached runs are much faster.

### What mutation score should I aim for?

A good target depends on your project:

| Score | Interpretation |
|-------|----------------|
| < 60% | Significant test gaps exist |
| 60-80% | Average coverage, room for improvement |
| 80-90% | Good coverage for most projects |
| > 90% | Excellent coverage (may have diminishing returns) |

Some mutations are "equivalent" - they produce identical behavior to the original code. A 100% score is often impossible and not worth pursuing.

### Which files should I mutate?

Focus on:

- **Business logic** - Core functionality that must be correct
- **Security-critical code** - Authentication, authorization, validation
- **Financial calculations** - Money handling, pricing, taxes

Skip:

- **Configuration files** - Static data, settings
- **Migration scripts** - One-time database operations
- **Generated code** - Auto-generated files

### How do I run mutation testing in CI?

Add a step to your CI pipeline:

```yaml
- name: Run mutation testing
  run: |
    pytest --gremlins --gremlin-report=json
    SCORE=$(jq '.summary.percentage' gremlin-report.json)
    if (( $(echo "$SCORE < 80" | bc -l) )); then
      echo "Mutation score $SCORE% is below threshold 80%"
      exit 1
    fi
```

This runs mutation testing, outputs a JSON report, then checks if the mutation score meets your threshold.

### What if mutation testing is too slow?

Try these strategies:

1. **Start small**: Target specific files with `--gremlin-targets`
2. **Use incremental mode**: `--gremlin-cache` skips unchanged code
3. **Enable parallel execution**: `--gremlin-parallel`
4. **Focus operators**: `--gremlin-operators=comparison,boolean`
5. **Run in CI only**: Skip mutation testing in local development

## Next Steps

Now that you understand the basics:

- [Configuration](configuration.md) - Customize behavior via `pyproject.toml` or CLI
- [Operators](operators.md) - Learn about available mutation types
- [Reports](reports.md) - Generate HTML and JSON reports for detailed analysis

## Quick Reference

| Task | Command |
|------|---------|
| Basic mutation testing | `pytest --gremlins` |
| Target specific files | `pytest --gremlins --gremlin-targets=src/mymodule.py` |
| Generate HTML report | `pytest --gremlins --gremlin-report=html` |
| Use caching | `pytest --gremlins --gremlin-cache` |
| Parallel execution | `pytest --gremlins --gremlin-parallel` |
| Use specific operators | `pytest --gremlins --gremlin-operators=comparison,boolean` |
