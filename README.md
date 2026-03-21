# pytest-gremlins

**Fast-first mutation testing for pytest. Speed that makes mutation testing practical for everyday TDD.**

[![PyPI version](https://img.shields.io/pypi/v/pytest-gremlins.svg)](https://pypi.org/project/pytest-gremlins/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-gremlins.svg)](https://pypi.org/project/pytest-gremlins/)
[![CI](https://github.com/mikelane/pytest-gremlins/actions/workflows/ci.yml/badge.svg)](https://github.com/mikelane/pytest-gremlins/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/mikelane/pytest-gremlins/branch/main/graph/badge.svg)](https://codecov.io/gh/mikelane/pytest-gremlins)
[![Documentation](https://readthedocs.org/projects/pytest-gremlins/badge/?version=latest)](https://pytest-gremlins.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> *Let the gremlins loose. See which ones survive.*

---

## Key Features

- **Speed-First Architecture** - Mutation switching eliminates file I/O and module reloads. Run
  gremlins in seconds, not hours.
- **Native pytest Integration** - Zero configuration to start. Just add `--gremlins` to your pytest
  command.
- **Coverage-Guided Selection** - Only runs tests that actually cover the mutated code. 10-100x
  fewer test executions in well-modularized codebases.
- **Incremental Caching** - Results cached by content hash. Unchanged code skips re-testing entirely.
- **Parallel Execution** - Distribute gremlins across CPU cores for linear speedup.

---

## Quick Start

```bash
# Install
pip install pytest-gremlins

# Run mutation testing
pytest --gremlins
```

That's it. pytest-gremlins will instrument your code, release the gremlins, and report which ones
your tests zapped (good!) and which survived (test gaps!).

---

## Why pytest-gremlins?

**Code coverage lies.** It tells you what code your tests *execute*, but not whether your tests
would catch bugs.

**Mutation testing answers a harder question:** If I introduce a bug, will my tests fail?

### The Problem with Existing Tools

| Tool           | Limitation                                                 |
| -------------- | ---------------------------------------------------------- |
| **mutmut**     | Unix/WSL only (requires `fork()`); not a pytest plugin     |
| **Cosmic Ray** | Complex setup; distributed mode requires Celery            |
| **MutPy**      | Unmaintained (last update 2019), Python 3.4-3.7 only       |
| **mutatest**   | Unmaintained (last update 2022)                            |

See the [full comparison guide](https://pytest-gremlins.readthedocs.io/en/latest/guide/comparison/) for detailed, fair comparisons.

### Our Solution: Speed Through Architecture

pytest-gremlins is fast because of *how* it works, not just parallelization:

1. **Mutation Switching** - Instrument once, toggle mutations via environment variable
2. **Coverage Guidance** - Only run tests that cover the mutated code
3. **Incremental Analysis** - Skip unchanged code on repeat runs
4. **Parallel Execution** - Safe parallelization with no shared state

---

## Performance

<!-- TODO: verify benchmark — these numbers predate mutmut v3 parallelization; re-run and update -->
Benchmarked against [mutmut](https://github.com/boxed/mutmut) on a synthetic project:

| Mode                                                 | Time   | vs mutmut | Speedup           |
| ---------------------------------------------------- | ------ | --------- | ----------------- |
| `--gremlins` (sequential)                            | 17.79s | 14.90s    | 0.84x (see note)  |
| `--gremlins --gremlin-parallel`                      | 3.99s  | 14.90s    | **3.73x faster**  |
| `--gremlins --gremlin-parallel --gremlin-cache`      | 1.08s  | 14.90s    | **13.82x faster** |

**Key findings:**

- Sequential mode is slower due to subprocess isolation overhead; detailed profiling shows
  [1.7x slower on small targets](docs/performance/profiling-report.md)
- Parallel mode delivers **3.73x speedup** over mutmut
- With caching, subsequent runs are **13.82x faster**
- pytest-gremlins found 117 mutations vs mutmut's 86, with 98% kill rate vs 86%

---

## Example Output

```text
================== pytest-gremlins mutation report ==================

Zapped: 142 gremlins (85%)
Survived: 18 gremlins (11%)
Timeout: 5 gremlins (3%)
Error: 2 gremlins (1%)

Top surviving gremlins:
  src/auth.py:42                   >= to >               (comparison)
  src/utils.py:17                  + to -                (arithmetic)
  src/api.py:88                    True to False         (boolean)

Run with --gremlin-report=html for detailed report.
=====================================================================
```

Timeout, Error, and Pardoned categories are only shown when their count is greater than zero.

---

## Installation

```bash
# With pip
pip install pytest-gremlins

# With uv
uv add pytest-gremlins

# With poetry
poetry add pytest-gremlins
```

Requires Python 3.11+

---

## Configuration

Zero configuration required for most projects. The plugin auto-discovers source paths from your
`pyproject.toml` setuptools config (e.g., `[tool.setuptools.packages.find]`). If auto-discovery
doesn't find your code, configure paths explicitly:

```toml
[tool.pytest-gremlins]
# Operators to use (default: all 5)
operators = ["comparison", "arithmetic", "boolean", "boundary", "return"]

# Paths to mutate (optional -- auto-discovered from setuptools metadata)
paths = ["src"]

# Patterns to exclude
exclude = ["**/migrations/*", "**/test_*"]

# Report formats: "console", "html", "json" (default: console)
report = ["console", "html"]

# Enable incremental caching (default: false)
cache = true

# Fail if pardoned gremlins exceed 5% of total
max-pardons-pct = 5.0
```

---

## The Gremlins Theme

We use Gremlins movie references as our domain language:

| Traditional Term       | Gremlin Term            | Meaning                            |
| ---------------------- | ----------------------- | ---------------------------------- |
| Original code          | **Mogwai**              | Your clean, untouched source code  |
| Start mutation testing | **Feed after midnight** | Begin the mutation process         |
| Mutant                 | **Gremlin**             | A mutation injected into your code |
| Kill mutant            | **Zap**                 | Your test caught the mutation      |
| Surviving mutant       | **Survivor**            | Mutation your tests missed         |

---

## Documentation

Full documentation: [pytest-gremlins.readthedocs.io](https://pytest-gremlins.readthedocs.io)

- [Getting Started](https://pytest-gremlins.readthedocs.io/en/latest/guide/getting-started/)
- [Configuration](https://pytest-gremlins.readthedocs.io/en/latest/guide/configuration/)
- [API Reference](https://pytest-gremlins.readthedocs.io/en/latest/api/)

---

## Related Projects

- [pytest-test-categories](https://github.com/mikelane/pytest-test-categories) - Enforce Google
  test size standards in Python
- [dioxide](https://github.com/mikelane/dioxide) - Rust-backed dependency injection for Python

---

## Contributing

Contributions welcome! See our [Contributing Guide](CONTRIBUTING.md).

This project uses strict TDD discipline with BDD/Gherkin scenarios. All contributions must include
tests written *before* implementation.

> **Note on code coverage:** We target 69% coverage due to inherent limitations in measuring pytest
> plugins (import timing, subprocess execution). See
> [CONTRIBUTING.md](CONTRIBUTING.md#code-coverage) for details.

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.
