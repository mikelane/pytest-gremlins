# Coverage Module

The coverage module implements **coverage-guided test selection**, the second pillar of
pytest-gremlins' speed strategy. Instead of running all tests for each gremlin, only tests that
actually cover the mutated code are executed.

## Overview

Traditional mutation testing runs all tests for each mutation:

```text
100 gremlins x 500 tests = 50,000 test executions
```

Coverage-guided selection runs only relevant tests:

```text
100 gremlins x ~5 tests average = 500 test executions
```

This provides **10-100x reduction** in test executions.

## Module Exports

```python
from pytest_gremlins.coverage import (
    CoverageMap,           # Line-to-test mapping
    CoverageCollector,     # Coverage data collection
    TestSelector,          # Basic test selection
    PrioritizedSelector,   # Priority-ordered selection
)
```

---

## CoverageMap

Maps source locations (file:line) to test function names.

::: pytest_gremlins.coverage.mapper.CoverageMap
    options:
      show_root_heading: true
      show_source: true

### CoverageMap Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `add(file, line, test)` | `None` | Add a coverage mapping |
| `get_tests(file, line)` | `set[str]` | Get tests covering a location |
| `locations()` | `Iterator[tuple]` | Iterate over all locations |
| `get_incidentally_tested(threshold)` | `list[tuple]` | Find heavily-tested code |
| `__len__()` | `int` | Number of source locations |
| `__contains__(location)` | `bool` | Check if location is covered |

### Usage Example

```python
from pytest_gremlins.coverage import CoverageMap

# Create a coverage map
coverage_map = CoverageMap()

# Record test coverage
coverage_map.add('src/auth.py', 42, 'test_login_success')
coverage_map.add('src/auth.py', 42, 'test_login_failure')
coverage_map.add('src/auth.py', 43, 'test_login_success')

# Query coverage
tests = coverage_map.get_tests('src/auth.py', 42)
print(tests)  # {'test_login_success', 'test_login_failure'}

# Check if a location is covered
if ('src/auth.py', 42) in coverage_map:
    print('Line 42 is covered')

# Get locations covered by many tests (possibly utility code)
heavily_tested = coverage_map.get_incidentally_tested(threshold=10)
for file_path, line, count in heavily_tested:
    print(f'{file_path}:{line} covered by {count} tests')
```

### Internal Structure

```python
# Internal _data structure:
{
    'src/auth.py:42': {'test_login_success', 'test_login_failure'},
    'src/auth.py:43': {'test_login_success'},
    'src/utils.py:10': {'test_helper'},
}
```

---

## CoverageCollector

Collects coverage data per-test by integrating with coverage.py.

::: pytest_gremlins.coverage.collector.CoverageCollector
    options:
      show_root_heading: true
      show_source: true

### CoverageCollector Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `record_test_coverage(test, data)` | `None` | Record coverage for a test |
| `extract_lines_from_coverage_data(data)` | `dict` | Extract lines from coverage.py data |
| `get_stats()` | `dict` | Get collection statistics |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `coverage_map` | `CoverageMap` | The underlying coverage map |
| `recorded_tests` | `set[str]` | Set of recorded test names |

### Usage Example

```python
from pytest_gremlins.coverage import CoverageCollector

collector = CoverageCollector()

# Record coverage for a test
collector.record_test_coverage(
    'test_login',
    {
        'src/auth.py': [10, 11, 12, 42, 43],
        'src/utils.py': [5, 6, 7],
    }
)

# Get statistics
stats = collector.get_stats()
print(f"Tests: {stats['total_tests']}")
print(f"Locations: {stats['total_locations']}")
print(f"Mappings: {stats['total_mappings']}")

# Access the coverage map
tests = collector.coverage_map.get_tests('src/auth.py', 42)
```

### CoverageDataProtocol

Protocol for coverage.py's CoverageData interface.

::: pytest_gremlins.coverage.collector.CoverageDataProtocol
    options:
      show_root_heading: true
      show_source: true

---

## TestSelector

Selects tests to run for each gremlin based on coverage data.

::: pytest_gremlins.coverage.selector.TestSelector
    options:
      show_root_heading: true
      show_source: true

### TestSelector Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `select_tests(gremlin)` | `set[str]` | Select tests for a gremlin |
| `select_tests_for_location(file, line)` | `set[str]` | Select tests for a location |
| `select_tests_for_gremlins(gremlins)` | `set[str]` | Select tests for multiple gremlins |
| `select_tests_with_stats(gremlin)` | `tuple` | Select tests and return stats |

### Usage Example

