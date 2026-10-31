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
git worktree add .worktrees/feature-xyz -b feature/xyz

# 2. Navigate to worktree
cd .worktrees/feature-xyz

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
git worktree remove .worktrees/feature-xyz
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

# Create worktree for feature (always inside .worktrees/)
git worktree add .worktrees/{branch-name} -b {branch-name}

# Remove when done
git worktree remove .worktrees/{branch-name}
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
│       ├── config.py           # Configuration loading
│       ├── plugin.py           # pytest plugin hooks
│       ├── operators/
│       │   ├── __init__.py
│       │   ├── protocol.py     # GremlinOperator protocol
│       │   ├── registry.py     # OperatorRegistry
│       │   ├── comparison.py
│       │   ├── arithmetic.py
│       │   ├── boolean.py
│       │   ├── boundary.py
│       │   └── return_value.py
│       ├── instrumentation/
│       │   ├── __init__.py
│       │   ├── gremlin.py      # Gremlin dataclass
│       │   ├── transformer.py  # AST transformation
│       │   ├── switcher.py     # Mutation switching logic
│       │   ├── finder.py       # Mutation point finder
│       │   └── pragma.py       # Pardon pragma parsing
│       ├── coverage/
│       │   ├── __init__.py
│       │   ├── mapper.py       # Coverage-guided selection
│       │   ├── collector.py    # Coverage data collection
│       │   ├── context_plugin.py # Coverage.py dynamic context
│       │   ├── selector.py     # Test selection
│       │   └── prioritized_selector.py
│       ├── cache/
│       │   ├── __init__.py
│       │   ├── hasher.py       # Content hashing
│       │   ├── store.py        # SQLite result cache
│       │   └── incremental.py  # Cache coordinator
│       ├── parallel/
│       │   ├── __init__.py
│       │   ├── pool.py         # Worker pool
│       │   ├── batch_executor.py
│       │   ├── aggregator.py
│       │   └── distribution.py
│       └── reporting/
│           ├── __init__.py
│           ├── results.py      # GremlinResult dataclass
│           ├── score.py        # MutationScore
│           ├── console.py
│           ├── html.py
│           ├── json_reporter.py
│           └── history.py      # Run history tracking
├── tests/
│   ├── conftest.py
│   ├── benchmark/              # Benchmark tests
│   ├── cache/                  # Cache domain tests
│   ├── config/                 # Config domain tests
│   ├── coverage_module/        # Coverage domain tests
│   ├── instrumentation/        # Instrumentation domain tests
│   ├── operators/              # Operator domain tests
│   ├── parallel/               # Parallel domain tests
│   ├── plugin/                 # Plugin integration tests
│   └── reporting/              # Reporting domain tests
├── features/                   # Gherkin scenarios
│   └── ...
├── docs/
│   ├── design/
│   │   ├── NORTH_STAR.md
│   │   ├── OPERATORS.md
│   │   ├── AGENT_GUIDELINES.md
│   │   └── XDIST_INTEGRATION.md
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

Ruff and mypy run from the uv environment (`uv run --frozen`), so `uv.lock` is the single source of
truth for their versions. There are no `ruff-pre-commit` or `mirrors-mypy` entries. This is an excerpt;
the full config is `.pre-commit-config.yaml`.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
        args: [--unsafe]
      - id: check-toml
      - id: debug-statements

  - repo: local
    hooks:
      - id: ruff-check-commit
        name: ruff check (staged files)
        entry: uv run --frozen ruff check --force-exclude --fix --exit-non-zero-on-fix
        language: system
        types_or: [python, pyi, jupyter]
        require_serial: true
        stages: [pre-commit]
      - id: ruff-format-commit
        name: ruff format (staged files)
        entry: uv run --frozen ruff format --force-exclude
        language: system
        types_or: [python, pyi, jupyter]
        require_serial: true
        stages: [pre-commit]
      - id: mypy-commit
        name: mypy (strict, commit)
        entry: uv run --frozen mypy src/pytest_gremlins
        language: system
        files: ^src/
        types_or: [python, pyi]
        pass_filenames: false
        stages: [pre-commit]

  - repo: https://github.com/commitizen-tools/commitizen
    rev: v4.13.7
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

Tests are organized by domain module, not by test size. Test size categories
(small, medium, large) are assigned via pytest markers, not directory nesting:

