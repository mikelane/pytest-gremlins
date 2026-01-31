# Configuration

pytest-gremlins can be configured via command-line options or `pyproject.toml`. This page documents all configuration options with examples.

## Configuration Precedence

Configuration values are resolved in this order (highest priority first):

1. **Command-line options** - Flags passed to pytest
2. **pyproject.toml** - `[tool.pytest-gremlins]` section
3. **Built-in defaults** - Sensible defaults for all options

When the same option is specified at multiple levels, the higher-priority value wins.

## Command-Line Options Reference

All command-line options are prefixed with `--gremlin` or `--gremlins`.

### Core Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--gremlins` | flag | `false` | Enable mutation testing |
| `--gremlin-operators` | string | all | Comma-separated list of operators to use |
| `--gremlin-targets` | string | `src/` | Comma-separated list of files/directories to mutate |
| `--gremlin-report` | string | `console` | Report format: `console`, `html`, or `json` |

### Performance Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--gremlin-cache` | flag | `false` | Enable incremental analysis cache |
| `--gremlin-clear-cache` | flag | `false` | Clear cache before running |
| `--gremlin-parallel` | flag | `false` | Enable parallel gremlin execution |
| `--gremlin-workers` | integer | CPU count | Number of parallel workers |
| `--gremlin-batch` | flag | `false` | Enable batch execution mode |
| `--gremlin-batch-size` | integer | `10` | Number of gremlins per batch |

### Usage Examples

**Basic mutation testing:**

```bash
pytest --gremlins
```

**Target specific files:**

```bash
pytest --gremlins --gremlin-targets=src/auth.py,src/api.py
```

**Target a directory:**

```bash
pytest --gremlins --gremlin-targets=src/mypackage
```

**Use specific operators only:**

```bash
pytest --gremlins --gremlin-operators=comparison,boolean
```

**Generate HTML report:**

```bash
pytest --gremlins --gremlin-report=html
```

**Enable incremental caching:**

```bash
pytest --gremlins --gremlin-cache
```

**Clear cache and run fresh:**

```bash
pytest --gremlins --gremlin-cache --gremlin-clear-cache
```

**Enable parallel execution:**

```bash
pytest --gremlins --gremlin-parallel
```

**Parallel with specific worker count:**

```bash
pytest --gremlins --gremlin-parallel --gremlin-workers=4
```

**Enable batch mode for reduced overhead:**

```bash
pytest --gremlins --gremlin-batch --gremlin-batch-size=20
```

**Combine multiple options:**

```bash
pytest --gremlins \
    --gremlin-targets=src/core \
    --gremlin-operators=comparison,boundary \
    --gremlin-cache \
    --gremlin-parallel \
    --gremlin-report=html
```

## pyproject.toml Configuration

Configure pytest-gremlins in your `pyproject.toml` file under the `[tool.pytest-gremlins]` section.

### Complete Configuration Reference

```toml
[tool.pytest-gremlins]
# Paths to scan for source files to mutate
# Default: ["src"]
paths = ["src", "lib"]

# Glob patterns for files to exclude from mutation
# Default: []
exclude = [
    "**/migrations/*",
    "**/test_*",
    "**/__pycache__/*",
    "**/conftest.py",
]

# Operators to enable (in order of priority)
# Default: all operators
operators = [
    "comparison",
    "boundary",
    "boolean",
    "arithmetic",
    "return",
]
```

### Configuration Options Table

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `paths` | list[string] | `["src"]` | Directories or files to scan for source code |
| `exclude` | list[string] | `[]` | Glob patterns for files to exclude |
| `operators` | list[string] | all | Operators to enable, in priority order |

### Example Configurations

**Minimal configuration:**

```toml
[tool.pytest-gremlins]
paths = ["src"]
```

**Django project:**

```toml
[tool.pytest-gremlins]
paths = ["myapp"]
exclude = [
    "**/migrations/*",
    "**/admin.py",
    "**/apps.py",
]
operators = ["comparison", "boolean", "return"]
```

**Library with multiple packages:**

```toml
[tool.pytest-gremlins]
paths = ["src/mylib", "src/mylib_extras"]
exclude = [
    "**/_compat.py",
    "**/deprecated/*",
]
```

**Focused on high-value mutations:**

