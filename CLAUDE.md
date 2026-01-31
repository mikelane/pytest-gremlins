# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pytest-gremlins is a **fast-first** mutation testing plugin for pytest. Speed is the primary
differentiator - we aim to make mutation testing practical for everyday TDD, not just overnight
CI jobs.

## Design Documents

- [North Star](docs/design/NORTH_STAR.md) - Vision, speed architecture, success metrics
- [Operators](docs/design/OPERATORS.md) - Mutation operators design and registry
- [Agent Guidelines](docs/design/AGENT_GUIDELINES.md) - TDD laws, BDD process, CI/CD, release process

## Core Architecture (Speed-First)

Four pillars drive our speed strategy:

1. **Mutation Switching** - Instrument code once with all mutations embedded, toggle via environment
   variable. No file I/O, no module reloads during test runs.

2. **Coverage-Guided Test Selection** - Only run tests that actually cover the mutated code. 10-100x reduction in test executions.

3. **Incremental Analysis** - Cache results keyed by content hashes. Skip unchanged code/tests on subsequent runs.

4. **Parallel Execution** - Distribute gremlins across worker processes. Mutation switching makes
   this safe (no shared mutable state).

## Domain Language

| Traditional Term       | Gremlin Term            |
| ---------------------- | ----------------------- |
| Original code          | **Mogwai**              |
| Start mutation testing | **Feed after midnight** |
| Mutant                 | **Gremlin**             |
| Kill mutant            | **Zap**                 |
| Surviving mutant       | **Survivor**            |

## Project Structure

```text
pytest-gremlins/
├── src/pytest_gremlins/      # Source code
│   ├── __init__.py           # Package init with version
│   ├── plugin.py             # pytest plugin hooks
│   └── py.typed              # PEP 561 marker
├── tests/
│   ├── conftest.py           # Shared fixtures
│   ├── small/                # Unit tests (< 100ms)
│   ├── medium/               # Integration tests (< 10s)
│   └── large/                # E2E tests (< 60s)
├── features/                 # Gherkin scenarios
├── docs/
│   └── design/               # Design documents
├── .github/workflows/        # CI/CD
├── pyproject.toml            # Project config (uv, ruff, mypy, pytest)
├── tox.ini                   # Multi-version testing
└── .pre-commit-config.yaml   # Pre-commit hooks
```

## Build Commands

```bash
# Install dependencies
uv sync --dev

# Run small tests only (fast, always safe)
uv run pytest tests/small -m small

# Run small + medium tests (PR checks)
uv run pytest tests/small tests/medium

# Run all tests
uv run pytest

# Type checking (strict)
uv run mypy src/pytest_gremlins

# Linting
uv run ruff check src tests

# Formatting
uv run ruff format src tests

# All checks (what pre-commit runs)
uv run pre-commit run --all-files

# Multi-version testing
uv run tox

# Build docs
uv run mkdocs build --strict

# Run doctests
uv run pytest --doctest-modules src/pytest_gremlins
```

## TDD Laws (STRICTLY ENFORCED)

1. **No production code without a failing test**
2. **Only enough test code to fail**
3. **Only enough production code to pass**
4. **Refactor only when green**

## Code Style

- **Quotes:** Single quotes
- **Line length:** 120 characters
- **Type hints:** Required (strict mypy)
- **Docstrings:** Google style with doctests
- **Test names:** No "should" - use declarative statements

## Key Files

- `pyproject.toml` - All tool configuration (ruff, mypy, pytest, coverage, commitizen)
- `tox.ini` - Multi-Python version testing (3.11-3.14)
- `.pre-commit-config.yaml` - Pre-commit hooks
- `.github/workflows/ci.yml` - CI pipeline
- `.github/workflows/release.yml` - Release pipeline with Test PyPI
