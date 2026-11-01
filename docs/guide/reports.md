# Reports

pytest-gremlins generates reports in multiple formats to help you understand mutation testing
results and take action on surviving gremlins.

## Report Formats Overview

| Format | Use Case | Output |
|--------|----------|--------|
| `console` | Quick feedback, local development | Terminal output |
| `html` | Detailed analysis, code review | `coverage/gremlins/index.html` |
| `json` | CI integration, custom tooling | `coverage/gremlins/gremlins.json` |

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

The layout below is the plugin's; the counts and paths are illustrative. File paths are printed
as the plugin resolved them, which is usually absolute. Up to ten survivors are listed.

```text
======================= pytest-gremlins mutation report ========================

Zapped: 142 gremlins (85%)
Survived: 18 gremlins (11%)
Timeout: 5 gremlins (3%)
Error: 2 gremlins (1%)

Top surviving gremlins:
  /home/you/project/src/auth.py:42 > to >=              (comparison)
  /home/you/project/src/utils.py:17 + to -               (arithmetic)
  /home/you/project/src/api.py:88 return value to None (return)

Run with --gremlin-report=html for detailed report.
=======================================  =======================================
```

Timeout, Error, and Pardoned lines only appear when their count is greater than zero. The
`Run with --gremlin-report=html` hint is left out when `html` is one of the report formats.

