# Configuration

pytest-gremlins can be configured via `pyproject.toml` or command-line options.

## pyproject.toml

```toml
[tool.pytest-gremlins]
# Paths to mutate (default: ["src"])
paths = ["src"]

# Patterns to exclude from mutation
exclude = [
    "**/migrations/*",
    "**/test_*",
    "**/__pycache__/*",
]

# Operators to use (default: all)
operators = [
    "comparison",
    "arithmetic",
    "boolean",
    "return",
]

# Minimum mutation score to pass (0-100)
min_score = 80

# Report format: console, html, json
report = "console"

# Number of parallel workers (default: CPU count)
workers = 4

# Enable incremental mode (cache results)
incremental = true
```

## Command-Line Options

```bash
# Enable mutation testing
pytest --gremlins

# Specify operators
pytest --gremlins --gremlin-operators=comparison,boolean

# Set report format
pytest --gremlins --gremlin-report=html

# Set minimum score (fail if below)
pytest --gremlins --gremlin-min-score=80

# Disable incremental mode
pytest --gremlins --no-gremlin-incremental

# Set worker count
pytest --gremlins --gremlin-workers=4
```

## Operator Configuration

Fine-tune individual operators:

```toml
[tool.pytest-gremlins.operators.comparison]
# Skip specific mutations
skip_mutations = ["eq_to_noteq"]

[tool.pytest-gremlins.operators.arithmetic]
# Only use these operations
only_ops = ["add", "sub"]
```

## Excluding Code

### Via Configuration

```toml
[tool.pytest-gremlins]
exclude = ["**/migrations/*"]
```

### Via Inline Comments

```python
def legacy_function():  # pragma: no gremlin
    # This entire function is excluded
    pass

def another_function():
    x = calculate()  # pragma: no gremlin
    return x + 1  # This line is excluded
```

## CI Integration

For CI, set a minimum score and fail the build if not met:

```yaml
# .github/workflows/ci.yml
- name: Run mutation testing
  run: pytest --gremlins --gremlin-min-score=80
```
