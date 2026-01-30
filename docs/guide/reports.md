# Reports

pytest-gremlins generates reports in multiple formats to help you understand mutation testing results and take action on surviving gremlins.

## Report Formats Overview

| Format | Use Case | Output |
|--------|----------|--------|
| `console` | Quick feedback, local development | Terminal output |
| `html` | Detailed analysis, code review | `gremlin-report.html` |
| `json` | CI integration, custom tooling | `gremlin-report.json` |

## Console Report (Default)

The console report provides a quick summary directly in your terminal.

### Enabling Console Report

Console is the default format:

```bash
pytest --gremlins
```

Or explicitly:

```bash
pytest --gremlins --gremlin-report=console
```

### Example Output

```text
================== pytest-gremlins mutation report ==================

Zapped: 142 gremlins (89%)
Survived: 18 gremlins (11%)

Top surviving gremlins:
  src/auth.py:42    >= to >     (boundary not tested)
  src/utils.py:17   + to -      (arithmetic not verified)
  src/api.py:88     True to False (return value unchecked)

Run with --gremlin-report=html for detailed report.
=====================================================================
```

### Console Output Sections

**Summary Section:**

| Field | Description |
|-------|-------------|
| Zapped | Number and percentage of gremlins caught by tests |
| Survived | Number and percentage of gremlins that escaped tests |

**Top Surviving Gremlins:**

Shows the most important surviving gremlins to fix. Each line contains:

- **Location** - File path and line number
- **Mutation** - What changed (e.g., `>= -> >`)
- **Operator** - Which operator created this gremlin

**Cache Statistics (when caching enabled):**

```
Cache: 85 hits, 15 misses (85% hit rate)
```

### When to Use Console Report

- During local development for quick feedback
- In CI logs for basic pass/fail information
- When you need immediate visibility without file output

## HTML Report

The HTML report provides a detailed, visual representation of mutation testing results.

### Enabling HTML Report

```bash
pytest --gremlins --gremlin-report=html
```

### Output Location

By default, the HTML report is written to:

```
gremlin-report.html
```

The location is shown in the console output:

```
HTML report written to: /path/to/project/gremlin-report.html
```

### Report Contents

The HTML report includes:

**Summary Dashboard:**

- Total gremlins tested
- Zapped count (with percentage)
- Survived count (with percentage)
- Overall mutation score

**Results Table:**

| Column | Description |
|--------|-------------|
| File | Source file path |
| Line | Line number in source |
| Operator | Operator that created the gremlin |
| Description | Human-readable mutation description |
| Status | `zapped`, `survived`, `timeout`, or `error` |

**Status Color Coding:**

| Status | Color | Meaning |
|--------|-------|---------|
| zapped | Green | Test caught the mutation |
| survived | Red | Test missed the mutation |
| timeout | Orange | Mutation caused test timeout |
| error | Purple | Mutation caused an error |

### Example HTML Report Structure

```html
<!DOCTYPE html>
<html>
<head>
    <title>pytest-gremlins Mutation Report</title>
    <!-- Embedded CSS for standalone viewing -->
</head>
<body>
    <div class="container">
        <h1>pytest-gremlins Mutation Report</h1>

        <!-- Summary cards -->
        <div class="summary">
            <div class="stat-card">
                <div class="stat-value">160</div>
                <div class="stat-label">Total Gremlins</div>
            </div>
            <div class="stat-card stat-zapped">
                <div class="stat-value">142</div>
                <div class="stat-label">Zapped</div>
            </div>
            <div class="stat-card stat-survived">
                <div class="stat-value">18</div>
                <div class="stat-label">Survived</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">89%</div>
                <div class="stat-label">Mutation Score</div>
            </div>
        </div>

        <!-- Results table -->
        <table>
            <thead>
                <tr>
                    <th>File</th>
                    <th>Line</th>
                    <th>Operator</th>
                    <th>Description</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>src/auth.py</td>
                    <td>42</td>
                    <td>comparison</td>
                    <td>>= -> ></td>
                    <td class="status-survived">survived</td>
                </tr>
                <!-- More rows... -->
            </tbody>
        </table>
    </div>
</body>
</html>
```

### Viewing the HTML Report

