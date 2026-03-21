# Plugin Module

The plugin module provides the pytest integration for pytest-gremlins. It implements pytest hooks
that enable mutation testing as part of the test lifecycle.

## Overview

The plugin handles:

1. **Command-line options** - Adding `--gremlins` and related flags
2. **Configuration** - Loading settings from pyproject.toml and merging with CLI
3. **Source discovery** - Finding Python files to mutate
4. **Instrumentation** - Transforming source code with embedded mutations
5. **Test execution** - Running tests against each gremlin
6. **Result reporting** - Displaying mutation scores and survivors

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--gremlins` | `False` | Enable mutation testing |
| `--gremlin-operators` | All | Comma-separated list of operators to use |
| `--gremlin-report` | `console` | Report format: `console`, `html`, `json` (repeatable) |
| `--gremlin-targets` | None (auto-discovered) | Comma-separated source directories/files |
| `--gremlin-exclude` | None | Glob patterns to exclude from mutation (repeatable) |
| `--gremlin-cache` | `False` | Enable incremental analysis cache |
| `--gremlin-clear-cache` | `False` | Clear cache before running |
| `--gremlin-parallel` | `False` | Enable parallel execution |
| `--gremlin-workers` | CPU count | Number of parallel workers |
| `--gremlin-batch` | `False` | Enable batch execution mode |
| `--gremlin-batch-size` | `10` | Gremlins per batch |
| `--gremlins-html-dir` | None | Output directory for HTML reports |
| `--strict-pardons` | `False` | Treat pardoned gremlins as CI failures (exit non-zero if any exist) |
| `--gremlin-audit-pardons` | `False` | Audit pardon pragma usage |
| `--gremlin-max-pardons-pct` | None | Maximum percentage of pardoned gremlins |
| `--max-pardons` | None | Maximum absolute number of pardoned gremlins |

## Usage Examples

### Basic Usage

```bash
# Enable mutation testing
pytest --gremlins

# Target specific directory
pytest --gremlins --gremlin-targets=mypackage/

# Generate HTML report
pytest --gremlins --gremlin-report=html
```

### With Caching

```bash
# Enable incremental caching (faster subsequent runs)
pytest --gremlins --gremlin-cache

# Clear cache and start fresh
pytest --gremlins --gremlin-cache --gremlin-clear-cache
```

### Parallel Execution

```bash
# Run with parallel workers (auto-detects CPU count)
pytest --gremlins --gremlin-parallel

# Specify worker count
pytest --gremlins --gremlin-parallel --gremlin-workers=8

# Use batch mode for reduced subprocess overhead
pytest --gremlins --gremlin-batch --gremlin-batch-size=20
```

### Selective Operators

```bash
# Use only comparison and boundary operators
pytest --gremlins --gremlin-operators=comparison,boundary

# Use only arithmetic operator
pytest --gremlins --gremlin-operators=arithmetic
```

## Configuration

Configuration can be specified in `pyproject.toml` under `[tool.pytest-gremlins]`:

```toml
[tool.pytest-gremlins]
# Mutation operators to enable
operators = ["comparison", "arithmetic", "boolean"]

# Source paths to mutate
paths = ["src/mypackage"]

# Glob patterns to exclude from mutation
exclude = ["**/migrations/**"]

# Number of parallel workers ("auto" or an integer)
workers = "auto"

# Enable incremental analysis cache
cache = true

# Report formats
report = ["html", "json"]

# Gremlins per batch in batch mode
batch_size = 20

