# Reports

pytest-gremlins can generate reports in multiple formats to help you understand and act on mutation testing results.

## Console Report (Default)

The default console report shows a summary and top surviving gremlins:

```
================== pytest-gremlins mutation report ==================

Zapped: 142 gremlins (89%)
Survived: 18 gremlins (11%)

Top surviving gremlins:
  src/auth.py:42    >= → >     (boundary not tested)
  src/utils.py:17   + → -      (arithmetic not verified)
  src/api.py:88     True → False (return value unchecked)

Run with --gremlin-report=html for detailed report.
=====================================================================
```

## HTML Report

Generate a detailed HTML report:

```bash
pytest --gremlins --gremlin-report=html
```

The HTML report includes:

- **Summary dashboard** - Overall score, trends, operator breakdown
- **File browser** - Navigate source files with inline mutation annotations
- **Gremlin details** - Each mutation with original/mutated code
- **Test mapping** - Which tests cover each gremlin

Output location: `htmlcov/gremlins/index.html` (configurable)

## JSON Report

Generate machine-readable JSON output:

```bash
pytest --gremlins --gremlin-report=json
```

```json
{
  "summary": {
    "total": 160,
    "zapped": 142,
    "survived": 18,
    "score": 88.75
  },
  "gremlins": [
    {
      "id": "gremlin_001",
      "file": "src/auth.py",
      "line": 42,
      "operator": "comparison",
      "original": ">=",
      "mutated": ">",
      "status": "survived",
      "covering_tests": ["test_auth.py::test_login"]
    }
  ]
}
```

## Multiple Report Formats

Generate multiple formats at once:

```bash
pytest --gremlins --gremlin-report=console,html,json
```

## Report Configuration

```toml
[tool.pytest-gremlins]
# Report format(s)
report = ["console", "html"]

# HTML report output directory
html_report_dir = "htmlcov/gremlins"

# JSON report output file
json_report_file = "gremlin-report.json"

# Show N surviving gremlins in console (0 = all)
console_survivors = 10
```

## CI Integration

For CI, use JSON output for programmatic parsing:

```yaml
- name: Run mutation testing
  run: pytest --gremlins --gremlin-report=json

- name: Check mutation score
  run: |
    SCORE=$(jq '.summary.score' gremlin-report.json)
    if (( $(echo "$SCORE < 80" | bc -l) )); then
      echo "Mutation score $SCORE is below threshold 80"
      exit 1
    fi
```