```text
tests/
├── conftest.py              # Shared fixtures
├── benchmark/               # Benchmark tests
├── cache/                   # Cache domain tests
├── config/                  # Config domain tests
├── coverage_module/         # Coverage domain tests
├── instrumentation/         # Instrumentation domain tests
├── operators/               # Operator domain tests
├── parallel/                # Parallel domain tests
├── plugin/                  # Plugin integration tests
└── reporting/               # Reporting domain tests
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
uv run pytest tests -m small

# Small + medium (PR checks)
uv run pytest tests -m "small or medium"

# All tests including large (nightly/release)
uv run pytest

# Single test file
uv run pytest tests/operators/test_comparison.py

# Single test
uv run pytest tests/operators/test_comparison.py::test_comparison_operator_returns_mutations

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

### Docs Freshness (Review Rule)

A PR whose diff changes user-facing behavior and touches nothing under `docs/` is a review finding of
**MEDIUM** severity, unless the PR description says why no docs change is needed. User-facing behavior means:
options or defaults, verdicts, exit codes, console, report or warning output, or what gets mutated. The PR
template asks the author to state which case applies in its required Docs section. Reviewers, including
pr-reviewer agents, check that section against the diff.

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
      - run: uv run pytest tests -m "small or medium" --cov=pytest_gremlins
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

### Philosophy: Release Often

We follow the FastAPI/Ruff model -- release stable versions frequently. Every few
merged PRs, cut a release. No alpha/beta/RC ceremony for routine releases.

### How to Release (Local)

**Prerequisites:** Be on `main` with a clean working tree. The script checks both and
refuses to continue if either is wrong.

```bash
# Auto-detect bump type from conventional commits (recommended)
./scripts/release.sh

# Or force a specific bump type
./scripts/release.sh --patch
./scripts/release.sh --minor
./scripts/release.sh --major
```

**What happens:** The script uses commitizen to bump the version in `pyproject.toml` and
`src/pytest_gremlins/__init__.py`, regenerate `CHANGELOG.md`, create a version commit and
tag, and push both to origin. The tag push triggers the `release.yml` pipeline, which runs
tests, publishes to PyPI, and creates a GitHub Release.

### How to Release (GitHub Actions)

The `cut-release.yml` workflow lets you release without a local checkout:

1. Go to **Actions > Cut Release > Run workflow**
2. Select the bump type (`auto`, `patch`, `minor`, `major`)
3. Click **Run workflow**

The workflow bumps the version, pushes the commit and tag, and triggers `release.yml`.
The job summary shows which commits are included and links to the release pipeline.

**Prerequisites:** A GitHub fine-grained PAT with **Repository permissions > Contents:
Read and write** must be stored as the `RELEASE_PAT` repository secret. Set a 90-day
expiry and renew before it lapses. Without this secret, the workflow will fail at the
push step because the default `GITHUB_TOKEN` cannot push commits that trigger other
workflows.

### Changelog Format and the Docs Gate

The changelog is written by hand in the CHANGELOG PR that precedes the release.

Every release entry in `CHANGELOG.md` is gated. Each bullet under `### Upgrade notes`, `### Feature`
and `### Fix` must end with either a docs reference or an exemption:

- A docs reference is a link to the page, with the anchor when the change has a section:
  `[docs](https://pytest-gremlins.readthedocs.io/en/latest/<page>/#<anchor>)`. A path relative to `docs/`
  (`guide/configuration.md#<anchor>`) also works. A bullet may carry several. The page and the anchor must exist
  in the built site. A link to the home page (`index.md`, `.`, or the bare `/en/latest/`) does not count.
- An exemption is `(no docs: <reason>)`, for example a bug fix that only restores documented behavior. The
  reason must not be empty, and it is reviewed in the changelog PR.
- `### Internal` and `### Documentation` bullets are not gated.
- Use only these `###` headings: `Upgrade notes`, `Feature`, `Fix`, `Internal` and `Documentation`, spelled
  exactly like that. Any other heading (`Feat`, `Fixes`, `Upgrade Notes`) fails the check, and so does a bullet
  that sits under no `###` heading.
- Every list item is a bullet: `-`, `*`, `+`, `1.` and `1)` markers all count, and a nested sub-bullet needs its
  own reference or exemption. A reference or exemption inside an HTML comment, a code span, an image
  (`![x](...)`) or an escaped link (`\[x](...)`) does not count.
- Under `### Upgrade notes`, `### Feature` and `### Fix` the only accepted lines are blank lines, list items and
  their indented continuation lines. Prose paragraphs, `•` pseudo-bullets, block quotes (`>`), code fences,
  HTML comments (`<!--` anywhere, even in a code span), other headings (`####`, indented or tab-indented `#`),
  thematic breaks and underlined headings fail the check, and the failure names the line. Put prose before the
  first `###` heading.
- The whole selected entry, including the preamble, `### Internal` and `### Documentation`, is read as a strict
  format. A visible line must be prose, a list line, a version heading or one of the five `###` headings. Every
  other line that starts with `#` fails, including `#Feature`, `####Detail`, `###Feature`, `#Feature ###`,
  `#\tFeature` and `##v2.0.0`. An issue-number line is the one exception: a `#720)` line indented by two spaces is
  accepted only while a list item is open directly above it, and a standalone `#720)` indented by four spaces
  renders as a heading and fails.
