# Monorepo Setup

Configure pytest-gremlins for multi-package monorepos with selective testing.

## Goal

Run mutation testing on specific packages in a monorepo, only testing code that changed
or belongs to the package being tested.

## Prerequisites

- Monorepo with multiple Python packages
- Shared test infrastructure
- Build tool that supports workspaces (e.g., uv workspaces, pip-tools)

## Repository Structure

This recipe assumes a structure like:

```text
my-monorepo/
├── packages/
│   ├── core/
│   │   ├── src/
│   │   │   └── core/
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── api/
│   │   ├── src/
│   │   │   └── api/
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── cli/
│       ├── src/
│       │   └── cli/
│       ├── tests/
│       └── pyproject.toml
├── pyproject.toml  # Root workspace config
└── .github/
    └── workflows/
        └── mutation.yml
```

## Steps

1. Configure each package with pytest-gremlins
2. Create a root configuration for shared settings
3. Set up CI to run mutation testing per package
4. Configure path-based filtering

## Configuration

### Root Configuration

Create `pyproject.toml` at the repository root:

```toml
[project]
name = "my-monorepo"
version = "0.0.0"
description = "Monorepo root"

[tool.uv.workspace]
members = ["packages/*"]

[tool.pytest-gremlins]
# Shared settings for all packages

exclude = [
    "**/migrations/*",
    "**/__pycache__/*",
    "**/conftest.py",
]

# Default operators (can be overridden per package)
operators = [
    "comparison",
    "arithmetic",
    "boolean",
    "return",
]
```

### Package Configuration

Create `packages/core/pyproject.toml`:

```toml
[project]
name = "core"
version = "1.0.0"
description = "Core library"
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest-gremlins]
# Package-specific paths
paths = ["src/core"]

# Package-specific exclusions
exclude = [
    "src/core/generated/*",
]
```

Create `packages/api/pyproject.toml`:

```toml
[project]
name = "api"
version = "1.0.0"
description = "API service"
dependencies = ["core"]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest-gremlins]
paths = ["src/api"]
```

Create `packages/cli/pyproject.toml`:

```toml
[project]
name = "cli"
version = "1.0.0"
description = "CLI tool"
dependencies = ["core"]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-gremlins>=1.0.0",
]

[tool.pytest-gremlins]
paths = ["src/cli"]

# Skip mutations in argparse setup
exclude = [
    "src/cli/main.py",  # Mostly argparse boilerplate
]
```

### CI Configuration

Create `.github/workflows/mutation.yml`:

```yaml
name: Mutation Testing

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  FORCE_COLOR: "1"

jobs:
  # Detect which packages changed
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      packages: ${{ steps.filter.outputs.changes }}
    steps:
      - uses: actions/checkout@v4

      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            core:
              - 'packages/core/**'
            api:
              - 'packages/api/**'
              - 'packages/core/**'  # API depends on core
            cli:
              - 'packages/cli/**'
              - 'packages/core/**'  # CLI depends on core

  # Run mutation testing for changed packages
  mutation:
    needs: detect-changes
    if: needs.detect-changes.outputs.packages != '[]'
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        package: ${{ fromJson(needs.detect-changes.outputs.packages) }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true

      - name: Install dependencies
        run: |
          cd packages/${{ matrix.package }}
          uv sync --extra dev

      - name: Restore mutation cache
        uses: actions/cache@v4
        with:
          path: packages/${{ matrix.package }}/.gremlins_cache
          key: gremlins-${{ matrix.package }}-${{ hashFiles(format('packages/{0}/src/**/*.py', matrix.package)) }}
          restore-keys: |
            gremlins-${{ matrix.package }}-

      - name: Run mutation testing
        working-directory: packages/${{ matrix.package }}
        run: |
          uv run pytest --gremlins \
            --gremlin-report=html \
            --gremlin-cache

      - name: Upload report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: mutation-report-${{ matrix.package }}
          path: packages/${{ matrix.package }}/gremlin-report.html
          retention-days: 14

  # Summary job
  mutation-summary:
    needs: [detect-changes, mutation]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Check results
        run: |
          if [ "${{ needs.mutation.result }}" == "failure" ]; then
            echo "Mutation testing failed for one or more packages"
            exit 1
          fi
          echo "All mutation tests passed"
```

### Running Locally

Create a script `scripts/mutate.sh`:

```bash
#!/bin/bash
# Run mutation testing for a specific package or all packages

set -e

PACKAGE=${1:-all}

run_mutation() {
    local pkg=$1
    echo "Running mutation testing for $pkg..."
    cd "packages/$pkg"
    uv run pytest --gremlins --gremlin-cache
    cd ../..
}

if [ "$PACKAGE" == "all" ]; then
    for dir in packages/*/; do
        pkg=$(basename "$dir")
        run_mutation "$pkg"
    done
else
    run_mutation "$PACKAGE"
fi
```

Make it executable:

```bash
chmod +x scripts/mutate.sh
```

## Verification

1. Run mutation testing for a single package:

   ```bash
   ./scripts/mutate.sh core
   ```

2. Run for all packages:

   ```bash
   ./scripts/mutate.sh all
   ```

3. Push changes and verify CI runs only for affected packages

4. Check that reports are generated per package

## Troubleshooting

### Tests from one package run against another package's code

Ensure each package has proper pytest configuration:

```toml
# packages/core/pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

And run pytest from the package directory:

```bash
cd packages/core && uv run pytest --gremlins
```

### Shared dependencies not found during mutation testing

Install dependencies in development mode from the root:

```bash
# From repository root
uv sync --all-packages
```

Or explicitly install dependencies:

```bash
cd packages/api
uv sync --extra dev
uv pip install -e ../core  # Install core as editable
```

### Cache not shared between packages

If packages share code (e.g., API uses Core), you might want shared cache:

```yaml
# In CI workflow
- name: Restore shared cache
  uses: actions/cache@v4
  with:
    path: .gremlins_cache
    key: gremlins-monorepo-${{ hashFiles('packages/*/src/**/*.py') }}
```

## Advanced: Dependency-Aware Testing

For monorepos where changes to core packages should trigger mutation testing in dependent packages:

```yaml
# .github/workflows/mutation.yml
jobs:
  detect-changes:
    # ... (same as above)

  build-dependency-graph:
    runs-on: ubuntu-latest
    outputs:
      affected: ${{ steps.deps.outputs.affected }}
    steps:
      - uses: actions/checkout@v4

      - name: Compute affected packages
        id: deps
        run: |
          # Simple dependency resolution
          AFFECTED="[]"

          # If core changed, all packages are affected
          if echo "${{ needs.detect-changes.outputs.packages }}" | grep -q "core"; then
            AFFECTED='["core", "api", "cli"]'
          # If only api changed
          elif echo "${{ needs.detect-changes.outputs.packages }}" | grep -q "api"; then
            AFFECTED='["api"]'
          # If only cli changed
          elif echo "${{ needs.detect-changes.outputs.packages }}" | grep -q "cli"; then
            AFFECTED='["cli"]'
          fi

          echo "affected=$AFFECTED" >> $GITHUB_OUTPUT
```
