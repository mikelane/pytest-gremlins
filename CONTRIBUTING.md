# Contributing to pytest-gremlins

Thank you for your interest in contributing to pytest-gremlins! This document provides guidelines and instructions for contributing.

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How to Contribute

### Reporting Bugs

Before creating a bug report, please check existing issues to avoid duplicates. When creating a bug report, include:

- A clear, descriptive title
- Steps to reproduce the behavior
- Expected behavior
- Actual behavior
- Python version and OS
- pytest-gremlins version
- Minimal code example if possible

### Suggesting Features

Feature requests are welcome! Please:

- Check existing issues and discussions first
- Describe the problem you're trying to solve
- Explain your proposed solution
- Consider alternatives you've thought about

### Pull Requests

We love pull requests! Here's how to contribute code:

1. Fork the repository
2. Create a feature branch from `main`
3. Follow our development workflow (see below)
4. Submit a pull request

## Development Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for package management
- [Graphite](https://graphite.dev/) for stacked PRs (recommended)
- Git

### Initial Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/pytest-gremlins.git
cd pytest-gremlins

# Install dependencies
uv sync --dev

# Install pre-commit hooks
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg

# Verify setup
uv run pytest tests/small
```

## Development Workflow

### The Golden Rule: TDD

We follow **strict Test-Driven Development**. This is non-negotiable:

1. **Write a failing test first** - Before any production code
2. **Write minimal code to pass** - No more, no less
3. **Refactor while green** - Clean up only when tests pass

### BDD with Gherkin

For features, we write Gherkin scenarios first:

```gherkin
# features/my_feature.feature
Feature: Description of the feature

  Scenario: Specific behavior
    Given some precondition
    When I take some action
    Then I expect some outcome
```

Then implement step definitions in `tests/` before writing production code.

### Working in Isolated Worktrees

All development happens in git worktrees:

```bash
# Create a worktree for your feature
git worktree add ../pytest-gremlins-my-feature feature/my-feature

# Work in the worktree
cd ../pytest-gremlins-my-feature

# When done, clean up
git worktree remove ../pytest-gremlins-my-feature
```

### Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`

**Examples:**
```
feat(operators): add string mutation operator
fix(instrumentation): handle async functions correctly
docs(readme): add installation instructions
test(operators): add tests for boundary mutations
```

### Running Tests

```bash
# Run small (unit) tests - always fast
uv run pytest tests/small

# Run small + medium tests
uv run pytest tests/small tests/medium

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=pytest_gremlins --cov-report=html

# Run specific test file
uv run pytest tests/small/pytest_gremlins/test_operators.py

# Run specific test
uv run pytest tests/small/pytest_gremlins/test_operators.py::test_comparison_mutation
```

### Code Quality Checks

```bash
# Linting
uv run ruff check src tests
uv run ruff format --check src tests

# Type checking
uv run mypy src/pytest_gremlins

# Run all checks (pre-commit runs these)
uv run pre-commit run --all-files
```

### Test Categories

We use [pytest-test-categories](https://github.com/mikelane/pytest-test-categories):

| Category | Location | Characteristics | Timeout |
|----------|----------|-----------------|---------|
| Small | `tests/small/` | Pure functions, no I/O, mocked deps | < 100ms |
| Medium | `tests/medium/` | Real filesystem, database, multiple components | < 10s |
| Large | `tests/large/` | End-to-end, external services | < 60s |

### Documentation

- All public APIs need docstrings (Google style)
- Include doctests for examples
- Update user guide for behavior changes
- Run doctests: `uv run pytest --doctest-modules src/pytest_gremlins`

## Pull Request Checklist

Before submitting a PR, ensure:

- [ ] Tests written FIRST (TDD)
- [ ] All tests pass (`uv run pytest`)
- [ ] Type checking passes (`uv run mypy src/pytest_gremlins`)
- [ ] Linting passes (`uv run ruff check .`)
- [ ] Formatting correct (`uv run ruff format --check .`)
- [ ] Docstrings added/updated for public APIs
- [ ] Doctests pass (`uv run pytest --doctest-modules src/pytest_gremlins`)
- [ ] Documentation updated if behavior changed
- [ ] Commit messages follow conventional commits
- [ ] PR description explains the change

## Code Style

- **Quotes:** Single quotes for strings
- **Line length:** 120 characters
- **Imports:** Sorted with vertical hanging indent
- **Type hints:** Required for all public functions
- **Docstrings:** Google style, required for public APIs

Example:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_gremlins.operators import (
    ArithmeticOperator,
    BooleanOperator,
    ComparisonOperator,
)


if TYPE_CHECKING:
    from collections.abc import Sequence


def process_gremlins(
    operators: Sequence[str],
    *,
    parallel: bool = True,
) -> list[str]:
    """Process gremlins using the specified operators.

    Args:
        operators: Names of operators to use.
        parallel: Whether to run in parallel.

    Returns:
        List of gremlin IDs that were processed.

    Raises:
        ValueError: If no operators are specified.

    Examples:
        >>> process_gremlins(['comparison', 'boolean'])
        ['gremlin_001', 'gremlin_002', ...]

    """
    if not operators:
        raise ValueError('At least one operator must be specified')
    # Implementation...
```

## Getting Help

- Open an issue for bugs or feature requests
- Start a discussion for questions
- Check existing issues and discussions first

## Recognition

Contributors are recognized in our release notes. Thank you for helping make pytest-gremlins better!
