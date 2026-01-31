# pytest-gremlins

[![PyPI version](https://img.shields.io/pypi/v/pytest-gremlins.svg)](https://pypi.org/project/pytest-gremlins/)
[![Python versions](https://img.shields.io/pypi/pyversions/pytest-gremlins.svg)](https://pypi.org/project/pytest-gremlins/)
[![License](https://img.shields.io/pypi/l/pytest-gremlins.svg)](https://github.com/mikelane/pytest-gremlins/blob/main/LICENSE)
[![CI](https://github.com/mikelane/pytest-gremlins/actions/workflows/ci.yml/badge.svg)](https://github.com/mikelane/pytest-gremlins/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/mikelane/pytest-gremlins/branch/main/graph/badge.svg)](https://codecov.io/gh/mikelane/pytest-gremlins)
[![Documentation](https://readthedocs.org/projects/pytest-gremlins/badge/?version=latest)](https://pytest-gremlins.readthedocs.io)

> Let the gremlins loose. See which ones survive.

**pytest-gremlins** is a fast-first mutation testing plugin for pytest. It helps you evaluate the
quality of your test suite by injecting small changes (gremlins) into your code and checking if
your tests catch them.

## Why Mutation Testing?

Code coverage tells you what code your tests *execute*, but not whether your tests would catch bugs.
Mutation testing answers a harder question: **if I introduce a bug, will my tests fail?**

pytest-gremlins creates "gremlins" (small code mutations like changing `>=` to `>`) and runs your
tests against each one. If your tests pass despite the gremlin, you've found a weakness in your
test suite.

## Why pytest-gremlins?

Existing Python mutation testing tools are slow. pytest-gremlins is built for speed from day one:

- **Mutation Switching** - All mutations are embedded in a single instrumentation pass, toggled via
  environment variable. No file I/O or module reloading per mutation.
- **Coverage-Guided Selection** - Only runs tests that actually cover the mutated code.
- **Incremental Analysis** - Caches results. Unchanged code/tests don't get re-tested.
- **Parallel Execution** - Distributes gremlins across CPU cores.

## Performance

Benchmarked against [mutmut](https://github.com/boxed/mutmut) on a synthetic project (Python 3.12, Docker):

| Mode                                            | Time   | vs mutmut | Speedup           |
| ----------------------------------------------- | ------ | --------- | ----------------- |
| `--gremlins` (sequential)                       | 17.79s | 14.90s    | 0.84x             |
| `--gremlins --gremlin-parallel`                 | 3.99s  | 14.90s    | **3.73x faster**  |
| `--gremlins --gremlin-parallel --gremlin-cache` | 1.08s  | 14.90s    | **13.82x faster** |

**Key findings:**

- Sequential mode is ~16% slower than mutmut (more mutation operators enabled by default)
- Parallel mode delivers **3.73x speedup** over mutmut
- With caching enabled, subsequent runs are **13.82x faster**
- pytest-gremlins found 117 mutations vs mutmut's 86, with a 98% kill rate vs 86%

Run your own benchmarks:

```bash
docker run --rm -v "$(pwd):/project" -w /benchmark python:3.12-slim bash -c \
  "pip install pytest-gremlins mutmut && python /project/benchmarks/docker/run_comparison.py"
```

## Installation

```bash
pip install pytest-gremlins
```

Or with uv:

```bash
uv add pytest-gremlins
```

## Quick Start

Run mutation testing on your project:

```bash
pytest --gremlins
```

That's it. pytest-gremlins will:

1. Instrument your code with gremlins
2. Run your tests against each gremlin
3. Report which gremlins survived (test gaps) and which were zapped (good tests)

## Example Output

```text
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

## The Gremlins Theme

We use Gremlins movie references as our domain language:

| Traditional Term       | Gremlin Term            | Meaning                            |
| ---------------------- | ----------------------- | ---------------------------------- |
| Original code          | **Mogwai**              | Your clean, untouched source code  |
| Start mutation testing | **Feed after midnight** | Begin the mutation process         |
| Mutant                 | **Gremlin**             | A mutation injected into your code |
| Kill mutant            | **Zap**                 | Your test caught the mutation      |
| Surviving mutant       | **Survivor**            | Mutation your tests missed         |

## Documentation

Full documentation is available at [pytest-gremlins.readthedocs.io](https://pytest-gremlins.readthedocs.io).

- [User Guide](https://pytest-gremlins.readthedocs.io/en/latest/guide/)
- [Configuration Reference](https://pytest-gremlins.readthedocs.io/en/latest/configuration/)
- [API Reference](https://pytest-gremlins.readthedocs.io/en/latest/api/)

## Related Projects

- [pytest-test-categories](https://github.com/mikelane/pytest-test-categories) - Enforce Google test size standards in Python
- [dioxide](https://github.com/mikelane/dioxide) - Rust-backed dependency injection for Python

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

This project follows a strict TDD discipline and uses BDD with Gherkin scenarios. All contributions
must include tests written *before* implementation.

## License

MIT License. See [LICENSE](LICENSE) for details.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.
