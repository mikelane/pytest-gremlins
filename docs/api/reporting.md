# Reporting Module

The reporting module provides data structures and reporters for presenting mutation testing results
in various formats: console, HTML, and JSON.

## Overview

After mutation testing completes, results need to be presented clearly:

- **Console**: Quick summary during development
- **HTML**: Detailed visual report for review
- **JSON**: Machine-readable for CI integration

## Module Exports

```python
from pytest_gremlins.reporting import (
    GremlinResult,       # Individual mutation test result
    GremlinResultStatus, # Status enum (ZAPPED, SURVIVED, etc.)
    MutationScore,       # Aggregated statistics
    ConsoleReporter,     # Terminal output
    HtmlReporter,        # HTML file output
    JsonReporter,        # JSON file output
)
```

---

## GremlinResult

Represents the outcome of testing a single gremlin (mutation).

::: pytest_gremlins.reporting.results.GremlinResult
    options:
      show_root_heading: true
      show_source: true

### GremlinResult Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `gremlin` | `Gremlin` | The tested gremlin |
| `status` | `GremlinResultStatus` | Test outcome |
| `killing_test` | `str \| None` | Test that caught the mutation |
| `execution_time_ms` | `float \| None` | Execution time |

### GremlinResult Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_zapped` | `bool` | `True` if caught by tests |
| `is_survived` | `bool` | `True` if escaped tests |

### Usage Example

```python
from pytest_gremlins.reporting import GremlinResult, GremlinResultStatus
from pytest_gremlins.instrumentation import Gremlin

# Create a result
result = GremlinResult(
    gremlin=gremlin,
    status=GremlinResultStatus.ZAPPED,
    killing_test='test_boundary_check',
    execution_time_ms=45.2,
)

if result.is_zapped:
    print(f'Caught by {result.killing_test}')
elif result.is_survived:
    print(f'TEST GAP: {result.gremlin.description}')
```

---

## GremlinResultStatus

Enum of possible mutation test outcomes.

::: pytest_gremlins.reporting.results.GremlinResultStatus
    options:
      show_root_heading: true
      show_source: true

### Status Values

| Value | Meaning | Good/Bad |
|-------|---------|----------|
| `ZAPPED` | Test caught the mutation | Good - tests working |
| `SURVIVED` | Mutation not caught | Bad - test gap found |
| `TIMEOUT` | Test execution timed out | Neutral - may indicate infinite loop |
| `ERROR` | Error during execution | Neutral - investigate |

### Usage Example

```python
from pytest_gremlins.reporting import GremlinResultStatus

status = GremlinResultStatus.ZAPPED
print(status.value)  # 'zapped'

# Compare statuses
if result.status == GremlinResultStatus.SURVIVED:
    print('Test gap found!')
```

---

## MutationScore

Aggregated mutation testing statistics.

::: pytest_gremlins.reporting.score.MutationScore
    options:
      show_root_heading: true
      show_source: true

### MutationScore Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `total` | `int` | Total gremlins tested |
| `zapped` | `int` | Gremlins caught by tests |
| `survived` | `int` | Gremlins that escaped |
| `timeout` | `int` | Gremlins that timed out |
| `error` | `int` | Gremlins with errors |
| `results` | `tuple[GremlinResult, ...]` | All results |

### MutationScore Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `from_results(results)` | `MutationScore` | Create from result list |
| `percentage` | `float` | Score as percentage (0-100) |
| `by_file()` | `dict[str, MutationScore]` | Breakdown by file |
| `top_survivors(limit)` | `list[GremlinResult]` | Top N survivors |

### Score Calculation

The mutation score represents test effectiveness:

```text
score = (zapped + timeout) / total * 100
```

Timeouts count as "caught" because the test detected abnormal behavior.

### Usage Example

```python
from pytest_gremlins.reporting import MutationScore

# Create score from results
score = MutationScore.from_results(results)

print(f'Mutation Score: {score.percentage:.1f}%')
print(f'Total: {score.total}')
print(f'Zapped: {score.zapped}')
print(f'Survived: {score.survived}')

# Breakdown by file
by_file = score.by_file()
for file_path, file_score in by_file.items():
    print(f'{file_path}: {file_score.percentage:.1f}%')

# Show top surviving gremlins
print('\nTop survivors:')
for result in score.top_survivors(limit=5):
    g = result.gremlin
    print(f'  {g.file_path}:{g.line_number} - {g.description}')
```

---

## Reporters

### ConsoleReporter

Writes human-readable output to the terminal.

::: pytest_gremlins.reporting.console.ConsoleReporter
    options:
      show_root_heading: true
      show_source: true
      members:
        - "__init__"
        - write_report

### Console Output Format

```text
================== pytest-gremlins mutation report ==================

Zapped: 142 gremlins (89%)
Survived: 18 gremlins (11%)

Top surviving gremlins:
  src/auth.py:42          >= to >          (comparison)
  src/utils.py:17         + to -           (arithmetic)
  src/validate.py:23      True to False    (boolean)

Run with --gremlin-report=html for detailed report.
=====================================================================
```

