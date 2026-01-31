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
| `--gremlin-report` | `console` | Report format: `console`, `html`, `json` |
| `--gremlin-targets` | `src/` | Comma-separated source directories/files |
| `--gremlin-cache` | `False` | Enable incremental analysis cache |
| `--gremlin-clear-cache` | `False` | Clear cache before running |
| `--gremlin-parallel` | `False` | Enable parallel execution |
| `--gremlin-workers` | CPU count | Number of parallel workers |
| `--gremlin-batch` | `False` | Enable batch execution mode |
| `--gremlin-batch-size` | `10` | Gremlins per batch |

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

# Patterns to exclude (not yet implemented)
exclude = ["**/migrations/**"]
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
| `report_format` | `str` | Output format (console/html/json) |
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

```python
def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-gremlins based on command-line options."""
```

### pytest_collection_finish

After test collection completes, discovers source files and generates gremlins.

```python
def pytest_collection_finish(session: pytest.Session) -> None:
    """After test collection, discover source files and generate gremlins."""
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