```python
from pytest_gremlins.coverage import CoverageMap, TestSelector
from pytest_gremlins.instrumentation import transform_source

# Build coverage map
coverage_map = CoverageMap()
coverage_map.add('example.py', 3, 'test_adult')
coverage_map.add('example.py', 3, 'test_minor')

# Create selector
selector = TestSelector(coverage_map)

# Transform source to get gremlins
source = '''
def is_adult(age):
    return age >= 18
'''
gremlins, _ = transform_source(source, 'example.py')

# Select tests for each gremlin
for gremlin in gremlins:
    tests = selector.select_tests(gremlin)
    print(f'{gremlin.gremlin_id}: {len(tests)} tests')

# Select with statistics
tests, stats = selector.select_tests_with_stats(gremlins[0])
print(f"Selected {stats['selected_count']} tests for {stats['coverage_location']}")
```

---

## PrioritizedSelector

Extends test selection by ordering tests by specificity. Tests covering fewer lines are more
specific and more likely to catch mutations quickly.

::: pytest_gremlins.coverage.prioritized_selector.PrioritizedSelector
    options:
      show_root_heading: true
      show_source: true

### PrioritizedSelector Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_test_specificity()` | `dict[str, int]` | Get line counts per test |
| `select_tests_prioritized(gremlin)` | `list[str]` | Select tests ordered by specificity |
| `select_tests_for_location_prioritized(file, line)` | `list[str]` | Select for location |
| `select_tests_with_stats(gremlin)` | `tuple` | Select with statistics |

### How Prioritization Works

```python
# Test A covers 3 lines
# Test B covers 50 lines
# Test C covers 10 lines

# For a gremlin on line 5 (covered by all three):
# Prioritized order: [Test A, Test C, Test B]
#
# Test A (3 lines) is most specific - runs first
# If Test A catches the mutation, we skip Test B and C
```

### Usage Example

```python
from pytest_gremlins.coverage import CoverageMap, PrioritizedSelector

# Build coverage map
coverage_map = CoverageMap()

# test_specific covers only lines 10-12
coverage_map.add('auth.py', 10, 'test_specific')
coverage_map.add('auth.py', 11, 'test_specific')
coverage_map.add('auth.py', 12, 'test_specific')

# test_broad covers lines 1-100
for line in range(1, 101):
    coverage_map.add('auth.py', line, 'test_broad')

# test_medium covers lines 5-20
for line in range(5, 21):
    coverage_map.add('auth.py', line, 'test_medium')

# Create prioritized selector
selector = PrioritizedSelector(coverage_map)

# Get specificity scores (lower = more specific)
specificity = selector.get_test_specificity()
print(specificity)
# {'test_specific': 3, 'test_medium': 16, 'test_broad': 100}

# Select tests for line 10 (covered by all three)
# Returns: ['test_specific', 'test_medium', 'test_broad']
tests = selector.select_tests_for_location_prioritized('auth.py', 10)
print(tests[0])  # 'test_specific' - most specific, runs first
```

### Statistics

```python
# Get selection with detailed statistics
tests, stats = selector.select_tests_with_stats(gremlin)

print(stats)
# {
#     'selected_count': 3,
#     'coverage_location': 'auth.py:10',
#     'most_specific_test': 'test_specific',
#     'specificity_range': (3, 100),  # (min_lines, max_lines)
# }
```

---

## Integration with pytest

The coverage module integrates with coverage.py's dynamic context feature:

```python
# In plugin.py, pytest-gremlins:
# 1. Runs tests with coverage.py using dynamic_context = test_function
# 2. Extracts per-test coverage from the SQLite database
# 3. Builds the CoverageMap
# 4. Uses PrioritizedSelector for each gremlin
```

### Coverage Collection Flow

```text
pytest_sessionfinish:
    1. Run: coverage run --dynamic-context=test_function pytest
    2. Open .coverage SQLite database
    3. Query contexts (test names) and their covered lines
    4. Build CoverageMap from query results
    5. Create PrioritizedSelector
```

---

## Performance Impact

### Example Scenario

```text
Project: 100 source files, 500 tests
Gremlins: 1000 mutations

Without coverage-guided selection:
  1000 gremlins x 500 tests = 500,000 test runs

With coverage-guided selection:
  Average 5 tests per gremlin = 5,000 test runs

Speedup: 100x
```

### Best Practices

1. **Write focused tests** - Tests covering fewer lines are more specific
2. **Avoid god tests** - Tests that exercise the entire codebase dilute selection
3. **Use pytest -x** - Exit on first failure (works great with prioritization)
4. **Monitor specificity** - Check `get_test_specificity()` for balance
