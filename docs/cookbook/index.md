# Cookbook

Practical, copy-paste recipes for integrating pytest-gremlins into your projects.

## What is the Cookbook?

The cookbook provides complete, ready-to-use configurations for common scenarios. Each recipe includes:

- **Goal** - What you're trying to achieve
- **Prerequisites** - What you need before starting
- **Steps** - Numbered, copy-paste instructions
- **Configuration** - Complete config files (not snippets)
- **Verification** - How to confirm it works
- **Troubleshooting** - Common issues and fixes

## Available Recipes

### CI/CD Integration

| Recipe | Description |
|--------|-------------|
| [GitHub Actions](ci-integration.md#github-actions) | Complete workflow with caching and matrix builds |
| [GitLab CI](ci-integration.md#gitlab-ci) | Pipeline with stages and artifacts |
| [CircleCI](ci-integration.md#circleci) | Orb-based configuration with parallelism |

### Project Types

| Recipe | Description |
|--------|-------------|
| [Django Projects](django.md) | Models, views, and Django-specific settings |
| [FastAPI Projects](fastapi.md) | Async code, dependency injection, API endpoints |
| [Monorepo Setup](monorepo.md) | Multi-package repos with selective testing |

### Development Workflow

| Recipe | Description |
|--------|-------------|
| [TDD Workflow](tdd-workflow.md) | Red-Green-Refactor-Mutate cycle |
| [Pre-commit Hook](pre-commit.md) | Fast incremental runs on commit |
| [pytest Plugin Compatibility](pytest-plugins.md) | Integration with pytest-cov, pytest-xdist |

## Quick Reference

### Minimum Configuration

```toml
# pyproject.toml
[tool.pytest-gremlins]
paths = ["src"]
```

### Run Mutation Testing

```bash
# Basic run
pytest --gremlins

# With HTML report
pytest --gremlins --gremlin-report=html

# Quick run (comparison operators only)
pytest --gremlins --gremlin-operators=comparison

# With incremental caching
pytest --gremlins --gremlin-cache
```

### Common Command Patterns

```bash
# Development: fast feedback on changed code
pytest --gremlins --gremlin-cache

# CI: full run with report
pytest --gremlins --gremlin-report=html

# Debug: single file
pytest --gremlins --gremlin-targets=src/mymodule.py

# Performance: parallel execution
pytest --gremlins --gremlin-parallel --gremlin-workers=4
```

## Getting Help

- [Configuration Reference](../guide/configuration.md) - All configuration options
- [Operators Guide](../guide/operators.md) - Available mutation operators
- [GitHub Issues](https://github.com/mikelane/pytest-gremlins/issues) - Report problems or request features
