# Getting Started

This guide will help you get pytest-gremlins up and running with your project.

## Installation

Install pytest-gremlins from PyPI:

```bash
pip install pytest-gremlins
```

Or with uv:

```bash
uv add pytest-gremlins
```

Or with poetry:

```bash
poetry add pytest-gremlins
```

## Requirements

- Python 3.11 or later
- pytest 7.0 or later

## First Run

Once installed, run mutation testing with a single flag:

```bash
pytest --gremlins
```

pytest-gremlins will:

1. **Instrument your code** - Parse source files and embed all possible mutations
2. **Build coverage map** - Run tests once to determine which tests cover which code
3. **Feed the gremlins** - Activate each mutation and run relevant tests
4. **Report results** - Show which gremlins survived (test gaps) and which were zapped

## Understanding the Output

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

- **Zapped** - Your tests caught these mutations. Good!
- **Survived** - Your tests didn't catch these mutations. These are test gaps.

## Next Steps

- [Configuration](configuration.md) - Customize behavior via `pyproject.toml`
- [Operators](operators.md) - Learn about available mutation types
- [Reports](reports.md) - Generate HTML and JSON reports
