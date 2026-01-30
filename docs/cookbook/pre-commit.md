# Pre-commit Hook

Configure pytest-gremlins as a pre-commit hook for fast feedback during development.

## Goal

Run incremental mutation testing on changed files before each commit, catching test quality issues early.

## Prerequisites

- pytest-gremlins installed
- pre-commit installed and initialized
- Existing test suite

## Steps

1. Install pre-commit
2. Create or update `.pre-commit-config.yaml`
3. Configure pytest-gremlins for fast incremental runs
4. Test the hook

## Configuration

### Install pre-commit

```bash
pip install pre-commit
```

Or with uv:

```bash
uv add pre-commit --dev
```

### Create .pre-commit-config.yaml

Create `.pre-commit-config.yaml`:

```yaml
default_language_version:
  python: python3.12

repos:
  # Standard pre-commit hooks
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files

  # Ruff for linting and formatting
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.6
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  # Type checking
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.7.1
    hooks:
      - id: mypy
        additional_dependencies:
          - pytest>=7.0.0
        args: [--strict]
        files: ^src/

  # Run tests on changed files
  - repo: local
    hooks:
      - id: pytest-quick
        name: pytest (quick)
        entry: pytest
        args:
          - tests/
          - -x           # Stop on first failure
          - --tb=short   # Short traceback
          - -q           # Quiet output
        language: system
        pass_filenames: false
        always_run: true
        stages: [pre-commit]

  # Mutation testing on changed files (optional, can be slow)
  - repo: local
    hooks:
      - id: gremlins-quick
        name: gremlins (incremental)
        entry: pytest
        args:
          - --gremlins
          - --gremlin-incremental
          - --gremlin-operators=comparison,boolean  # Fast subset
          - --gremlin-min-score=60                  # Lower threshold for commits
          - -x
          - --tb=short
        language: system
        pass_filenames: false
        stages: [pre-commit]
        # Only run when Python source files change
        files: ^src/.*\.py$

ci:
  # Skip mutation testing in pre-commit.ci (too slow)
  skip: [gremlins-quick, pytest-quick]
```

### pyproject.toml Configuration

Add configuration optimized for pre-commit:

```toml
[tool.pytest-gremlins]
paths = ["src"]
min_score = 80
incremental = true

# Pre-commit runs should be fast
[tool.pytest-gremlins.precommit]
# Use fewer operators for speed
operators = ["comparison", "boolean"]
# Lower threshold for commits (full check in CI)
min_score = 60
# Limit time spent
timeout = 60  # seconds
```

### Install the Hooks

```bash
pre-commit install
```

For commit-msg hooks (if using commitizen):

```bash
pre-commit install --hook-type commit-msg
```

## Running the Hook

### Automatic on Commit

```bash
git add .
git commit -m "feat: add new feature"
# Hooks run automatically
```

### Manual Run

```bash
# Run all hooks on all files
pre-commit run --all-files

# Run just the gremlins hook
pre-commit run gremlins-quick --all-files

# Run on specific files
pre-commit run gremlins-quick --files src/mymodule.py
```

### Skip Hooks When Needed

```bash
# Skip all hooks
git commit --no-verify -m "wip: work in progress"

# Skip specific hook
SKIP=gremlins-quick git commit -m "feat: quick fix"
```

## Verification

1. Make a change to source code:
   ```bash
   echo "# change" >> src/mymodule.py
   ```

2. Stage and commit:
   ```bash
   git add src/mymodule.py
   git commit -m "test: verify pre-commit hook"
   ```

3. Observe the mutation testing output

4. If mutations survive, the commit is blocked:
   ```
   gremlins (incremental)..............................................Failed
   - hook id: gremlins-quick
   - exit code: 1

   Mutation score 45% is below minimum 60%
   ```

## Troubleshooting

**Issue: Hook takes too long**

Optimize for speed by reducing scope:

```yaml
- id: gremlins-quick
  entry: pytest
  args:
    - --gremlins
    - --gremlin-incremental
    - --gremlin-operators=comparison  # Single operator
    - --gremlin-timeout=30            # Hard timeout
    - -x
```

Or skip mutation testing in pre-commit entirely and run in CI:

```yaml
- id: gremlins-quick
  stages: [manual]  # Only run when explicitly called
```

**Issue: "No tests collected" error**

Ensure tests exist and pytest can find them:

```bash
# Debug test collection
pytest --collect-only tests/
```

Check pytest configuration:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

**Issue: Hook doesn't run on file changes**

Check the `files` pattern matches your source files:

```yaml
- id: gremlins-quick
  files: ^src/.*\.py$  # Must match your structure
```

Debug with:

```bash
pre-commit run gremlins-quick --files src/mymodule.py --verbose
```

**Issue: Different results than CI**

Pre-commit uses a subset of operators for speed. CI should run the full suite:

```yaml
# .github/workflows/ci.yml
- name: Full mutation testing
  run: pytest --gremlins --gremlin-min-score=80  # Full operators, higher threshold
```

## Advanced: Staged Files Only

Run mutation testing only on staged Python files:

```yaml
- repo: local
  hooks:
    - id: gremlins-staged
      name: gremlins (staged files)
      entry: bash -c 'pytest --gremlins --gremlin-incremental $(git diff --cached --name-only --diff-filter=AM | grep "\.py$" | grep "^src/" | tr "\n" " ")'
      language: system
      pass_filenames: false
      stages: [pre-commit]
      files: ^src/.*\.py$
```

## Advanced: Different Hooks for Different Stages

```yaml
repos:
  - repo: local
    hooks:
      # Quick check on commit
      - id: gremlins-commit
        name: gremlins (commit)
        entry: pytest
        args:
          - --gremlins
          - --gremlin-incremental
          - --gremlin-operators=comparison
          - --gremlin-min-score=50
          - -x
        language: system
        pass_filenames: false
        stages: [pre-commit]
        files: ^src/.*\.py$

      # Full check before push
      - id: gremlins-push
        name: gremlins (push)
        entry: pytest
        args:
          - --gremlins
          - --gremlin-incremental
          - --gremlin-min-score=70
          - --gremlin-report=console
        language: system
        pass_filenames: false
        stages: [pre-push]
        files: ^src/.*\.py$
```

Install both:

```bash
pre-commit install
pre-commit install --hook-type pre-push
```

## When to Skip Mutation Testing

Skip mutation testing in pre-commit when:

1. **Work in Progress (WIP) commits**: Use `--no-verify` or `SKIP=gremlins-quick`
2. **Documentation-only changes**: The hook should already skip (no Python files)
3. **Urgent hotfixes**: Skip locally, but ensure CI catches issues
4. **Initial development**: Focus on getting tests green first

Best practice: Run full mutation testing in CI, use pre-commit for quick feedback.

## Integration with CI

Ensure CI runs full mutation testing even if pre-commit uses a subset:

```yaml
# .github/workflows/ci.yml
jobs:
  mutation:
    steps:
      - name: Full mutation testing
        run: |
          pytest --gremlins \
            --gremlin-report=html \
            --gremlin-min-score=80  # Higher than pre-commit threshold
```

This catches any mutations that slipped through the faster pre-commit check.