# Pardon budget (percentage and absolute cap)
max-pardons-pct = 5.0
max_pardons = 10
```

### Configuration Precedence

1. CLI arguments (highest priority)
2. pyproject.toml `[tool.pytest-gremlins]` section
3. Built-in defaults (lowest priority)

---

## GremlinConfig

::: pytest_gremlins.config.GremlinConfig
    options:
      show_root_heading: true
      show_source: true
      members:
        - operators
        - paths
        - exclude
        - workers
        - cache
        - report
        - batch_size
        - max_pardons_pct
        - max_pardons

## Configuration Functions

::: pytest_gremlins.config.load_config
    options:
      show_root_heading: true
      show_source: true

::: pytest_gremlins.config.merge_configs
    options:
      show_root_heading: true
      show_source: true

---

## GremlinSession

The `GremlinSession` dataclass maintains state throughout a mutation testing run.

::: pytest_gremlins.plugin.GremlinSession
    options:
      show_root_heading: true
      show_source: true

### Session Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `enabled` | `bool` | Whether mutation testing is active |
| `operators` | `list[GremlinOperator]` | Active mutation operators |
| `report_formats` | `list[str]` | Output formats (console/html/json) |
| `gremlins` | `list[Gremlin]` | All discovered gremlins |
| `results` | `list[GremlinResult]` | Test results for each gremlin |
| `source_files` | `dict[str, str]` | Map of file paths to source code |
| `test_files` | `list[Path]` | Collected test file paths |
| `target_paths` | `list[Path]` | Source paths to mutate |
| `instrumented_dir` | `Path \| None` | Temp directory with instrumented code |
| `coverage_collector` | `CoverageCollector \| None` | Coverage data collector |
| `test_selector` | `TestSelector \| None` | Coverage-based test selector |
| `prioritized_selector` | `PrioritizedSelector \| None` | Priority-ordered selector |
| `test_node_ids` | `dict[str, str]` | Map of test names to pytest node IDs |
| `total_tests` | `int` | Total number of collected tests |
| `cache_enabled` | `bool` | Whether caching is active |
| `cache` | `IncrementalCache \| None` | The cache instance |
| `source_hashes` | `dict[str, str]` | Content hashes for source files |
| `test_hashes` | `dict[str, str]` | Content hashes for test files |
| `cache_hits` | `int` | Number of cache hits |
| `cache_misses` | `int` | Number of cache misses |
| `parallel_enabled` | `bool` | Whether parallel mode is active |
| `parallel_workers` | `int \| None` | Number of workers (None = auto) |
| `batch_enabled` | `bool` | Whether batch mode is active |
| `batch_size` | `int` | Gremlins per batch |
| `xdist_item_ids` | `list[str] \| None` | Test IDs captured from xdist workers |
| `xdist_active` | `bool` | Whether xdist is active |
| `xdist_workers` | `int \| None` | Number of xdist workers |
| `coverage_mode` | `CoverageMode` | PIGGYBACK (reuse pytest-cov) or PRIVATE |
| `private_coverage` | `coverage.Coverage \| None` | Inline coverage instance (PRIVATE mode) |
| `gremlins_tmpdir` | `str \| None` | Shared temp dir for xdist worker coverage data |
| `exclude_patterns` | `list[str]` | Glob patterns to skip during source discovery |
| `strict_pardons` | `bool` | Treat pardoned gremlins as CI failures (exit non-zero if any exist) |
| `audit_pardons` | `bool` | Whether to audit pardon pragma usage |
| `max_pardons_pct` | `float \| None` | Maximum percentage of pardoned gremlins |
| `max_pardons` | `int \| None` | Maximum absolute pardon count |

---

## pytest Hooks

The plugin implements these pytest hooks:

### pytest_addoption

Adds command-line options for mutation testing configuration.

```python
def pytest_addoption(parser: pytest.Parser) -> None:
    """Add command-line options for pytest-gremlins."""
```

### pytest_configure

Initializes the gremlin session based on command-line options and pyproject.toml.
When xdist is available, also registers `pytest_configure_node` and
`pytest_xdist_node_collection_finished` hooks.

```python
def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-gremlins based on command-line options."""
```

### pytest_sessionstart

Sets up inline coverage collection in PRIVATE mode (when `--cov` is not active).

```python
def pytest_sessionstart(session: pytest.Session) -> None:
    """Start inline coverage collection if needed."""
```

### pytest_runtestloop

Hookimpl wrapper that saves and stops coverage data after the test loop completes.

```python
def pytest_runtestloop(session: pytest.Session) -> Generator[None, None, None]:
    """Wrap the test loop to capture coverage data."""
```

### pytest_collection_finish

After test collection completes, discovers source files and generates gremlins.

```python
def pytest_collection_finish(session: pytest.Session) -> None:
    """After test collection, discover source files and generate gremlins."""
```

### pytest_configure_node (xdist only)

Passes gremlin temp directory path to xdist workers via `node.workerinput`.

```python
def pytest_configure_node(node: _XdistWorkerNode) -> None:
    """Pass gremlins config to xdist worker nodes."""
```

### pytest_xdist_node_collection_finished (xdist only)

Captures test node IDs from the first xdist worker's collection.

```python
def pytest_xdist_node_collection_finished(node: object, ids: list[str]) -> None:
    """Capture collected test IDs from xdist workers."""
```

### pytest_sessionfinish

After all tests run, executes mutation testing against each gremlin.

```python
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """After all tests run, execute mutation testing."""
```

### pytest_terminal_summary

Adds mutation testing results to pytest's terminal output.

```python
def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    """Add mutation testing results to terminal output."""
```

### pytest_unconfigure

Cleans up temporary files and closes resources.

```python
def pytest_unconfigure(config: pytest.Config) -> None:
    """Clean up after pytest-gremlins."""
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ACTIVE_GREMLIN` | Set by plugin to indicate which gremlin is active during test execution |
| `PYTEST_GREMLINS_SOURCES_FILE` | Path to JSON file containing instrumented source code |

---

## Internal Functions

These functions are internal to the plugin but documented for understanding the implementation.

### Source Discovery

```python
def _discover_source_files(
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> dict[str, str]:
    """Discover Python source files to mutate."""
```

### Test Selection

```python
def _select_tests_for_gremlin_prioritized(
    gremlin: Gremlin,
    gremlin_session: GremlinSession,
) -> list[str]:
    """Select tests for a gremlin, ordered by specificity."""
```

### Mutation Testing Execution

```python
def _run_mutation_testing(
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Run mutation testing for all gremlins (sequential mode)."""

def _run_parallel_mutation_testing(
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Run mutation testing in parallel across multiple workers."""

def _run_batch_mutation_testing(
    session: pytest.Session,
    gremlin_session: GremlinSession,
) -> list[GremlinResult]:
    """Run mutation testing using batch execution."""
```
