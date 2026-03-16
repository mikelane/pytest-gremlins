# CI/CD Integration

Complete CI/CD configurations for running pytest-gremlins in your pipelines.

!!! tip "Prefer the GitHub Action?"
    If you use GitHub Actions, the easiest way to add mutation testing is the
    [`pytest-gremlins-action`](github-action.md). It handles installation, caching,
    parallelism, and score enforcement in a single step. The manual workflows below
    are for teams that need more control or use a different CI platform.

## How Caching Works in CI

pytest-gremlins uses two cache layers that work together:

**Layer 1: CI platform cache (outer)**

The CI platform stores the entire `.gremlins_cache/` directory between job runs. The cache key
is a hash of your source files, not the commit SHA. When one file changes, the key changes and
the outer cache misses — but `restore-keys` finds the previous warm cache as a fallback.

**Layer 2: IncrementalCache (inner)**

Inside `.gremlins_cache/`, results are keyed per-gremlin by `gremlin_id:source_hash:test_hash`.
When the outer cache is restored, the inner cache hits on unchanged files and misses only on
gremlins in the file you changed.

**Net result:** change one file, re-run only that file's gremlins. Everything else returns from
the inner cache instantly.

### Why `if: always()` on cache save

If the mutation score falls below the configured threshold, the threshold check step fails and
the job exits non-zero. Without explicit handling, CI skips the cache save. The next run starts
cold and re-analyzes everything — even the code that didn't change.

Save the cache with `if: always()` so that a failing score gate preserves the warm cache.
Subsequent runs only re-test what changed.

---

## GitHub Actions

### Goal

Run mutation testing on every PR and block merges if the mutation score drops below a threshold.

### Prerequisites

- GitHub repository with pytest-gremlins installed
- Existing test suite that passes
- `pyproject.toml` with pytest-gremlins configuration

### Steps

1. Create the workflow file at `.github/workflows/mutation.yml`
2. Configure the mutation score threshold in `pyproject.toml`
3. Push changes and verify the workflow runs

### Configuration

Create `.github/workflows/mutation.yml`:

```yaml
name: Mutation Testing

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: mutation-${{ github.ref }}
  cancel-in-progress: true

env:
  FORCE_COLOR: "1"

jobs:
  mutation:
    name: Mutation Testing
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for incremental mode

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Restore gremlins cache
        uses: actions/cache/restore@v4
        with:
          path: .gremlins_cache
          key: ${{ runner.os }}-gremlins-${{ hashFiles('src/**/*.py', 'tests/**/*.py', 'pyproject.toml') }}
          restore-keys: |
            ${{ runner.os }}-gremlins-

      - name: Run mutation testing
        run: |
          pytest --gremlins \
            --gremlin-report=html \
            --gremlin-cache

      - name: Save gremlins cache
        uses: actions/cache/save@v4
        if: always()   # Save even if threshold check fails
        with:
          path: .gremlins_cache
          key: ${{ runner.os }}-gremlins-${{ hashFiles('src/**/*.py', 'tests/**/*.py', 'pyproject.toml') }}

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: mutation-report
          path: gremlin-report.html
          retention-days: 30
```

Note: The restore and save steps use `actions/cache/restore` and `actions/cache/save` separately,
not the combined `actions/cache`. The combined action ties the save to the step's success condition,
which means `if: always()` cannot be applied independently. The split approach lets the save run
regardless of whether the threshold check passed.

The cache key includes `pyproject.toml` because operator configuration lives there — changing which
operators run changes mutation results, so the old cache is invalid.

Add to `pyproject.toml`:

```toml
[tool.pytest-gremlins]
paths = ["src"]

exclude = [
    "**/migrations/*",
    "**/__pycache__/*",
]
```

### Verification

1. Push a commit to trigger the workflow
2. Check the Actions tab for the "Mutation Testing" workflow
3. Verify the mutation report artifact is uploaded
4. On PRs, verify the comment appears with results

### Troubleshooting

#### Workflow times out

Mutation testing can be slow on large codebases. Solutions:

```yaml
# Option 1: Increase timeout
jobs:
  mutation:
    timeout-minutes: 60  # Default is 360

# Option 2: Run only on changed files
- name: Get changed files
  id: changed
  uses: tj-actions/changed-files@v41
  with:
    files: |
      src/**/*.py

- name: Run mutation testing
  if: steps.changed.outputs.any_changed == 'true'
  run: |
    pytest --gremlins ${{ steps.changed.outputs.all_changed_files }}
```

---

## GitLab CI

### Goal

Integrate mutation testing into GitLab CI/CD with stages, artifacts, and merge request integration.

### Prerequisites

- GitLab repository with pytest-gremlins installed
- `.gitlab-ci.yml` exists or will be created
- GitLab Runner available

