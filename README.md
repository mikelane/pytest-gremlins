# pytest-gremlins

**Fast-first mutation testing for pytest. Speed that makes mutation testing practical for everyday TDD.**

[![PyPI version](https://img.shields.io/pypi/v/pytest-gremlins.svg)](https://pypi.org/project/pytest-gremlins/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-gremlins.svg)](https://pypi.org/project/pytest-gremlins/)
[![CI](https://github.com/mikelane/pytest-gremlins/actions/workflows/ci.yml/badge.svg)](https://github.com/mikelane/pytest-gremlins/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/mikelane/pytest-gremlins/branch/main/graph/badge.svg)](https://codecov.io/gh/mikelane/pytest-gremlins)
[![Documentation](https://readthedocs.org/projects/pytest-gremlins/badge/?version=latest)](https://pytest-gremlins.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> *Let the gremlins loose. See which ones survive.*

---

## Key Features

- **Speed-First Architecture** - Mutation switching eliminates file I/O and module reloads. Run
  gremlins in seconds, not hours.
- **Native pytest Integration** - Zero configuration to start. Just add `--gremlins` to your pytest
  command.
- **Coverage-Guided Selection** - Only runs tests that actually cover the mutated code. 10-100x
  fewer test executions.
- **Incremental Caching** - Results cached by content hash. Unchanged code skips re-testing entirely.
- **Parallel Execution** - Distribute gremlins across CPU cores for linear speedup.

---

## Quick Start

Install and run mutation testing in 30 seconds:

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

| Tool           | Fatal Flaw                                              |
| -------------- | ------------------------------------------------------- |
| **mutmut**     | Single-threaded, no incremental analysis, 65+ minute runs |
| **Cosmic Ray** | Requires Celery + RabbitMQ for parallelization          |
| **MutPy**      | Dead (last update 2019), Python 3.4-3.7 only            |
| **mutatest**   | Dead (last update 2022), Python <=3.8 only              |

### Our Solution: Speed Through Architecture

pytest-gremlins is fast because of *how* it works, not just parallelization:

1. **Mutation Switching** - Instrument once, toggle mutations via environment variable
2. **Coverage Guidance** - Only run tests that cover the mutated code
3. **Incremental Analysis** - Skip unchanged code on repeat runs
4. **Parallel Execution** - Safe parallelization with no shared state

---

## Performance

Benchmarked against [mutmut](https://github.com/boxed/mutmut) on a synthetic project:

| Mode                                            | Time   | vs mutmut | Speedup           |
| ----------------------------------------------- | ------ | --------- | ----------------- |
| `--gremlins` (sequential)                       | 17.79s | 14.90s    | 0.84x             |
| `--gremlins --gremlin-parallel`                 | 3.99s  | 14.90s    | **3.73x faster**  |
| `--gremlins --gremlin-parallel --gremlin-cache` | 1.08s  | 14.90s    | **13.82x faster** |

**Key findings:**
- Sequential mode is ~16% slower (more mutation operators enabled by default)
- Parallel mode delivers **3.73x speedup** over mutmut
- With caching, subsequent runs are **13.82x faster**
- pytest-gremlins found 117 mutations vs mutmut's 86, with 98% kill rate vs 86%

---

## Example Output

```text
================== pytest-gremlins mutation report ==================

Zapped: 142 gremlins (89%)
Survived: 18 gremlins (11%)

Top surviving gremlins:
  src/auth.py:42    >= -> >     (boundary not tested)
  src/utils.py:17   + -> -      (arithmetic not verified)
  src/api.py:88     True -> False (return value unchecked)

Run with --gremlin-report=html for detailed report.
=====================================================================
```

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

**Requires Python 3.11+**

---

## Configuration

Configure in `pyproject.toml`:

```toml
[tool.pytest-gremlins]
# Operators to use (default: all)
operators = ["comparison", "arithmetic", "boolean"]

# Paths to mutate
paths = ["src"]

# Patterns to exclude
exclude = ["**/migrations/*", "**/test_*"]

# Minimum mutation score to pass
min_score = 80
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

- [User Guide](https://pytest-gremlins.readthedocs.io/en/latest/guide/)
- [Configuration Reference](https://pytest-gremlins.readthedocs.io/en/latest/configuration/)
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

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.