```toml
[tool.pytest-gremlins]
paths = ["src"]
operators = ["comparison", "boundary"]  # Only boundary-related bugs
```

## Excluding Code from Mutation

Use glob patterns in `pyproject.toml` to exclude files from mutation testing:

```toml
[tool.pytest-gremlins]
exclude = [
    "**/migrations/*",      # Django migrations
    "**/test_*",            # Test files
    "**/conftest.py",       # pytest configuration
    "**/__pycache__/*",     # Cache directories
    "**/vendor/*",          # Vendored dependencies
]
```

## Performance Tuning

### Incremental Caching

Enable caching to skip unchanged code on subsequent runs:

```bash
pytest --gremlins --gremlin-cache
```

The cache is stored in `.gremlins_cache/` in your project root. Cache keys include:

- Source file content hash
- Test file content hash
- Gremlin ID

When source or test files change, affected gremlins are re-tested.

**Clear the cache:**

```bash
pytest --gremlins --gremlin-cache --gremlin-clear-cache
```

### Parallel Execution

Enable parallel execution for faster results on multi-core machines:

```bash
pytest --gremlins --gremlin-parallel
```

By default, uses all available CPU cores. Specify worker count:

```bash
pytest --gremlins --gremlin-parallel --gremlin-workers=4
```

### Batch Execution

Batch mode reduces subprocess overhead by testing multiple gremlins per subprocess:

```bash
pytest --gremlins --gremlin-batch --gremlin-batch-size=20
```

Batch size tuning:

| Batch Size | Tradeoff |
|------------|----------|
| Small (5-10) | More subprocess overhead, but faster feedback on failures |
| Medium (20-50) | Balanced for most projects |
| Large (100+) | Less overhead, but slower feedback |

### Combined Performance Options

For maximum speed, combine all performance options:

```bash
pytest --gremlins \
    --gremlin-cache \
    --gremlin-parallel \
    --gremlin-batch \
    --gremlin-batch-size=20 \
    --gremlin-workers=8
```

## CI Integration

### GitHub Actions

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
        run: |
          pip install -e ".[dev]"

      - name: Run mutation testing
        run: |
          pytest --gremlins \
            --gremlin-cache \
            --gremlin-parallel \
            --gremlin-report=json

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        with:
          name: mutation-report
          path: gremlin-report.json
```

### GitLab CI

```yaml
mutation_testing:
  stage: test
  script:
    - pip install -e ".[dev]"
    - pytest --gremlins --gremlin-cache --gremlin-parallel --gremlin-report=json
  artifacts:
    reports:
      junit: gremlin-report.json
    paths:
      - gremlin-report.json
```

### Pre-commit Hook

Add mutation testing as a pre-commit hook (warning: can be slow):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: mutation-testing
        name: Mutation Testing
        entry: pytest --gremlins --gremlin-cache --gremlin-parallel
        language: system
        pass_filenames: false
        stages: [pre-push]  # Run on push, not commit
```

## Troubleshooting Configuration

### Common Issues

**No gremlins found:**

```bash
$ pytest --gremlins
pytest-gremlins: No gremlins found in source code.
```

Solutions:

1. Check `--gremlin-targets` points to actual Python files
2. Verify files are not excluded by `exclude` patterns
3. Ensure source files contain mutable code (not just imports/constants)

**Cache not working:**

If caching does not seem to skip unchanged code:

1. Ensure `--gremlin-cache` flag is present
2. Check `.gremlins_cache/` directory exists
3. Verify source and test files have not changed

**Parallel execution hanging:**

If parallel mode hangs or is very slow:

1. Reduce worker count: `--gremlin-workers=2`
2. Check for test isolation issues
3. Ensure tests do not have external dependencies

### Debug Mode

Enable verbose output to debug configuration issues:

```bash
pytest --gremlins -v
```

This shows:

- Which files are being scanned
- Number of gremlins found per file
- Which operators are active
- Cache hit/miss statistics

## Configuration Validation

pytest-gremlins validates configuration at startup and reports errors:

```text
pytest-gremlins: Invalid configuration
  - Unknown operator 'typo' in operators list
  - Path 'nonexistent/' does not exist
```

Use the `--collect-only` flag to validate configuration without running tests:

```bash
pytest --gremlins --collect-only
```