### Usage Example

```python
from pytest_gremlins.reporting import ConsoleReporter, MutationScore

reporter = ConsoleReporter()
score = MutationScore.from_results(results)
reporter.write_report(score)

# Write to file instead of stdout
with open('report.txt', 'w') as f:
    reporter = ConsoleReporter(output=f)
    reporter.write_report(score)
```

---

### HtmlReporter

Generates standalone HTML reports with embedded CSS.

::: pytest_gremlins.reporting.html.HtmlReporter
    options:
      show_root_heading: true
      show_source: true
      members:
        - to_html
        - write_report

### HTML Report Features

- **Summary cards**: Total, zapped, survived, score percentage
- **Results table**: All gremlins with status, file, line, operator
- **Color coding**: Green for zapped, red for survived
- **Responsive design**: Works on desktop and mobile
- **Self-contained**: No external dependencies

### HtmlReporter Example

```python
from pathlib import Path
from pytest_gremlins.reporting import HtmlReporter, MutationScore

reporter = HtmlReporter()
score = MutationScore.from_results(results)

# Write to file
reporter.write_report(score, Path('mutation_report.html'))

# Or get HTML string
html = reporter.to_html(score)
```

### HTML Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <title>pytest-gremlins Mutation Report</title>
    <style>/* Embedded CSS */</style>
</head>
<body>
    <div class="container">
        <h1>pytest-gremlins Mutation Report</h1>
        <div class="summary">
            <!-- Summary cards -->
        </div>
        <table>
            <!-- Results table -->
        </table>
    </div>
</body>
</html>
```

---

### JsonReporter

Produces machine-readable JSON for CI integration.

::: pytest_gremlins.reporting.json_reporter.JsonReporter
    options:
      show_root_heading: true
      show_source: true
      members:
        - to_json
        - write_report

### JSON Schema

```json
{
    "summary": {
        "total": 160,
        "zapped": 142,
        "survived": 18,
        "timeout": 0,
        "error": 0,
        "percentage": 88.75
    },
    "files": {
        "src/auth.py": {
            "total": 50,
            "zapped": 45,
            "survived": 5,
            "percentage": 90.0
        },
        "src/utils.py": {
            "total": 30,
            "zapped": 25,
            "survived": 5,
            "percentage": 83.3
        }
    },
    "results": [
        {
            "gremlin_id": "g001",
            "file_path": "src/auth.py",
            "line_number": 42,
            "status": "zapped",
            "operator": "comparison",
            "description": ">= to >",
            "killing_test": "test_age_boundary"
        },
        {
            "gremlin_id": "g002",
            "file_path": "src/auth.py",
            "line_number": 42,
            "status": "survived",
            "operator": "comparison",
            "description": ">= to <"
        }
    ]
}
```

### JsonReporter Example

```python
from pathlib import Path
from pytest_gremlins.reporting import JsonReporter, MutationScore

reporter = JsonReporter()
score = MutationScore.from_results(results)

# Write to file
reporter.write_report(score, Path('mutation_report.json'))

# Or get JSON string
json_str = reporter.to_json(score)
data = json.loads(json_str)

# CI integration example
if data['summary']['percentage'] < 80:
    print('FAIL: Mutation score below 80%')
    exit(1)
```

---

## CLI Integration

Choose report format via command line:

```bash
# Console output (default)
pytest --gremlins

# HTML report
pytest --gremlins --gremlin-report=html

# JSON report
pytest --gremlins --gremlin-report=json

# All formats
pytest --gremlins --gremlin-report=console,html,json
```

### Output Locations

| Format | Default Location |
|--------|------------------|
| Console | stdout |
| HTML | `mutation_report.html` |
| JSON | `mutation_report.json` |

---

## Interpreting Results

### Good Score (>80%)

Your tests effectively catch most mutations. Focus on:

- Reviewing surviving gremlins
- Adding tests for uncovered edge cases
- Monitoring for regression

### Moderate Score (50-80%)

Tests catch many mutations but gaps exist. Actions:

- Review `top_survivors()` for patterns
- Check boundary conditions
- Add negative test cases
- Verify return value assertions

### Low Score (<50%)

Significant test gaps. Consider:

- Are tests actually running?
- Do assertions check the right things?
- Is code coverage actually high?
- Focus on the "survived" gremlins

### Common Survivor Patterns

| Pattern | Likely Cause | Fix |
|---------|--------------|-----|
| Boundary mutations | Missing edge case tests | Add tests for `n-1`, `n+1` |
| Return value mutations | Not asserting return values | Add explicit assertions |
| Boolean mutations | Not testing both branches | Add inverse condition test |
| Arithmetic mutations | Not verifying calculations | Add calculation validation |