### Steps

1. Add the mutation testing job to `.gitlab-ci.yml`
2. Configure artifacts and caching
3. Set up merge request integration

### Configuration

Create or update `.gitlab-ci.yml`:

```yaml
stages:
  - test
  - quality
  - mutation

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

.python-setup: &python-setup
  image: python:3.12-slim
  before_script:
    - pip install --upgrade pip
    - pip install -e ".[dev]"

# Run unit tests first
unit-tests:
  <<: *python-setup
  stage: test
  script:
    - pytest tests/ -v --cov=src --cov-report=xml
  coverage: '/TOTAL.*\s+(\d+%)/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

# Run mutation testing
mutation-testing:
  <<: *python-setup
  stage: mutation
  needs: ["unit-tests"]
  script:
    - pytest --gremlins
        --gremlin-report=html
        --gremlin-cache
  cache:
    key:
      files:
        - "**/*.py"       # GitLab hashes the listed files natively
        - pyproject.toml
    paths:
      - .gremlins_cache/
    policy: pull-push     # Restore before job, save after (even on failure)
  artifacts:
    paths:
      - gremlin-report.html
    expire_in: 30 days
    when: always
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Fast mutation check for MRs (subset of operators)
mutation-quick:
  <<: *python-setup
  stage: quality
  script:
    - pytest --gremlins
        --gremlin-operators=comparison,boolean
        --gremlin-cache
  cache:
    key:
      files:
        - "**/*.py"
        - pyproject.toml
    paths:
      - .gremlins_cache/
    policy: pull-push
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: true
```

GitLab's `cache.key.files` accepts a list of files and computes a hash of their contents natively.
This is equivalent to GitHub's `hashFiles()`. Using `policy: pull-push` restores the cache before
the job starts and saves it after the job finishes, including on failure.

Add to `pyproject.toml`:

```toml
[tool.pytest-gremlins]
paths = ["src"]

exclude = [
    "**/migrations/*",
    "**/__pycache__/*",
]
```

### Verification

1. Push changes to trigger the pipeline
2. Check the "mutation-testing" job in the pipeline
3. Download artifacts and verify the HTML report
4. For MRs, verify both quick and full mutation jobs run

### Troubleshooting

#### Job fails with no tests collected

Ensure pytest-gremlins is properly installed and configured:

```yaml
before_script:
  - pip install -e ".[dev]"
  - pytest --gremlins --collect-only  # Verify collection
```

---

## CircleCI

### Goal

Run mutation testing in CircleCI with parallelism and workspace sharing.

### Prerequisites

- CircleCI project connected to your repository
- Existing CircleCI configuration
- pytest-gremlins installed in your project

### Steps

1. Create or update `.circleci/config.yml`
2. Configure caching and workspaces
3. Set up parallelism for faster runs

### Configuration

CircleCI's `checksum` command accepts only a single file path — globs are not supported. To hash
multiple source files, generate a combined hash file first and pass that to `checksum`.

Create `.circleci/config.yml`:

```yaml
version: 2.1

orbs:
  python: circleci/python@2.1

executors:
  python-executor:
    docker:
      - image: cimg/python:3.12

commands:
  setup-deps:
    description: Install dependencies with caching
    steps:
      - python/install-packages:
          pkg-manager: pip
          pip-dependency-file: pyproject.toml
          args: -e ".[dev]"

  generate-cache-key:
    description: Hash all source and config files into a single file
    steps:
      - run:
          name: Generate gremlins cache key
          command: |
            find src tests -name '*.py' | sort | xargs md5sum > /tmp/gremlins-sources.txt
            md5sum pyproject.toml >> /tmp/gremlins-sources.txt

  restore-gremlin-cache:
    description: Restore mutation testing cache
    steps:
      - restore_cache:
          keys:
            - gremlin-v1-{{ checksum "/tmp/gremlins-sources.txt" }}
            - gremlin-v1-

  save-gremlin-cache:
    description: Save mutation testing cache
    steps:
      - save_cache:
          key: gremlin-v1-{{ checksum "/tmp/gremlins-sources.txt" }}
          paths:
            - .gremlins_cache

jobs:
  test:
    executor: python-executor
    steps:
      - checkout
      - setup-deps
      - run:
          name: Run tests
          command: pytest tests/ -v --cov=src

  mutation-quick:
    executor: python-executor
    steps:
      - checkout
      - setup-deps
      - generate-cache-key
      - restore-gremlin-cache
      - run:
          name: Quick mutation check
          command: |
            pytest --gremlins \
              --gremlin-operators=comparison,boolean \
              --gremlin-cache
      - save-gremlin-cache

  mutation-full:
    executor: python-executor
    parallelism: 4
    steps:
      - checkout
      - setup-deps
      - generate-cache-key
      - restore-gremlin-cache
      - run:
          name: Split mutation testing
          command: |
            FILES=$(find src -name "*.py" | circleci tests split)
            pytest --gremlins \
              --gremlin-targets=$FILES \
              --gremlin-report=html \
              --gremlin-cache
      - save-gremlin-cache
      - store_artifacts:
          path: gremlin-report.html
          destination: mutation-report.html

workflows:
  version: 2
  test-and-mutate:
    jobs:
      - test
      - mutation-quick:
          requires:
            - test
          filters:
            branches:
              ignore: main
      - mutation-full:
          requires:
            - test
          filters:
            branches:
              only: main

  nightly-mutation:
    triggers:
      - schedule:
          cron: "0 2 * * *"
          filters:
            branches:
              only: main
    jobs:
      - test
      - mutation-full:
          requires:
            - test
```