The HTML report is self-contained with embedded CSS. Open it directly in any web browser:

```bash
# macOS
open gremlin-report.html

# Linux
xdg-open gremlin-report.html

# Windows
start gremlin-report.html
```

### When to Use HTML Report

- Detailed analysis of mutation testing results
- Code review discussions
- Sharing results with team members
- Archiving reports for historical comparison

## JSON Report

The JSON report provides machine-readable output for CI/CD integration and custom tooling.

### Enabling JSON Report

```bash
pytest --gremlins --gremlin-report=json
```

### Output Location

By default, the JSON report is written to:

```
gremlin-report.json
```

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
      "total": 80,
      "zapped": 72,
      "survived": 8,
      "percentage": 90.0
    },
    "src/utils.py": {
      "total": 80,
      "zapped": 70,
      "survived": 10,
      "percentage": 87.5
    }
  },
  "results": [
    {
      "gremlin_id": "g001",
      "file_path": "src/auth.py",
      "line_number": 42,
      "operator": "comparison",
      "description": ">= -> >",
      "status": "survived"
    },
    {
      "gremlin_id": "g002",
      "file_path": "src/utils.py",
      "line_number": 17,
      "operator": "arithmetic",
      "description": "+ -> -",
      "status": "zapped",
      "killing_test": "test_utils.py::test_calculate"
    }
  ]
}
```

### Field Reference

**Summary Object:**

| Field | Type | Description |
|-------|------|-------------|
| `total` | integer | Total number of gremlins tested |
| `zapped` | integer | Number of gremlins caught by tests |
| `survived` | integer | Number of gremlins that escaped |
| `timeout` | integer | Number of gremlins that caused timeouts |
| `error` | integer | Number of gremlins that caused errors |
| `percentage` | float | Mutation score percentage (0-100) |

**Files Object:**

A mapping of file paths to per-file statistics:

| Field | Type | Description |
|-------|------|-------------|
| `total` | integer | Total gremlins in this file |
| `zapped` | integer | Gremlins caught in this file |
| `survived` | integer | Gremlins that escaped in this file |
| `percentage` | float | Mutation score for this file (0-100) |

**Results Array (Gremlin Objects):**

| Field | Type | Description |
|-------|------|-------------|
| `gremlin_id` | string | Unique identifier for this gremlin |
| `file_path` | string | Source file path |
| `line_number` | integer | Line number in source |
| `operator` | string | Operator that created this gremlin |
| `description` | string | Human-readable mutation description |
| `status` | string | One of: `zapped`, `survived`, `timeout`, `error` |
| `killing_test` | string | Test that caught the mutation (only present if zapped) |

### Processing JSON Reports

**Using jq to extract information:**

```bash
# Get mutation score
jq '.summary.percentage' gremlin-report.json

# List surviving gremlins
jq '.results[] | select(.status == "survived") | "\(.file_path):\(.line_number) - \(.description)"' gremlin-report.json

# Count gremlins by operator
jq '.results | group_by(.operator) | map({operator: .[0].operator, count: length})' gremlin-report.json

# Get per-file breakdown
jq '.files | to_entries[] | "\(.key): \(.value.percentage)%"' gremlin-report.json
```

**Python script example:**

```python
import json

with open('gremlin-report.json') as f:
    report = json.load(f)

print(f"Mutation Score: {report['summary']['percentage']:.1f}%")

survivors = [g for g in report['results'] if g['status'] == 'survived']
print(f"\nSurviving gremlins ({len(survivors)}):")
for g in survivors:
    print(f"  {g['file_path']}:{g['line_number']} - {g['description']}")
