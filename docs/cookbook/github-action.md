# GitHub Action

The [`pytest-gremlins-action`](https://github.com/marketplace/actions/pytest-gremlins)
is a composite GitHub Action that runs mutation testing, ratchets the mutation score so it
can only go up, comments on pull requests, and builds a badge URL. This page describes
`mikelane/pytest-gremlins-action@v1`.

The action does not check out your code, set up Python, or install your project. Run
`actions/checkout`, `actions/setup-python` and your own install step before it.

## What It Does

1. Restores a cache (see [Caching](#caching) for a known problem)
2. Runs `pip install "pytest-gremlins>=1.5.1"`, unless `skip-install` is `'true'`
3. Runs `pytest --gremlins --gremlin-report=json`, plus flags built from the inputs
   (`--gremlin-parallel`, `--gremlin-workers=N`, `--gremlin-cache`, `--gremlin-targets=...`
   and `extra-args`), prefixed with `command-prefix` if you set one
4. Reads the summary from `coverage/gremlins/gremlins.json`
5. Compares `.summary.percentage` to the score stored in the ratchet file, and fails the
   step if the score is lower (see [Score Ratchet](#score-ratchet))
6. On `pull_request` events, posts or updates a PR comment with the results, if
   `pr-comment` is `'true'`
7. Builds a Shields.io badge URL for the score

## Action Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `python-version` | `'3.12'` | Declared, but no step of the action reads it. Use `actions/setup-python` to choose the Python version. |
| `parallel` | `'true'` | Adds `--gremlin-parallel`. |
| `workers` | `''` | Adds `--gremlin-workers=N`. Must be a positive integer. Empty means one worker per CPU core. |
| `cache` | `'true'` | Adds `--gremlin-cache` and turns on the action's cache step. |
| `targets` | `''` | Adds `--gremlin-targets=<value>` (comma-separated source paths to mutate). |
| `extra-args` | `''` | Extra arguments appended to the pytest command, split on whitespace. |
| `ratchet-file` | `'.gremlins-score'` | File that stores the score threshold for the ratchet. |
| `command-prefix` | `''` | Command to put in front of `pytest`, for example `uv run`, `poetry run` or `pdm run`. |
| `skip-install` | `'false'` | Set to `'true'` to skip `pip install pytest-gremlins` when your environment already provides it. |
| `pr-comment` | `'true'` | Post the mutation report as a PR comment on `pull_request` events. |

## Action Outputs

| Output | Description |
|--------|-------------|
| `score` | Mutation score percentage (`.summary.percentage` from `gremlins.json`) |
| `zapped` | Number of zapped gremlins |
| `survived` | Number of surviving gremlins |
| `timeout` | Number of gremlins caught by a timeout |
| `total` | Total number of gremlins |
| `pardoned` | Number of pardoned gremlins |
| `passed` | `'true'` if the score is at or above the ratchet threshold |
| `badge-url` | Shields.io badge URL for the score |

If `gremlins.json` is missing, the action warns, reports every count as `0` and the score as
`100`, and goes on.

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
    permissions:
      contents: write        # the ratchet commits .gremlins-score
      pull-requests: write   # the PR comment
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install project
        run: pip install -e ".[dev]"

      - uses: mikelane/pytest-gremlins-action@v1
        id: gremlins

      - name: Show score
        run: echo "Mutation score: ${{ steps.gremlins.outputs.score }}%"
```

## Full Usage (All Inputs)

```yaml
      - uses: mikelane/pytest-gremlins-action@v1
        with:
          parallel: 'true'
          workers: '4'
          cache: 'true'
          targets: 'src/my_package'
          extra-args: '--gremlin-operators=comparison,boundary'
          ratchet-file: '.gremlins-score'
          command-prefix: ''
          skip-install: 'false'
          pr-comment: 'true'
```

## Score Ratchet

The action reads `.summary.percentage` from `coverage/gremlins/gremlins.json`. That value
is the mutation score, `(zapped + timeout) / (total - pardoned) * 100`; see
[Understanding Mutation Score](../guide/reports.md#understanding-mutation-score). It is not
the `Zapped: N gremlins (X%)` percentage on the console, which is `zapped / total`.

The threshold comes from the file named by `ratchet-file`:

- If the file doesn't exist, the threshold is `0`.
- If the score is below the threshold, the step fails with
  `Mutation score <score>% is below ratchet threshold <threshold>%`.
- If the score is above the threshold, the action writes the new score to the file, commits
  it as `github-actions[bot]` with the message `chore: update mutation score to <score>%`,
  and runs `git push origin HEAD`. The job needs `contents: write` for that push.
- If the score equals the threshold, nothing changes.

There is no input for a fixed threshold. To start from a minimum score, commit a ratchet file
that holds it, for example a `.gremlins-score` file containing `80`.

pytest-gremlins itself doesn't fail the run because gremlins survived. The ratchet is the
only score gate.

## Caching

With `cache: 'true'`, the action passes `--gremlin-cache` and runs `actions/cache@v4` on the
path `.gremlin-cache.db`, keyed on `hashFiles('src/**/*.py', 'tests/**/*.py')`. pytest-gremlins
writes its cache to `.gremlins_cache/`, not `.gremlin-cache.db`, so that step saves nothing and
every run starts cold. This is tracked in
[pytest-gremlins-action#20](https://github.com/mikelane/pytest-gremlins-action/issues/20).

Until that is fixed, the action's cache step doesn't help. To keep the cache between runs,
use the manual workflow in [CI/CD Integration](ci-integration.md#how-caching-works-in-ci),
which restores and saves `.gremlins_cache/` itself.

## PR Comment

On `pull_request` events with `pr-comment: 'true'`, the action posts a comment headed
**Mutation Testing Report**. It shows the score, the ratchet threshold, a count table and up
to 20 surviving gremlins. Later runs update the same comment instead of adding a new one. The
job needs `pull-requests: write`.

## Combining with Other Steps

The action asks only for the JSON report. To get the HTML report too, add it with
`extra-args` and upload the directory as an artifact:

```yaml
      - uses: mikelane/pytest-gremlins-action@v1
        with:
          extra-args: '--gremlin-report=html'

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: mutation-report
          path: coverage/gremlins/
          retention-days: 30
```

## Using with uv

If your project uses [uv](https://github.com/astral-sh/uv), install it, sync your project
(with pytest-gremlins in its dev dependencies), and run pytest through `uv run`:

```yaml
      - uses: astral-sh/setup-uv@v4

      - name: Install project
        run: uv sync

      - uses: mikelane/pytest-gremlins-action@v1
        with:
          command-prefix: 'uv run'
          skip-install: 'true'
```

`skip-install: 'true'` stops the action from running `pip install` outside your uv
environment.

## Manual Workflow Alternative

If you cannot use the action (self-hosted runners, restricted marketplace access, etc.),
see [CI/CD Integration](ci-integration.md) for manual workflow configurations covering
GitHub Actions, GitLab CI, CircleCI, and Dagger.