Note: CircleCI does not have a `when: always` equivalent on `save_cache`. The cache is saved
after the final step in the job. If the mutation step exits non-zero (threshold failure), CircleCI
marks the job failed but still executes subsequent steps — so `save-gremlin-cache` runs regardless.
Ensure the cache save step comes after the mutation run step, not before.

Add to `pyproject.toml`:

```toml
[tool.pytest-gremlins]
paths = ["src"]

exclude = [
    "**/migrations/*",
    "**/__pycache__/*",
]
```

### Verification

1. Push to a branch to trigger the quick mutation check
2. Merge to main to trigger the full mutation testing
3. Check the Artifacts tab for the HTML report
4. Verify the nightly job runs at 2 AM UTC

### Troubleshooting

#### Parallelism not speeding up runs

Ensure files are split correctly:

```yaml
- run:
    name: Debug split
    command: |
      find src -name "*.py" | circleci tests split | tee /tmp/split.txt
      echo "This worker will test: $(wc -l < /tmp/split.txt) files"
```

---

## Dagger

### Goal

Run mutation testing in a Dagger pipeline with automatic cross-run cache persistence.

### Prerequisites

- Dagger CLI installed
- Python project with pytest-gremlins installed
- `dagger` Python SDK installed

### How Dagger Caching Works

Dagger's `dag.cache_volume()` creates a named volume that persists across pipeline runs on the
same host (local or CI runner). No key management is needed — Dagger handles cache identity by
volume name. The inner IncrementalCache still handles per-gremlin invalidation inside the volume.

### Configuration

Create `dagger/src/main/__init__.py`:

```python
import dagger
from dagger import dag, function, object_type


@object_type
class GremlinsCI:
    @function
    async def mutation_test(self, source: dagger.Directory) -> str:
        gremlins_cache = dag.cache_volume("gremlins-cache")

        return await (
            dag.container()
            .from_("python:3.12-slim")
            .with_mounted_directory("/src", source)
            .with_mounted_cache("/src/.gremlins_cache", gremlins_cache)
            .with_workdir("/src")
            .with_exec(["pip", "install", "-e", ".[dev]"])
            .with_exec([
                "pytest", "--gremlins",
                "--gremlin-cache",
                "--gremlin-report=html",
            ])
            .stdout()
        )
```

Run it with:

```bash
dagger call mutation-test --source=.
```

The `gremlins-cache` volume persists between calls. The first run populates it; subsequent runs
restore it and let the inner IncrementalCache skip unchanged gremlins.

### Verification

1. Run `dagger call mutation-test --source=.` twice
2. The second run completes faster — the inner cache hits on unchanged gremlins
3. Modify a source file and run again — only that file's gremlins re-run

---

## Generic CI Principles

### Goal

Apply mutation testing best practices to any CI system.

### Key Principles

1. **Cache the mutation results**
   - pytest-gremlins caches results in `.gremlins_cache/`
   - Key cache by source and test file hashes, not commit SHA
   - Use `restore-keys` prefix fallback so a file change gets a warm partial cache
   - Save the cache with `if: always()` (or equivalent) — threshold failures must not discard it

2. **Use incremental caching**
   - Use `--gremlin-cache` to skip unchanged code
   - Full runs only on main branch or nightly

3. **Fail fast on PRs**
   - Use `--gremlin-operators=comparison,boolean` for quick feedback
   - Run full suite on main branch

4. **Store reports as artifacts**
   - Always generate HTML reports for debugging with `--gremlin-report=html`

### Recommended Configuration

```toml
# pyproject.toml
[tool.pytest-gremlins]
paths = ["src"]

# Exclude generated and test code
exclude = [
    "**/migrations/*",
    "**/test_*",
    "**/__pycache__/*",
    "**/conftest.py",
]
```
