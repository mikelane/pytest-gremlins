# CI/CD Integration

Complete CI/CD configurations for running pytest-gremlins in your pipelines.

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

      - name: Restore mutation cache
        uses: actions/cache@v4
        with:
          path: .gremlins_cache
          key: gremlins-${{ runner.os }}-${{ hashFiles('src/**/*.py', 'tests/**/*.py') }}
          restore-keys: |
            gremlins-${{ runner.os }}-

      - name: Run mutation testing
        run: |
          pytest --gremlins \
            --gremlin-report=html \
            --gremlin-cache

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: mutation-report
          path: gremlin-report.html
          retention-days: 30
```

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

#### Cache not restoring properly

Ensure the cache key includes all relevant files:

```yaml
key: gremlins-${{ hashFiles('src/**/*.py', 'tests/**/*.py', 'pyproject.toml') }}
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

cache:
  key: "${CI_COMMIT_REF_SLUG}"
  paths:
    - .cache/pip
    - .gremlins_cache

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
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  allow_failure: true
```

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

#### Cache not working across pipelines

GitLab caches are branch-specific by default. For shared cache:

```yaml
cache:
  key: "gremlins-global"
  paths:
    - .gremlins_cache
  policy: pull-push
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

  restore-gremlin-cache:
    description: Restore mutation testing cache
    steps:
      - restore_cache:
          keys:
            - gremlin-v1-{{ checksum "src/**/*.py" }}-{{ checksum "tests/**/*.py" }}
            - gremlin-v1-

  save-gremlin-cache:
    description: Save mutation testing cache
    steps:
      - save_cache:
          key: gremlin-v1-{{ checksum "src/**/*.py" }}-{{ checksum "tests/**/*.py" }}
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
      - restore-gremlin-cache
      - run:
          name: Split mutation testing
          command: |
            # Get list of source files and split across workers
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
      echo "This worker will test: $(cat /tmp/split.txt | wc -l) files"
```

#### Cache key too long

CircleCI has a 900-character limit for cache keys. Simplify:

```yaml
- restore_cache:
    keys:
      - gremlin-v1-{{ .Branch }}-{{ .Revision }}
      - gremlin-v1-{{ .Branch }}-
      - gremlin-v1-
```

---

## Generic CI Principles

### Goal

Apply mutation testing best practices to any CI system.

### Key Principles

1. **Cache the mutation results**
   - pytest-gremlins caches results in `.gremlins_cache/`
   - Key cache by source and test file hashes
   - Restore cache before running, save after

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
