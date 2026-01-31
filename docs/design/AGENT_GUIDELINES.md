# Agent Guidelines & Development Standards

> "Discipline is the bridge between goals and accomplishment."

This document defines the guardrails, processes, and standards that all agents (and humans) must
follow when developing pytest-gremlins.

---

## Table of Contents

1. [Core Principles](#core-principles)
2. [TDD: The Three Laws](#tdd-the-three-laws)
3. [BDD: Behavior-Driven Development](#bdd-behavior-driven-development)
4. [Development Workflow](#development-workflow)
5. [Git & Branching Strategy](#git--branching-strategy)
6. [Code Quality Standards](#code-quality-standards)
7. [Testing Strategy](#testing-strategy)
8. [Documentation Requirements](#documentation-requirements)
9. [CI/CD Pipeline](#cicd-pipeline)
10. [Release Process](#release-process)
11. [Agent Boundaries](#agent-boundaries)

---

## Core Principles

1. **Tests before code** - No exceptions. Ever.
2. **Documentation is code** - Same lifecycle, same rigor, same CI enforcement
3. **Small, reviewable PRs** - Stacked via Graphite, easy to understand
4. **Isolated development** - All work happens in git worktrees
5. **Automate everything** - If a human has to remember it, automate it
6. **Dogfood early** - Use pytest-gremlins on pytest-gremlins ASAP

---

## TDD: The Three Laws

TDD enforcement is **ULTRA strict**. These are not guidelines—they are laws:

### Law 1: Failing Test First
>
> You may not write any production code unless it is to make a failing test pass.

Before touching `src/`, there must be a failing test in `tests/`. No "I'll add tests later."
No "this is just a small change." No exceptions.

### Law 2: Minimal Test Code
>
> You may only write as much test code as required to make a test fail (and build/compile failures count as test failures).

Don't write a complete test suite upfront. Write ONE assertion that fails. Make it pass. Write the next assertion. Red-green-red-green.

### Law 3: Minimal Production Code
>
> You may only write as much production code as required to make a failing test pass.

Don't gold-plate. Don't add "while I'm here" features. Write the minimum code to go from red to green.

### Law 4: Refactor
>
> Engage in pragmatic refactoring once tests are passing.

Green means you can refactor. Improve structure, extract methods, rename things. But only when green. And stay green.

### The TDD Cycle

```text
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│    ┌─────────┐     ┌─────────┐     ┌─────────────┐         │
│    │  RED    │────►│  GREEN  │────►│  REFACTOR   │         │
│    │         │     │         │     │             │         │
│    │ Write a │     │ Write   │     │ Clean up    │         │
│    │ failing │     │ minimal │     │ while       │         │
│    │ test    │     │ code to │     │ staying     │         │
│    │         │     │ pass    │     │ green       │         │
│    └─────────┘     └─────────┘     └──────┬──────┘         │
│         ▲                                 │                 │
│         │                                 │                 │
│         └─────────────────────────────────┘                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## BDD: Behavior-Driven Development

We use **Gherkin** to define behaviors and **Cucumber** (via pytest-bdd) for automated acceptance testing.

### The BDD Flow

1. **PM Agent** writes Gherkin scenarios based on requirements
2. **QA Agent** reviews scenarios, adds edge cases
3. **Dev Agent** implements step definitions (tests) FIRST
4. **Dev Agent** implements production code to make steps pass
5. **Scenarios become living documentation**

### Gherkin Standards

```gherkin
Feature: Mutation Switching
  As a developer using pytest-gremlins
  I want mutations to be controlled via environment variable
  So that I can run tests against different mutations without reloading code

  Background:
    Given a Python file with a comparison operator
    And the file has been instrumented with gremlins

  Scenario: Default behavior runs original code
    Given no ACTIVE_GREMLIN environment variable is set
    When I execute the instrumented code
    Then the original comparison logic executes

  Scenario: Setting ACTIVE_GREMLIN activates a mutation
    Given ACTIVE_GREMLIN is set to "gremlin_001"
    When I execute the instrumented code
    Then the mutated comparison logic executes

  Scenario Outline: Different gremlins produce different mutations
    Given ACTIVE_GREMLIN is set to "<gremlin_id>"
    When I execute the comparison "age >= 18"
    Then the result matches "<expected_operator>"

    Examples:
      | gremlin_id  | expected_operator |
      | gremlin_001 | age > 18          |
      | gremlin_002 | age <= 18         |
      | gremlin_003 | age < 18          |
```

### Scenario Guidelines

- **Declarative, not imperative** - Describe WHAT, not HOW
- **Business language** - Avoid technical implementation details
- **One behavior per scenario** - Keep them focused
- **Use Background** - For common setup across scenarios
- **Scenario Outlines** - For parameterized testing

### File Organization

```text
features/
├── mutation_switching.feature
├── coverage_guidance.feature
├── incremental_analysis.feature
├── parallel_execution.feature
├── operators/
│   ├── comparison.feature
│   ├── arithmetic.feature
│   └── boolean.feature
└── reporting/
    ├── console_output.feature
    └── html_report.feature
```

---

## Development Workflow

### 1. Story Breakdown (PM Agent)

- PM agent breaks epics into stories
- Stories have clear acceptance criteria (Gherkin scenarios)
- Stories are sized for single PRs where possible

### 2. Development (Dev Agent)

```bash
# 1. Create isolated worktree
git worktree add ../pytest-gremlins-feature-xyz feature/xyz

# 2. Navigate to worktree
cd ../pytest-gremlins-feature-xyz

# 3. Write Gherkin scenarios (if not already done)
# 4. Write step definitions (failing tests)
# 5. Write minimal production code
# 6. Refactor while green
# 7. Commit with conventional commits

# 8. Create stacked PRs with Graphite
gt create -m "feat(operators): add comparison operator protocol"
gt create -m "feat(operators): implement comparison mutations"
gt create -m "test(operators): add comparison operator tests"

# 9. Push stack
gt push
```

### 3. Code Review (Reviewer Agent)

- Automated review against standards
- Check TDD compliance (tests exist, coverage adequate)
- Check documentation updates
- Check conventional commit format

### 4. Merge

- All status checks pass
- No conflicts with base branch
- Reviewer agent approves
- Squash merge to maintain linear history

### 5. Cleanup

```bash
# Remove worktree after merge
git worktree remove ../pytest-gremlins-feature-xyz
```

---

## Git & Branching Strategy

### Branch Naming

```text
feature/short-description    # New features
fix/short-description        # Bug fixes
docs/short-description       # Documentation only
refactor/short-description   # Code refactoring
chore/short-description      # Maintenance tasks
```

### Commit Messages (Conventional Commits)

```text
type(scope): description

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`

**Examples:**

```text
feat(operators): add comparison operator

Implements the comparison gremlin operator that mutates
<, <=, >, >=, ==, != operators.

Closes #42
```

```text
fix(instrumentation): handle async functions correctly

Async functions were losing their coroutine status after
instrumentation. This preserves the async wrapper.

Fixes #57
```

### Graphite Stacks

- **Max PR size:** ~400 lines changed (soft limit)
- **Stack depth:** As needed, but prefer shallow (2-3 PRs)
- **Each PR:** Single logical change, independently reviewable

### Worktree Requirements

**All development happens in isolated git worktrees.** Never commit directly from the main worktree.

```bash
# List active worktrees
git worktree list

# Create worktree for feature
git worktree add ../pytest-gremlins-{branch-name} {branch-name}

# Remove when done
git worktree remove ../pytest-gremlins-{branch-name}
```

---

## Code Quality Standards

### Python Version Support

- Python 3.11, 3.12, 3.13, 3.14
- Test all versions in CI matrix
- Use `from __future__ import annotations` for forward compat

### Project Structure

```text
pytest-gremlins/
├── src/
│   └── pytest_gremlins/
│       ├── __init__.py
│       ├── plugin.py           # pytest plugin hooks
│       ├── operators/
│       │   ├── __init__.py
│       │   ├── base.py         # GremlinOperator protocol
│       │   ├── registry.py     # OperatorRegistry
│       │   ├── comparison.py
│       │   ├── arithmetic.py
│       │   └── boolean.py
│       ├── instrumentation/
│       │   ├── __init__.py
│       │   ├── transformer.py  # AST transformation
│       │   └── switcher.py     # Mutation switching logic
│       ├── coverage/
│       │   ├── __init__.py
│       │   └── mapper.py       # Coverage-guided selection
│       ├── history/
│       │   ├── __init__.py
│       │   └── database.py     # Incremental analysis storage
│       └── reporting/
│           ├── __init__.py
│           ├── console.py
│           └── html.py
├── tests/
│   ├── conftest.py
│   ├── small/                  # Fast, isolated unit tests
│   │   └── pytest_gremlins/
│   │       ├── operators/
│   │       ├── instrumentation/
│   │       └── ...
│   ├── medium/                 # Integration tests
│   │   └── pytest_gremlins/
│   │       └── ...
│   └── large/                  # End-to-end, real filesystem
│       └── pytest_gremlins/
│           └── ...
├── features/                   # Gherkin scenarios
│   └── ...
├── docs/
│   ├── design/
│   │   ├── NORTH_STAR.md
│   │   ├── OPERATORS.md
│   │   └── AGENT_GUIDELINES.md
│   ├── user-guide/
│   ├── api/
│   └── changelog.md
├── pyproject.toml
├── tox.ini
├── .pre-commit-config.yaml
├── CLAUDE.md
├── README.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
└── LICENSE
```

### Type Checking (mypy)

**Strict mode from day one.** No `# type: ignore` without justification.

```toml
# pyproject.toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_configs = true
```

### Linting (Ruff)

```toml
# pyproject.toml
[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # Pyflakes
    "I",      # isort
    "B",      # flake8-bugbear
    "C4",     # flake8-comprehensions
    "UP",     # pyupgrade
    "ARG",    # flake8-unused-arguments
    "SIM",    # flake8-simplify
    "TCH",    # flake8-type-checking
    "PTH",    # flake8-use-pathlib
    "ERA",    # eradicate (commented-out code)
    "PL",     # Pylint
    "RUF",    # Ruff-specific rules
]
ignore = [
    "PLR0913",  # Too many arguments (we'll manage this ourselves)
]

[tool.ruff.format]
quote-style = "single"

[tool.ruff.lint.isort]
force-single-line = false
force-sort-within-sections = true
known-first-party = ["pytest_gremlins"]
combine-as-imports = true
split-on-trailing-comma = true
```

### Import Sorting (isort via Ruff)

Vertical hanging indent with force grid wrap:

```python
# Correct
from pytest_gremlins.operators import (
    ArithmeticOperator,
    BooleanOperator,
    ComparisonOperator,
    GremlinOperator,
    OperatorRegistry,
)

# Wrong
from pytest_gremlins.operators import ArithmeticOperator, BooleanOperator, ComparisonOperator
```

### Pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
      - id: check-merge-conflict
      - id: debug-statements

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.6
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.7.1
    hooks:
      - id: mypy
        additional_dependencies: [pytest]
        args: [--strict]

  - repo: https://github.com/commitizen-tools/commitizen
    rev: v3.13.0
    hooks:
      - id: commitizen
        stages: [commit-msg]
```

---

## Testing Strategy

### Test Categories (pytest-test-categories)

We dogfood [pytest-test-categories](https://github.com/mikelane/pytest-test-categories) from day one:

| Category   | Characteristics                                         | Timeout | When to Run          |
| ---------- | ------------------------------------------------------- | ------- | -------------------- |
| **Small**  | Pure functions, no I/O, no network, mocked dependencies | < 100ms | Always, every commit |
| **Medium** | Database, filesystem, multiple components               | < 10s   | PR checks, pre-merge |
| **Large**  | End-to-end, real external services, full system         | < 60s   | Nightly, release     |

### Test File Organization

```text
tests/
├── conftest.py              # Shared fixtures
├── small/
│   └── pytest_gremlins/
│       ├── operators/
│       │   ├── test_comparison.py
│       │   ├── test_arithmetic.py
│       │   └── test_boolean.py
│       ├── instrumentation/
│       │   ├── test_transformer.py
│       │   └── test_switcher.py
│       └── ...
├── medium/
│   └── pytest_gremlins/
│       ├── test_plugin_integration.py
│       ├── test_coverage_mapping.py
│       └── ...
└── large/
    └── pytest_gremlins/
        ├── test_real_project.py
        └── test_cli_workflow.py
```

### Test Naming

**Do NOT use "should" in test names.** Use declarative statements:

```python
# WRONG - "should" is always true whether or not it passes
def test_comparison_operator_should_return_mutations():
    ...

# CORRECT - Statement that can be falsified
def test_comparison_operator_returns_mutations_for_less_than():
    ...

def test_comparison_operator_returns_empty_list_for_non_comparison_node():
    ...
```

### Test Structure

No branching, loops, or complexity in tests. Use parametrization:

```python
# WRONG - Logic in test
def test_comparison_mutations():
    for op in [ast.Lt, ast.LtE, ast.Gt]:
        node = make_comparison(op)
        result = operator.mutate(node)
        if op == ast.Lt:
            assert len(result) == 2
        else:
            assert len(result) == 3

# CORRECT - Parametrized, no logic
@pytest.mark.parametrize(
    ('input_op', 'expected_mutation_count'),
    [
        (ast.Lt, 2),
        (ast.LtE, 2),
        (ast.Gt, 2),
        (ast.Eq, 1),
        (ast.NotEq, 1),
    ],
)
def test_comparison_operator_mutation_count(input_op, expected_mutation_count):
    node = make_comparison(input_op)
    result = operator.mutate(node)
    assert len(result) == expected_mutation_count
```

### Coverage Requirements

- **Line coverage:** ≥ 90%
- **Branch coverage:** ≥ 85%
- **Mutation score:** ≥ 80% (once we can dogfood)

CI fails if coverage drops below thresholds.

### Running Tests

```bash
# All small tests (fast, always safe)
uv run pytest tests/small -m small

# Small + medium (PR checks)
uv run pytest tests/small tests/medium -m "small or medium"

# All tests including large (nightly/release)
uv run pytest

# Single test file
uv run pytest tests/small/pytest_gremlins/operators/test_comparison.py

# Single test
uv run pytest tests/small/pytest_gremlins/operators/test_comparison.py::test_comparison_operator_returns_mutations

# With coverage
uv run pytest --cov=pytest_gremlins --cov-report=html

# Tox for all Python versions
uv run tox
```

---

## Documentation Requirements

### Documentation Is Code

Documentation has the same lifecycle as code:

- Lives in version control
- Reviewed in PRs
- Tested in CI (doctests, link checking)
- Released with code

### Types of Documentation

1. **README.md** - First impression, quick start, badges
2. **User Guide** - How to use pytest-gremlins
3. **API Reference** - Auto-generated from docstrings
4. **Design Docs** - Architecture decisions (this folder)
5. **Changelog** - Auto-generated by commitizen
6. **Contributing Guide** - How to contribute
7. **Code of Conduct** - Community standards

### Docstrings

All public APIs must have docstrings with:

- One-line summary
- Extended description (if needed)
- Args with types and descriptions
- Returns with type and description
- Raises with exception types
- Examples (as doctests)

```python
def mutate(self, node: ast.Compare) -> list[ast.Compare]:
    """Generate mutated variants of a comparison node.

    Takes an AST Compare node and returns all possible mutations
    based on the comparison operator.

    Args:
        node: An AST Compare node (e.g., `a < b`).

    Returns:
        List of mutated Compare nodes, each representing one gremlin.
        Returns empty list if the node cannot be mutated.

    Raises:
        TypeError: If node is not an ast.Compare instance.

    Examples:
        >>> import ast
        >>> node = ast.parse('a < b', mode='eval').body
        >>> operator = ComparisonOperator()
        >>> mutations = operator.mutate(node)
        >>> len(mutations)
        2

    """
```

### Doctests

**Doctests are mandatory for all public API examples.** They serve dual purpose:

1. Living documentation that's always accurate
2. Additional test coverage

CI runs doctests:

```bash
uv run pytest --doctest-modules src/pytest_gremlins
```

### ReadTheDocs

- Built from Markdown (MkDocs)
- Auto-deployed on merge to main
- API docs generated from docstrings
- Versioned docs for each release

### Documentation Review Checklist

Every PR touching code must address documentation:

- [ ] Docstrings updated for changed functions
- [ ] User guide updated if behavior changes
- [ ] Examples tested (doctests pass)
- [ ] README updated if needed
- [ ] Changelog entry (via conventional commit)

---

## CI/CD Pipeline

### GitHub Actions Workflows

#### On Pull Request

```yaml
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run mypy src

  test:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ['3.11', '3.12', '3.13', '3.14']
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          python-version: ${{ matrix.python-version }}
      - run: uv sync
      - run: uv run pytest tests/small tests/medium --cov=pytest_gremlins
      - uses: codecov/codecov-action@v4

  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run pytest --doctest-modules src/pytest_gremlins
      - run: uv run mkdocs build --strict

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run pip-audit
```

#### On Release Tag

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags: ['v*']

jobs:
  publish-test-pypi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv build
      - run: uv publish --index-url https://test.pypi.org/simple/

  test-install:
    needs: publish-test-pypi
    runs-on: ubuntu-latest
    steps:
      - run: pip install --index-url https://test.pypi.org/simple/ pytest-gremlins
      - run: python -c "import pytest_gremlins; print(pytest_gremlins.__version__)"

  publish-pypi:
    needs: test-install
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv build
      - run: uv publish

  github-release:
    needs: publish-pypi
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: softprops/action-gh-release@v1
        with:
          body_path: CHANGELOG.md
          generate_release_notes: true
```

### Branch Protection (main)

- Require pull request before merging
- Require status checks: lint, typecheck, test, docs, security
- Require linear history
- Do not allow bypassing settings

---

## Release Process

### Version Scheme

SemVer with pre-release identifiers:

- `0.1.0-alpha.1` - Early development, unstable
- `0.1.0-beta.1` - Feature complete, testing
- `0.1.0-rc.1` - Release candidate, final testing
- `0.1.0` - Stable release
- `1.0.0` - MLP (Minimum Loveable Product)

### Release Candidate Process

For **minor and major versions**:

```text
1. Feature complete on main
2. Create RC tag: v0.2.0-rc.1
3. Publish to Test PyPI
4. Independent agent tests in real project
5. Documentation review (thorough!)
6. If issues found:
   - Fix issues
   - Tag v0.2.0-rc.2
   - Repeat from step 3
7. If no issues:
   - Tag v0.2.0
   - Publish to PyPI
   - Create GitHub Release
```

### Release Checklist

Before any release:

- [ ] All tests pass (small, medium, large)
- [ ] Coverage thresholds met
- [ ] Type checking passes (strict)
- [ ] Linting passes
- [ ] Security scan clean
- [ ] Documentation builds without warnings
- [ ] Doctests pass
- [ ] Changelog updated (commitizen)
- [ ] Version bumped correctly
- [ ] README examples work
- [ ] User guide accurate
- [ ] API docs generated

For RC releases, additionally:

- [ ] Independent agent test in real project
- [ ] Documentation review by fresh eyes
- [ ] Breaking changes documented
- [ ] Migration guide if needed

### Commitizen Commands

```bash
# Bump version (determines type from commits)
uv run cz bump

# Bump specific version
uv run cz bump --increment PATCH
uv run cz bump --increment MINOR
uv run cz bump --increment MAJOR

# Create RC
uv run cz bump --prerelease rc

# Generate changelog
uv run cz changelog

# Check commits since last tag
uv run cz check --rev-range HEAD~5..HEAD
```

### MLP Definition

v1.0.0 (Minimum Loveable Product) requires:

1. **Core Features**
   - [ ] Mutation switching architecture working
   - [ ] Coverage-guided test selection
   - [ ] Incremental analysis (caching)
   - [ ] Parallel execution
   - [ ] 5 core operators (comparison, boundary, boolean, arithmetic, return)

2. **Integration**
   - [ ] Native pytest plugin (`pytest --gremlins`)
   - [ ] pytest-test-categories integration
   - [ ] Configuration via pyproject.toml

3. **Reporting**
   - [ ] Console output (summary + details)
   - [ ] HTML report

4. **Documentation**
   - [ ] Complete user guide
   - [ ] API reference
   - [ ] Examples that work
   - [ ] README with quick start

5. **Quality**
   - [ ] All tests passing
   - [ ] 90%+ line coverage
   - [ ] 80%+ mutation score (dogfooded)
   - [ ] Tested on real project (not just ourselves)

---

## Agent Boundaries

### What Agents CAN Do Autonomously

- Create branches and worktrees
- Write tests (TDD - tests first!)
- Write production code (to pass tests)
- Run tests and fix failures
- Create commits (conventional format)
- Create PRs via Graphite
- Respond to review feedback
- Bump patch/rc/alpha/beta versions
- Merge PRs (when all checks pass + reviewer approves + no conflicts)
- Update documentation alongside code

### What Agents CANNOT Do Without Human Approval

- Deviate from agreed roadmap/issue ACs
- Make architectural decisions not in design docs
- Bump minor or major versions
- Create releases to PyPI
- Modify CI/CD pipeline
- Change branch protection rules
- Modify agent guidelines (this document)
- Skip tests or reduce coverage
- Add `# type: ignore` without justification
- Bypass pre-commit hooks

### Agent Suggestions

Agents may **suggest** changes to:

- Architecture
- Roadmap priorities
- New features not in backlog
- Process improvements

But humans decide. Agents implement.

### Validation Requirements

Before creating a PR, agents must:

1. Run all small tests (always)
2. Run medium tests (always, unless > 5 min)
3. Run large tests (if touching integration points)
4. Verify type checking passes
5. Verify linting passes
6. Verify doctests pass
7. Verify documentation builds

If small tests ever become "too slow," something is wrong. Fix it.

---

## References

- [pytest-test-categories](https://github.com/mikelane/pytest-test-categories)
- [dioxide](https://github.com/mikelane/dioxide)
- [Open Source Guides](https://opensource.guide/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Graphite](https://graphite.dev/)
- [Commitizen](https://commitizen-tools.github.io/commitizen/)
