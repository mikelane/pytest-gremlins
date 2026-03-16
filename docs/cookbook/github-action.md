# GitHub Action

The [`pytest-gremlins-action`](https://github.com/marketplace/actions/pytest-gremlins)
is a composite GitHub Action that installs your project, runs mutation testing, and
enforces a score threshold -- all in one step.

## What It Does

1. Checks out your code and sets up Python
2. Installs your project with the command you specify
3. Runs `pytest --gremlins` with caching and optional parallelism
4. Parses the "Zapped: N gremlins (X%)" line from pytest output
5. Fails the step if the score is below your threshold

## Action Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `threshold` | `80` | Minimum mutation score (%). The step fails if the score is below this value. |
| `parallel` | `'true'` | Run mutation testing with `-n auto` (xdist parallel). |
| `cache` | `'true'` | Enable incremental cache with `--gremlin-cache`. Uses `actions/cache` to persist `.gremlins_cache/` between runs. |
| `python-version` | `'3.x'` | Python version for `actions/setup-python`. |
| `install-command` | `'pip install -e ".[dev]"'` | Command to install the project and its dependencies. |

## Basic Usage

```yaml
name: Mutation Testing

on:
  push:
    branches: [main]
  pull_request:

jobs:
  gremlins:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: mikelane/pytest-gremlins-action@v1
        with:
          threshold: 80
          parallel: 'true'
          cache: 'true'
```

## Full Usage (All Inputs)

```yaml
name: Mutation Testing

on:
  push:
    branches: [main]
  pull_request:

jobs:
  gremlins:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: mikelane/pytest-gremlins-action@v1
        with:
          threshold: 85
          parallel: 'true'
          cache: 'true'
          python-version: '3.12'
          install-command: 'pip install -e ".[dev]"'
```

## How Caching Works

When `cache: 'true'` (the default), the action uses `actions/cache` to persist the
`.gremlins_cache/` directory between workflow runs. The cache key is based on
`hashFiles` over your source files, test files, and `pyproject.toml`. A `restore-keys`
prefix fallback ensures that changing one file still gets a warm partial cache from
the previous run.

The cache is saved with `if: always()` so that a failing score gate does not discard
the warm cache. The next run only re-tests gremlins in the files you changed.

For details on how the two-layer cache works, see
[CI/CD Integration](ci-integration.md#how-caching-works-in-ci).

## Score Gate

The action parses pytest's summary output for the line:

```text
Zapped: 142 gremlins (85%)
```

It extracts the percentage and compares it to your `threshold` input. If the score
is below the threshold, the step exits with code 1 and the workflow fails.

## Combining with Other Steps

Upload the HTML report as an artifact so reviewers can browse it:

```yaml
jobs:
  gremlins:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: mikelane/pytest-gremlins-action@v1
        with:
          threshold: 80

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: mutation-report
          path: coverage/gremlins/
          retention-days: 30
```

## Using with uv

If your project uses [uv](https://github.com/astral-sh/uv) instead of pip, override
the install command:

```yaml
- uses: mikelane/pytest-gremlins-action@v1
  with:
    install-command: 'pip install uv && uv sync'
    threshold: 80
```

## Manual Workflow Alternative

If you cannot use the action (self-hosted runners, restricted marketplace access, etc.),
see [CI/CD Integration](ci-integration.md) for manual workflow configurations covering
GitHub Actions, GitLab CI, CircleCI, and Dagger.