```

### When to Use JSON Report

- CI/CD pipeline integration
- Custom reporting tools
- Historical trend analysis
- Automated quality gates

## Multiple Report Formats

Generate multiple formats in a single run:

```bash
pytest --gremlins --gremlin-report=console,html,json
```

This produces:

- Console output (terminal)
- `gremlin-report.html`
- `gremlin-report.json`

## Interpreting Results

### Understanding Mutation Score

The mutation score is calculated as:

```
score = (zapped + timeout) / total * 100
```

Timeouts count as "zapped" because the mutation was detected (it caused the test to hang).

**Score Guidelines:**

| Score | Interpretation | Action |
|-------|----------------|--------|
| < 50% | Poor coverage | Focus on adding basic tests |
| 50-70% | Below average | Add tests for surviving gremlins |
| 70-85% | Good | Target specific gaps |
| 85-95% | Very good | Diminishing returns territory |
| > 95% | Excellent | May have equivalent mutants |

### Prioritizing Survivors

Not all surviving gremlins are equally important. Prioritize by:

1. **Security-critical code** - Authentication, authorization, validation
2. **Business-critical code** - Payments, data integrity
3. **Operator type** - `boolean` and `comparison` often catch real bugs
4. **Code complexity** - More complex functions need better coverage

### Analyzing Patterns

Look for patterns in surviving gremlins:

**Pattern: Many boundary survivors**

```
src/validation.py:12   >= -> >   (comparison)
src/validation.py:15   <= -> <   (comparison)
src/validation.py:23   >= -> >   (comparison)
```

Action: Add boundary value tests for validation functions.

**Pattern: Many return survivors**

```
src/service.py:45   return x -> return None   (return)
src/service.py:67   return x -> return None   (return)
```

Action: Tests are not asserting on return values.

**Pattern: Boolean logic survivors**

```
src/auth.py:30   and -> or   (boolean)
```

Action: Test all condition combinations in authorization.

## CI Integration Examples

### GitHub Actions with Score Threshold

```yaml
name: Mutation Testing

on: [push, pull_request]

jobs:
  mutation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run mutation testing
        run: |
          pytest --gremlins --gremlin-report=json

      - name: Check mutation score
        run: |
          SCORE=$(jq '.summary.percentage' gremlin-report.json)
          echo "Mutation score: $SCORE%"
          if (( $(echo "$SCORE < 80" | bc -l) )); then
            echo "::error::Mutation score $SCORE% is below threshold 80%"
            exit 1
          fi

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: mutation-report
          path: |
            gremlin-report.html
            gremlin-report.json
```

### GitLab CI with Artifacts

```yaml
mutation_testing:
  stage: test
  script:
    - pip install -e ".[dev]"
    - pytest --gremlins --gremlin-report=console,html,json
    - |
      SCORE=$(jq '.summary.percentage' gremlin-report.json)
      echo "Mutation score: $SCORE%"
      if (( $(echo "$SCORE < 80" | bc -l) )); then
        echo "Mutation score below threshold"
        exit 1
      fi
  artifacts:
    when: always
    paths:
      - gremlin-report.html
      - gremlin-report.json
    reports:
      junit: gremlin-report.json
```

### Jenkins Pipeline

```groovy
pipeline {
    agent any

    stages {
        stage('Mutation Testing') {
            steps {
                sh 'pip install -e ".[dev]"'
                sh 'pytest --gremlins --gremlin-report=json,html'

                script {
                    def report = readJSON file: 'gremlin-report.json'
                    def score = report.summary.percentage

                    echo "Mutation Score: ${score}%"

                    if (score < 80) {
                        error "Mutation score ${score}% is below threshold 80%"
                    }
                }
            }
            post {
                always {
                    archiveArtifacts artifacts: 'gremlin-report.*'
                    publishHTML([
                        allowMissing: false,
                        alwaysLinkToLastBuild: true,
                        keepAll: true,
                        reportDir: '.',
                        reportFiles: 'gremlin-report.html',
                        reportName: 'Mutation Testing Report'
                    ])
                }
            }
        }
    }
}
```

## Troubleshooting Reports

### No Report Generated

If no report is generated:

1. Ensure `--gremlins` flag is present
2. Check that source files were found
3. Verify tests exist and pass normally

### Empty Report

If the report shows zero gremlins:

1. Check `--gremlin-targets` points to source files
2. Verify files contain mutable code
3. Check exclude patterns are not too broad

### HTML Report Not Rendering

If HTML report looks broken:

1. Open in a modern browser
2. Check file is not truncated
3. Ensure no special characters in file paths

### JSON Parse Errors

If JSON report fails to parse:

1. Check for incomplete writes (disk full)
2. Verify encoding (should be UTF-8)
3. Look for control characters in source paths