- Every thematic-break and underline-style heading line fails anywhere in the entry: `=`, `===`, `-`, `--`, `---`,
  `***`, `___`, `* * *` and `- - -`. The check does not guess from the previous line, so a delimiter under `A | B`
  or `<em>Feature</em>` fails too. These rules apply again after list and `>` prefixes are stripped, which catches
  `> #Feature`, `- #### Detail`, `> <em>Feature</em>` + `> ---` and `- ---`.
- A raw `<h1>`-`<h6>` tag fails wherever it is visible, in any case and with attributes (`<H2 class="x">`), inside
  a block quote or a list item included. A tag written as a code span (`<h1>` in backticks) stays literal text.
- A code fence or HTML comment is allowed in `### Internal`, `### Documentation` and before the first `###`
  heading, but it must be closed and must not hide a `###` heading. An unclosed one fails the check. A fence must
  open at the outer level: a fence opener inside a list item or block quote fails with an explicit message. Lines
  inside a closed outer fence or comment are literal, so a quoted or listed fence opener written there is left alone.
- A second visible `##` heading for the version being released fails wherever it appears, including `##v2.0.0`,
  an indented, quoted or listed copy, and one with a date or closing hashes.
- A `###` heading may have up to 3 leading spaces, a tab after the `###` and a closing `###`
  (`### Internal ###`). It is read like any other heading, so it must be one of the five names above.

Put a long link on its own indented line so the bullet still passes markdownlint:

```markdown
## vX.Y.Z (YYYY-MM-DD)

**One sentence on what changes for users.**

### Upgrade notes

- **The default batch size is now 10.** Runs with many small tests get faster. Pass `--gremlin-batch-size 1` to
  keep the old behavior. (#701)
  [docs](https://pytest-gremlins.readthedocs.io/en/latest/guide/configuration/#batch-execution)

### Fix

- **A crash on an oversized `PYTHONOPTIMIZE` value.** (#709)
  (no docs: fixes a crash and changes no documented behavior)

### Internal

- Bumped a dev dependency. (#715)
```

`scripts/check_release_docs.py` enforces this. It takes the version and a `mkdocs build --strict` output
directory (`uv run mkdocs build --strict --site-dir site`, then
`uv run python scripts/check_release_docs.py X.Y.Z --site-dir site`). It exits 1 and names the bullet or link when
the entry is missing, a bullet has neither a reference nor a non-empty exemption, or a reference points to a page
or anchor that is not in the site. It exits 2 when it could not run. It runs in three places:

1. `ci.yml`, whenever a PR changes `CHANGELOG.md`, against the topmost entry, so the changelog PR fails
   first. `--newest` picks that entry by the same heading rule the check uses, where the `v` is optional.
2. `cut-release.yml`, before the tag is created, against the version `cz bump --get-next` reports.
3. The `verify-tag` job of `release.yml`, against the tagged commit. Every other job in that workflow depends on
   `verify-tag`, so a failing check blocks the publish however the release was started.

**There is no bypass.** No workflow input, environment variable or flag skips the check, and `skip_test_pypi` does
not affect it. To ship a change without docs, write a `(no docs: <reason>)` exemption in the changelog PR, where the
reason is public and gets reviewed.

**Cache markers at release time.** `scripts/check_cache_kept.py` compares the guarded code (the cache-version guard's
own file set) at the newest `v*` tag reachable from the release, not counting the tag being released, with the code
being released. If it changed and neither `CACHE_VERSION` nor `RUNNER_FIDELITY_VERSION` differs from its value at that
tag, the release fails unless the entry has a `(cache kept: <reason>)` line with a non-empty reason. Put the line in the
entry's prose before its first `###` heading; it is accepted nowhere else, because the docs gate allows only list items
under the gated headings. The reason is public and is reviewed in the changelog PR. It runs in the same three places as
the docs gate (`ci.yml` on a `CHANGELOG.md` change with `--newest`, `cut-release.yml`, and `verify-tag`), exits 1 naming
the changed files, exits 2 when it could not run, and has no bypass. With `--newest`, a topmost entry that is already
tagged passes; the changes after it are checked once the next entry is added.

### When to Release

- After merging 3-5 PRs (routine)
- After any security fix (immediately)
- After a significant bug fix users are waiting on

### When to Pause and Think First

- **Breaking changes:** Write migration notes in `CHANGELOG.md` before bumping. Users
  need to know what breaks and how to update their code.
- **Major version bumps:** Discuss with the team first. A major bump signals a
  compatibility contract change and should not be accidental.

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
- Bump patch versions
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