The percentages on these lines are shares of all gremlins (`zapped / total` for the Zapped
line). They are not the mutation score, which counts timeouts as kills and leaves pardoned
gremlins out: `(zapped + timeout) / (total - pardoned)`. In this example the mutation score is
(142 + 5) / 167 = 88%, not 85%. The JSON report's `summary.percentage` holds the mutation
score; see [Understanding Mutation Score](#understanding-mutation-score).

### Console Output Sections

**Summary Section:**

| Field | Description |
|-------|-------------|
| Zapped | Number of gremlins caught by tests, and their share of all gremlins (not the mutation score) |
| Survived | Number and percentage of gremlins that escaped tests |
| Timeout | Number and percentage of gremlins that caused test timeouts and whose tests finish in time without the mutant (shown when > 0); these count as kills |
| Error | Number and percentage of gremlins that caused errors, including timeouts whose unmutated tests do not finish within half the timeout (shown when > 0) |
| Warning | One line giving how many timeouts were counted as errors because the unmutated tests did not finish within half the timeout, and what to do about it (shown when > 0) |
| Pardoned | Number of gremlins pardoned via inline pragma, excluded from score (shown when > 0) |

**Top Surviving Gremlins:**

Shows the most important surviving gremlins to fix. Each line contains:

- **Location** - File path and line number
- **Mutation** - What changed (e.g., `> to >=`)
- **Operator** - Which operator created this gremlin, in parentheses

**Errored Gremlins:**

The terminal summary counts errored gremlins on the `Error` line but doesn't list them. To see
why each one errored, use the HTML report's "Errored Gremlins" table or the `error_output`
field in the JSON report.

The Python API's `ConsoleReporter` (`pytest_gremlins.reporting.console`) adds a
`Top errored gremlins:` section that the terminal summary doesn't have. It lists up to ten
errored gremlins, each with its location and the last line of its error output (up to 120
characters).

**Cache Statistics (when caching enabled):**

```text
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

```text
coverage/gremlins/index.html
```

The location is shown in the console output:

```text
HTML report written to: /path/to/project/coverage/gremlins/index.html
```

### Report Contents

The HTML report includes:

**Summary Dashboard:**

- Total gremlins tested
- Zapped count (with percentage)
- Survived count (with percentage)
- Timeout count (with percentage)
- Error count (with percentage)
- Overall mutation score

**Results Table:**

| Column | Description |
|--------|-------------|
| File | Source file path |
| Line | Line number in source |
| Operator | Operator that created the gremlin |
| Description | Human-readable mutation description |
| Status | `zapped`, `survived`, `timeout`, or `error` |
| Selected test | The test that killed the gremlin, or every test the coverage-based selector ran, or `—` if none |

**Pardoned Gremlins Table:**

Shown only when at least one gremlin is pardoned. It lists each pardoned gremlin's file, line,
operator, description and the reason given in its pragma.

**Errored Gremlins Table:**

Shown only when an errored gremlin has error output. It lists each one's file, line and
operator, with its captured stderr in a collapsed "Show stderr" block.

**Skipped Files:**

Shown only when a source file could not be instrumented, under "Files skipped and not mutation
tested", with the reason for each file.

**Runs with no gremlins:**

A run that finds no gremlins still writes the requested HTML and JSON reports, with a total of 0. This covers
every target being skipped, nothing found in the searched paths, and no source paths being discovered.
A stale report from an earlier run is replaced, never left behind to look current.

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
                    <th>Selected test</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>src/auth.py</td>
                    <td>42</td>
                    <td>comparison</td>
                    <td>>= to ></td>
                    <td class="status-survived">survived</td>
                    <td>tests/test_auth.py::test_login_validates_age</td>
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
open coverage/gremlins/index.html

# Linux
xdg-open coverage/gremlins/index.html

# Windows
start coverage/gremlins/index.html
```

### Trend Chart

When you run mutation testing more than once with `--gremlin-report=html`, the HTML report
includes a line chart showing your mutation score over time. The chart renders after two or
more runs.

Behind the scenes, `append_history_entry` writes a timestamped score record to a history
file alongside the HTML report each time you generate one. On the next run, `load_history`
reads previous entries and passes them to the chart renderer. If the history file is missing
or corrupted, the report still generates -- you just won't see the chart until the next run
rebuilds the file.

This is useful for tracking whether your mutation score is trending up or down as your
project evolves, without needing an external dashboard.

A run that tested no gremlins, because there were none to test (every target skipped, nothing found, or
no paths discovered) or every gremlin was pardoned, adds no history entry, so it cannot plot a 0% point.
The trend chart still draws from the existing entries.

!!! note "Known limitation"
    History entries record only the score, not skipped files. A run that skipped a file can
    plot a higher score than it would have with that file included, so check the skipped
    files list above the charts before reading a rise in the trend as an improvement.

### Accessibility

The HTML report meets WCAG 2.1 AA standards:

- **Contrast ratios** pass for all status colors against both light and dark backgrounds
- **Keyboard navigation** works for expanding file sections and navigating the results table
- **Expand-all** handles overflow gracefully so the page remains usable with many files

### When to Use HTML Report

- Detailed analysis of mutation testing results
- Code review discussions
- Sharing results with team members
- Tracking mutation score trends across runs

## JSON Report

The JSON report provides machine-readable output for CI/CD integration and custom tooling.

### Enabling JSON Report

```bash
pytest --gremlins --gremlin-report=json
```

### Output Location

The JSON report is written to:

```text
coverage/gremlins/gremlins.json
```

The directory is created automatically if it does not exist.

### JSON Schema

```json
{
  "summary": {
    "total": 160,
    "zapped": 142,
    "survived": 18,
    "timeout": 0,
    "error": 0,
    "pardoned": 0,
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
      "gremlin_id": "auth_1a2b_g001",
      "file_path": "src/auth.py",
      "line_number": 42,
      "status": "survived",
      "operator": "comparison",
      "description": ">= to >",
      "selected_tests": ["tests/test_auth.py::test_login_validates_age"]
    },
    {
      "gremlin_id": "utils_3c4d_g002",
      "file_path": "src/utils.py",
      "line_number": 17,
      "status": "zapped",
      "operator": "arithmetic",
      "description": "+ to -",
      "killing_test": "unknown",
      "selected_tests": ["tests/test_utils.py::test_calculate"]
    }
  ],
  "skipped_files": {
    "src/broken.py": "RecursionError: maximum recursion depth exceeded"
  }
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
| `pardoned` | integer | Number of gremlins pardoned via inline pragma |
| `percentage` | float | Mutation score percentage (0-100) |

**Timeout Warning Object (`timeout_warning`):**

Present at the top level only when one or more timeouts were downgraded to `error` because the
unmutated tests did not finish within half the timeout.

| Field | Type | Description |
|-------|------|-------------|
| `downgraded` | integer | Number of timeouts counted as errors instead of kills |
| `mutant_timeout` | integer | The effective per-gremlin timeout in seconds, scaled up by the rerun budget when pytest-rerunfailures is active |
| `message` | string | The explanation, including what to do about it (the option to raise the timeout, unless it is at the 86400-second cap) |

**Files Object:**

A mapping of file paths to per-file statistics:

| Field | Type | Description |
|-------|------|-------------|
| `total` | integer | Total gremlins in this file |
| `zapped` | integer | Gremlins caught in this file |
| `survived` | integer | Gremlins that escaped in this file |
| `percentage` | float | Mutation score for this file (0-100) |

**Skipped Files Object (`skipped_files`):**

Present only when a source file could not be instrumented. It maps each skipped path to the
reason in the form `ExceptionType: message`; these files are not counted in `summary` or `files`.
The HTML report also lists them above the charts, so a high mutation score is not mistaken
for full source coverage. When every target was skipped, `summary.total` is 0 and `skipped_files` lists them all.
When the JSON report is requested, a run with no gremlins at all writes it with `summary.total` of 0 and no
`skipped_files`.

**Results Array (Gremlin Objects):**

| Field | Type | Description |
|-------|------|-------------|
| `gremlin_id` | string | Unique identifier for this gremlin |
| `file_path` | string | Source file path |
| `line_number` | integer | Line number in source |
| `status` | string | One of: `zapped`, `survived`, `timeout`, `error`, `pardoned` |
| `operator` | string | Operator that created this gremlin |
| `description` | string | Human-readable mutation description |
| `killing_test` | string | Present when a killing test was recorded (normally on zapped gremlins). The test that caught the mutation when it is known; `unknown` when the gremlin run failed without naming a test. `<collection>` means the mutant stopped the suite from loading, so no test ran. If the unmutated suite cannot load in the gremlin subprocess, such load failures are reported with status `error` instead |
| `error_output` | string | Present only when the run produced error output, usually for status `error`: the captured stderr or error message, such as a timeout that was downgraded or a crash outside a test |
| `execution_time_ms` | float | Wall-clock milliseconds for this gremlin's test run, including any pytest-rerunfailures attempts inside it. Sequential, `--gremlin-parallel` and `--gremlin-batch` runs all record it. A verdict reused from the incremental cache carries the time stored with it. Absent when no time is known: a pardoned gremlin, a gremlin that errored before its run started, or a cached verdict stored without a time |
| `selected_tests` | list[string] | Present only when tests were selected: the pytest node ids run against this gremlin |

### Processing JSON Reports

**Using jq to extract information:**

```bash
# Get mutation score
jq '.summary.percentage' coverage/gremlins/gremlins.json

# List surviving gremlins
jq '.results[] | select(.status == "survived") | "\(.file_path):\(.line_number) - \(.description)"' coverage/gremlins/gremlins.json

# Count gremlins by operator
jq '.results | group_by(.operator) | map({operator: .[0].operator, count: length})' coverage/gremlins/gremlins.json

# Get per-file breakdown
jq '.files | to_entries[] | "\(.key): \(.value.percentage)%"' coverage/gremlins/gremlins.json
```

**Python script example:**

```python
import json

with open('coverage/gremlins/gremlins.json') as f:
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

Generate multiple formats in a single run using either syntax:

**Comma-separated (v1.5.1+):**

```bash
pytest --gremlins --gremlin-report=json,html
```

**Repeated flags:**

```bash
pytest --gremlins --gremlin-report=json --gremlin-report=html
```

**pyproject.toml:**

```toml
[tool.pytest-gremlins]
# List syntax
report = ["json", "html"]

# Or comma-separated string
# report = "json,html"
```

Console output always renders regardless of which formats you specify -- you do not need
to include `console` in the list.

Duplicate formats are deduplicated automatically, and trailing commas are ignored.

## Interpreting Results

### Understanding Mutation Score

The mutation score is calculated as:

```text
score = (zapped + timeout) / (total - pardoned) * 100
```

Pardoned gremlins are excluded from the denominator because they represent accepted
exceptions (equivalent mutants, untestable paths, or out-of-scope code). This means
pardoning a gremlin does not artificially inflate your score -- it removes the gremlin
from the scoring pool entirely.

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

```text
src/validation.py:12   >= to >   (comparison)
src/validation.py:15   <= to <   (comparison)
src/validation.py:23   >= to >   (comparison)
```

Action: Add boundary value tests for validation functions.

**Pattern: Many return survivors**

```text
src/service.py:45   return value to None   (return)
src/service.py:67   return value to None   (return)
```

Action: Tests are not asserting on return values.

**Pattern: Boolean logic survivors**

```text
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

      - name: Install uv
        uses: astral-sh/setup-uv@v10

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync

      - name: Run mutation testing
        run: |
          uv run pytest --gremlins --gremlin-report=json

      - name: Check mutation score
        run: |
          SCORE=$(jq '.summary.percentage' coverage/gremlins/gremlins.json)
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
          path: coverage/gremlins/
```

### GitLab CI with Artifacts

```yaml
mutation_testing:
  stage: test
  script:
    - pip install uv && uv sync
    - uv run pytest --gremlins --gremlin-report=console,html,json
    - |
      SCORE=$(jq '.summary.percentage' coverage/gremlins/gremlins.json)
      echo "Mutation score: $SCORE%"
      if (( $(echo "$SCORE < 80" | bc -l) )); then
        echo "Mutation score below threshold"
        exit 1
      fi
  artifacts:
    when: always
    paths:
      - coverage/gremlins/
```

`gremlins.json` is not a JUnit XML file, so don't list it under `artifacts:reports:junit`.

### Jenkins Pipeline

```groovy
pipeline {
    agent any

    stages {
        stage('Mutation Testing') {
            steps {
                sh 'pip install uv && uv sync'
                sh 'uv run pytest --gremlins --gremlin-report=json,html'

                script {
                    def report = readJSON file: 'coverage/gremlins/gremlins.json'
                    def score = report.summary.percentage

                    echo "Mutation Score: ${score}%"

                    if (score < 80) {
                        error "Mutation score ${score}% is below threshold 80%"
                    }
                }
            }
            post {
                always {
                    archiveArtifacts artifacts: 'coverage/gremlins/**'
                    publishHTML([
                        allowMissing: false,
                        alwaysLinkToLastBuild: true,
                        keepAll: true,
                        reportDir: 'coverage/gremlins',
                        reportFiles: 'index.html',
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

## Exporting to External Services

pytest-gremlins can export mutation testing results to external code quality platforms.

### Stryker Dashboard Export

The [Stryker Dashboard](https://dashboard.stryker-mutator.io/) is a free service for hosting
mutation testing reports. pytest-gremlins exports results in the standardized
[mutation-testing-report-schema](https://github.com/stryker-mutator/mutation-testing-elements)
format.

#### Using StrykerExporter

```python
from pytest_gremlins.reporting import MutationScore, StrykerExporter
from pathlib import Path

# After running mutation testing, get your score
score: MutationScore = ...  # from test execution

# Create exporter
exporter = StrykerExporter()

# Write full report (for detailed dashboard display)
exporter.write_report(score, Path('mutation.json'))

# Or generate simple score-only format (for badge display)
simple_json = exporter.to_score_only_json(score)
Path('mutation-score.json').write_text(simple_json)
```

**Schema validity.** The full report validates against the official
[mutation-testing-report-schema](https://github.com/stryker-mutator/mutation-testing-elements/tree/master/packages/report-schema).

- **Source:** each file entry carries its original `source`, read from disk when the report is
  built. The file is decoded the way pytest-gremlins decodes it for instrumentation: a UTF-8
  byte-order mark is dropped and a PEP 263 `coding:` declaration is honored. Line endings are
  normalized to `\n`.
- **Positions:** mutant `location` positions are 1-based for both line and column, with a required
  `end`. The Python AST's 0-based UTF-8 byte columns are converted to UTF-16 code unit columns and
  shifted by one, matching the string indices of the report viewer, so a character outside the Basic
  Multilingual Plane (such as an emoji) counts as two columns. A node without end information gets an
  `end` equal to its `start`.
- **Unreadable files:** a file that cannot be read exports an empty `source`, which the schema
  accepts. Its mutant columns are then the AST's byte columns plus one, because there is no text to
  convert them against.

!!! warning "Reports embed your source code"
    Each file entry in a Stryker report contains the full text of the mutated file. Uploading the
    report to the Stryker Dashboard, or sharing the JSON (for example as a CI artifact), shares that
    source code. Do not publish it for private or proprietary repositories unless you intend to.

#### Uploading to Stryker Dashboard

1. **Enable repository on dashboard.stryker-mutator.io**
2. **Get your API key** from the dashboard settings
3. **Upload report** via HTTP PUT:

```bash
curl -X PUT \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $STRYKER_DASHBOARD_API_KEY" \
  --data-binary @mutation.json \
  "https://dashboard.stryker-mutator.io/api/reports/github.com/$OWNER/$REPO/$BRANCH"
```

#### GitHub Actions for Stryker Dashboard

```yaml
name: Mutation Testing

on: [push, pull_request]

jobs:
  mutation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v10

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync

      - name: Run mutation testing
        run: uv run pytest --gremlins --gremlin-report=json

      # pytest-gremlins has no flag or command that writes the Stryker format. Call
      # StrykerExporter.write_report(score, Path('mutation.json')) from your own code
      # (see "Using StrykerExporter" above) and make sure mutation.json exists before the upload.

      - name: Upload to Stryker Dashboard
        if: github.ref == 'refs/heads/main'
        run: |
          curl -X PUT \
            -H "Content-Type: application/json" \
            -H "X-Api-Key: ${{ secrets.STRYKER_DASHBOARD_API_KEY }}" \
            --data-binary @mutation.json \
            "https://dashboard.stryker-mutator.io/api/reports/github.com/${{ github.repository }}/${{ github.ref_name }}"
```

#### Mutation Score Badge

After uploading to Stryker Dashboard, add this badge to your README:

```markdown
[![Mutation Score](https://img.shields.io/endpoint?style=flat&url=https%3A%2F%2Fbadge-api.stryker-mutator.io%2Fgithub.com%2FOWNER%2FREPO%2Fmain)](https://dashboard.stryker-mutator.io/reports/github.com/OWNER/REPO/main)
```

### SonarQube Export

SonarQube can import surviving mutants and errored gremlins as [external issues](https://docs.sonarsource.com/sonarqube/latest/analyzing-source-code/importing-external-issues/generic-issue-import-format/).

#### Using SonarQubeExporter

```python
from pytest_gremlins.reporting import MutationScore, SonarQubeExporter
from pathlib import Path

# After running mutation testing
score: MutationScore = ...

# Create exporter (optionally specify project root for path normalization)
exporter = SonarQubeExporter(
    project_root='/path/to/project',  # paths will be relative to this
    severity='MAJOR',  # BLOCKER, CRITICAL, MAJOR, MINOR, INFO
    effort_minutes=10,  # estimated time to fix each issue
)

# Write report
exporter.write_report(score, Path('mutation-sonar.json'))
```

#### SonarQube Import

Add the report path to your SonarQube analysis:

```bash
sonar-scanner \
  -Dsonar.externalIssuesReportPaths=mutation-sonar.json \
  -Dsonar.projectKey=my-project
```

#### What Gets Imported

**Survived** mutants are always imported as issues. **Errored** gremlins are also
imported, but only when they captured diagnostic output (`error_output`), so you
can see why a gremlin failed to run rather than whether it survived:

| Field | Survived | Errored |
|-------|----------|---------|
| Engine ID | `pytest-gremlins` | `pytest-gremlins` |
| Rule ID | `mutant-survived-{operator}` | `mutant-error-{operator}` |
| Severity | `MAJOR` (configurable) | `MAJOR` (configurable) |
| Type | `CODE_SMELL` | `CODE_SMELL` |
| Effort | `10 minutes` (configurable) | `10 minutes` (configurable) |
| Message | `Mutant survived: {description}` | `Mutant errored: {error_output}` (truncated to 500 chars) |

#### GitHub Actions for SonarQube

```yaml
name: Mutation Testing + SonarQube

on: [push, pull_request]

jobs:
  mutation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # SonarQube needs full history

      - name: Install uv
        uses: astral-sh/setup-uv@v10

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync

      - name: Run mutation testing
        run: uv run pytest --gremlins --gremlin-report=json

      # pytest-gremlins has no flag or command that writes the SonarQube format. Call
      # SonarQubeExporter.write_report(score, Path('mutation-sonar.json')) from your own code
      # (see "Using SonarQubeExporter" above) and make sure mutation-sonar.json exists before the scan.

      - name: SonarQube Scan
        uses: sonarsource/sonarqube-scan-action@master
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
          SONAR_HOST_URL: ${{ secrets.SONAR_HOST_URL }}
        with:
          args: >
            -Dsonar.externalIssuesReportPaths=mutation-sonar.json

      - name: SonarQube Quality Gate
        uses: sonarsource/sonarqube-quality-gate-action@master
        timeout-minutes: 5
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

### Export Format Reference

#### Stryker Dashboard Format (mutation-testing-report-schema)

<!-- stryker-report-example -->
```json
{
  "schemaVersion": "1.0",
  "thresholds": {
    "high": 80,
    "low": 60
  },
  "files": {
    "src/auth.py": {
      "language": "python",
      "source": "if age >= 18:\n    grant()\n",
      "mutants": [
        {
          "id": "g001",
          "mutatorName": "comparison",
          "location": {
            "start": {"line": 1, "column": 4},
            "end": {"line": 1, "column": 13}
          },
          "status": "Killed",
          "killedBy": ["test_auth.py::test_login"],
          "description": ">= to >",
          "duration": 45
        }
      ]
    }
  },
  "framework": {
    "name": "pytest-gremlins",
    "version": "1.0.0"
  },
  "config": {
    "pytestGremlins": {
      "mutationScore": 75.0,
      "counts": {
        "total": 5, "zapped": 3, "survived": 1, "timeout": 0, "error": 0, "pardoned": 1
      },
      "note": "pytest-gremlins mutation score: ..."
    }
  }
}
```

A mutant's **`duration`** is the gremlin's `execution_time_ms` truncated to whole milliseconds. It is absent when
`execution_time_ms` is (see the JSON field table above). Sequential, parallel and batch runs all set it.

**`config.pytestGremlins`** holds pytest-gremlins' own score (`mutationScore`, identical to
`MutationScore.percentage`) and the counts behind it. The schema defines `config` as a free-form
object, so this addition is schema-valid.

**Why the dashboard score can be higher than ours.** pytest-gremlins reports `ERROR` gremlins as
Stryker `RuntimeError`. Stryker treats `RuntimeError` and `CompileError` as invalid and removes them
from the score denominator. pytest-gremlins keeps `ERROR` in its denominator, so an error is not
silently excused:

```text
pytest-gremlins score: (zapped + timeout) / (total - pardoned)
Stryker score:         (killed + timeout) / (total - pardoned - errors)
```

The two numbers agree when the run has no `ERROR` gremlins and at least one gremlin counts
toward the score. When nothing counts (no gremlins at all, every gremlin pardoned, or every
remaining gremlin an `ERROR`), Stryker's formula has no score; pytest-gremlins reports 0.0 in
those cases. When `ERROR` gremlins exist alongside countable ones, a score recomputed by a Stryker
dashboard from the mutant statuses is higher than `mutationScore` (or equal, when nothing was detected:
with no zapped or timed-out gremlins both scores are 0.0). Treat
`config.pytestGremlins.mutationScore` as the authoritative number, and look into the `ERROR`
count when the two differ. Pardoned gremlins are exported as `Ignored`, which Stryker also leaves
out of its score.

**Status values:**

- `Killed` - Test caught the mutation (gremlin zapped)
- `Survived` - Mutation not detected (gremlin survived)
- `Timeout` - Test timed out
- `RuntimeError` - Mutation caused an error
- `Ignored` - Gremlin was pardoned (excluded from both scores)

#### SonarQube Generic Issue Format

```json
{
  "issues": [
    {
      "engineId": "pytest-gremlins",
      "ruleId": "mutant-survived-comparison",
      "severity": "MAJOR",
      "type": "CODE_SMELL",
      "effortMinutes": 10,
      "primaryLocation": {
        "filePath": "src/auth.py",
        "textRange": {
          "startLine": 42
        },
        "message": "Mutant survived: >= to >"
      }
    }
  ]
}
```

### Combining Multiple Exports

Generate multiple formats in your CI workflow:

```yaml
- name: Run mutation testing with all exports
  run: |
    pytest --gremlins --gremlin-report=json,html

    # pytest-gremlins ships no command that writes the Stryker or SonarQube format.
    # Your own code calls StrykerExporter and SonarQubeExporter (see above) and
    # writes mutation.json and mutation-sonar.json before the steps below run.

- name: Upload to Stryker Dashboard
  run: curl -X PUT ... @mutation.json

- name: SonarQube Scan
  run: sonar-scanner -Dsonar.externalIssuesReportPaths=mutation-sonar.json
