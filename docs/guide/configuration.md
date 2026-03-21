# Configuration

pytest-gremlins can be configured via command-line options or `pyproject.toml`. This page
documents all configuration options with examples.

## Configuration Precedence

Configuration values are resolved in this order (highest priority first):

1. **Command-line options** - Flags passed to pytest (e.g., `--gremlin-targets`)
2. **pyproject.toml** - `[tool.pytest-gremlins]` section
3. **Setuptools metadata** - `[tool.setuptools]` package config in `pyproject.toml`
4. **Built-in defaults** - Falls back to `src/` directory

When the same option is specified at multiple levels, the higher-priority value wins. For most
projects with a standard `pyproject.toml`, source paths are auto-discovered and no configuration
is needed.

## Command-Line Options Reference

All command-line options are prefixed with `--gremlin` or `--gremlins`.

### Core Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--gremlins` | flag | `false` | Enable mutation testing |
| `--gremlin-operators` | string | all | Comma-separated list of operators to use |
| `--gremlin-targets` | string | auto-discovered | Comma-separated list of files/directories to mutate (see [precedence](#configuration-precedence)) |
| `--gremlin-exclude` | string | none | Glob pattern to exclude from mutation (repeatable, overrides pyproject.toml) |
| `--gremlin-report` | string | `console` | Report format: `console`, `html`, or `json` |

### Performance Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--gremlin-cache` | flag | `false` | Enable incremental analysis cache |
| `--gremlin-clear-cache` | flag | `false` | Clear cache before running |
| `--gremlin-parallel` | flag | `false` | Enable parallel mutation execution |
| `--gremlin-workers` | integer | CPU count | Number of parallel workers (implies `--gremlin-parallel`) |
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

**Exclude files matching a glob pattern:**

```bash
pytest --gremlins --gremlin-exclude="**/migrations/*"
```

**Exclude multiple patterns (repeatable flag):**

```bash
pytest --gremlins --gremlin-exclude="**/migrations/*" --gremlin-exclude="**/generated/*"
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

**Enable parallel execution (use all CPU cores):**

```bash
pytest --gremlins --gremlin-parallel
```

**Parallel with specific worker count:**

```bash
pytest --gremlins --gremlin-workers=4
```

**Enable batch mode for reduced overhead:**

```bash
pytest --gremlins --gremlin-batch --gremlin-batch-size=20
```

**Combine multiple options:**

```bash
pytest --gremlins \
    --gremlin-targets=src/core \
    --gremlin-exclude="**/migrations/*" \
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
# Optional: auto-discovered from setuptools metadata, falling back to src/
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

# Number of parallel workers (integer or "auto" for os.cpu_count())
# Default: 1 (sequential)
workers = "auto"

# Enable incremental analysis cache
# Default: false
cache = true

# Report format(s): a single string, comma-separated string, or list
# Valid formats: "console", "html", "json"
# Default: "console"
report = ["html", "json"]

# Number of gremlins per batch in batch execution mode
# Default: 10
batch_size = 20

# Maximum number of pardoned gremlins (absolute ceiling)
# Default: no limit
max_pardons = 10

# Maximum percentage of pardoned gremlins (0-100)
# Default: no limit
max-pardons-pct = 5.0
```

### Configuration Options Table

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `paths` | list[string] | auto-discovered | Directories or files to scan for source code (falls back to `src/`) |
| `exclude` | list[string] | `[]` | Glob patterns for files to exclude |
| `operators` | list[string] | all | Operators to enable, in priority order |
| `workers` | int or `"auto"` | sequential | No parallelism unless `-n` or `--gremlin-parallel` is used; `"auto"` resolves to `os.cpu_count()` |
| `cache` | boolean | `false` | Enable incremental analysis cache |
| `report` | string or list | `"console"` | Report format(s): `"html"`, `"json"`, `"console"`, or a list like `["html", "json"]` |
| `batch_size` | int | `10` | Number of gremlins per batch in batch execution mode |
| `max_pardons` | int | no limit | Absolute ceiling on pardoned gremlins |
| `max-pardons-pct` | float | no limit | Maximum percentage of pardoned gremlins (0-100) |

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

## Inline Pardoning

Some gremlins produce code that behaves identically to the original (equivalent mutants), or
exercise paths you deliberately chose not to test. Rather than letting these inflate your
survivor count, you can **pardon** them with an inline pragma.

### Pragma Syntax

```python
return a // b  # gremlin: pardon[equivalent] integer division rounds same as subtraction
```

The pragma has three parts:

1. `# gremlin: pardon` -- the keyword (must be `pardon`, not `survivor`)
2. `[reason]` -- one of the valid reason codes (see below)
3. Free-text justification -- explains *why* this gremlin is pardoned

### Reason Codes

| Code | When to use |
|------|-------------|
| `equivalent` | The mutation produces identical behavior to the original code |
| `untestable` | The mutation affects code that cannot be exercised in a unit test (e.g., defensive `except` around OS calls) |
| `out_of_scope` | The mutation is in code you intentionally exclude from quality targets |

### Examples

```python
# Equivalent: both expressions evaluate to the same result
flags = set(items) | set(extras)  # gremlin: pardon[equivalent] union is commutative

# Untestable: requires hardware failure to trigger
try:
    fd = os.open(path, os.O_RDONLY)  # cspell:disable-line
except OSError:  # gremlin: pardon[untestable] OS-level failure path
    raise SystemExit(1)

# Out of scope: legacy adapter scheduled for removal
return legacy_convert(data)  # gremlin: pardon[out_of_scope] deprecated in Q3
```

### Enforcing Pardon Limits

Pardons are useful, but too many can silently inflate your mutation score. Use limits to
keep them in check:

**CLI flags:**

```bash
pytest --gremlins --max-pardons=10                 # fail if more than 10 pardons
pytest --gremlins --gremlin-max-pardons-pct=5.0    # fail if pardons exceed 5% of total
```

**pyproject.toml:**

```toml
[tool.pytest-gremlins]
max_pardons = 10
max-pardons-pct = 5.0
```

When either limit is exceeded, pytest-gremlins exits with a non-zero status and reports
which limit was violated.

### Migrating from `survivor` to `pardon`

In v1.5.0, the pragma keyword changed from `survivor` to `pardon`. The old keyword no
longer works. Update existing pragmas:

```python
# Old (no longer recognized)
x = val  # gremlin: survivor[equivalent] ...

# New
x = val  # gremlin: pardon[equivalent] ...
```

A project-wide find-and-replace handles this:

```bash
# Preview changes
grep -rn 'gremlin: survivor\[' src/

# Apply
sed -i 's/gremlin: survivor\[/gremlin: pardon\[/g' src/**/*.py
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

Use `--gremlin-parallel` to distribute mutations across multiple worker processes. Specifying a
worker count with `--gremlin-workers=N` automatically enables parallel mode:

```bash
pytest --gremlins --gremlin-parallel        # use all CPU cores
pytest --gremlins --gremlin-workers=4       # use 4 workers (implies --gremlin-parallel)
```

`--gremlin-parallel` without `--gremlin-workers` defaults to `os.cpu_count()` workers.
`--gremlin-workers=1` runs sequentially (useful for debugging).

Since v1.5.0, `--gremlins` and `-n` (pytest-xdist) work together via a **two-phase integration**:

- **Phase 1** distributes the test suite across xdist workers (the normal `-n auto` behavior)
- **Phase 2** uses xdist's resolved worker count for parallel mutation evaluation

This means `-n auto` is sufficient for both test distribution and mutation parallelism:

```bash
pytest --gremlins -n auto              # recommended: automatic parallelism
pytest --gremlins -n 4                 # explicit worker count
```

`--gremlin-workers` and `--gremlin-parallel` still work as standalone alternatives when you do
not want xdist involved in test distribution:

```bash
pytest --gremlins --gremlin-parallel   # use all CPU cores (no xdist)
pytest --gremlins --gremlin-workers=4  # specific worker count (no xdist)
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
    --gremlin-batch-size=20
```

## CI Integration

### GitHub Actions (Recommended)

The [pytest-gremlins-action](https://github.com/marketplace/actions/pytest-gremlins)
handles installation, parallel execution, caching, and score gating in a single step:

```yaml
- uses: mikelane/pytest-gremlins-action@v1
  with:
    threshold: 80
    parallel: 'true'
    cache: 'true'
```

See the [GitHub Action cookbook](../cookbook/github-action.md) for full configuration
options, caching details, and advanced usage.

If you need a manual workflow instead (e.g., self-hosted runners without marketplace access):

```yaml
name: Mutation Testing

on: [push, pull_request]

jobs:
  mutation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync

      - name: Run mutation testing
        run: |
          uv run pytest --gremlins \
            --gremlin-cache \
            --gremlin-parallel \
            --gremlin-report=json

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        with:
          name: mutation-report
          path: coverage/gremlins/gremlins.json
```

### GitLab CI

```yaml
mutation_testing:
  stage: test
  script:
    - pip install uv && uv sync
    - uv run pytest --gremlins --gremlin-cache --gremlin-parallel --gremlin-report=json
  artifacts:
    reports:
      junit: coverage/gremlins/gremlins.json
    paths:
      - coverage/gremlins/
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

```text
$ pytest --gremlins
No gremlins found: no source paths were discovered.

pytest-gremlins looks for source code in this order:
  1. --gremlin-targets CLI option
  2. [tool.pytest-gremlins] paths in pyproject.toml
  3. [tool.setuptools] package config in pyproject.toml
  4. [project].name heuristic
  5. setup.cfg packages config
  6. importlib.metadata (installed package metadata)
  7. src/ directory

If your source code is elsewhere, use: pytest --gremlins --gremlin-targets=your_package
```

The plugin auto-discovers source paths using seven strategies, tried in order:

1. `--gremlin-targets` CLI option
2. `[tool.pytest-gremlins] paths` in `pyproject.toml`
3. `[tool.setuptools]` package config in `pyproject.toml`
4. `[project].name` heuristic (looks for a directory matching the project name)
5. `setup.cfg` packages config
6. `importlib.metadata` (installed package metadata)
7. `src/` fallback

The first strategy that finds source files wins. If none of them match your layout:

1. Use `--gremlin-targets=your_package` to point at your source directly
2. Verify files are not excluded by `exclude` patterns
3. Ensure source files contain mutable code (not just imports/constants)
4. If you don't have a `pyproject.toml`, you must use `--gremlin-targets`

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
