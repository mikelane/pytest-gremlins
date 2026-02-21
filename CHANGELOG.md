# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.3.0b2 (2026-02-21)

### Fix

- use Path for sources.json in WorkerPool to fix Windows path separators (#185)

## v1.3.0b1 (2026-02-21)

### Fix

- make --cov + --gremlins produce real coverage output (#180) (#184)
- revert xdist -n integration; error explicitly on --gremlins + -n conflict (#179) (#183)

## v1.3.0b0 (2026-02-20)

### Feat

- integrate pytest-xdist -n flag for parallel mutation execution (#130) (#175)

### Fix

- suppress addopts and coverage in mutation subprocesses (#128)

## v1.2.0 (2026-02-15)

### Feat

- auto-discover source paths from setuptools metadata (#123)

### Fix

- migrate from optional-dependencies to dependency-groups (PEP 735) (#121)
- display all mutation outcome categories in reports (#115) (#120)
- commit .secrets.baseline to fix pre-commit hook blocking (#118)

## v1.1.0 (2026-02-12)

### Feat

- Add export to Stryker Dashboard and SonarQube (#110)

### Fix

- sync __init__.py version with pyproject.toml
- prevent pytest-cov from hijacking coverage subprocess (#114)
- don't count pytest collection/import errors as zapped (#106)
- make gremlin IDs globally unique across files (#90)
- boolean mutations in class defaults falsely survive (#91)
- **docs**: add mylib to spell check dictionary
- **docs**: fix markdown linting issues across all documentation (#81)

## v1.0.0 (2026-01-26)

First stable release of pytest-gremlins with complete mutation testing capabilities.

### Features

- **End-to-end plugin integration** - Full pytest plugin with `--gremlins` flag (#12)
- **Import hooks for mutation switching** - Toggle mutations via environment variable without file I/O (#15)
- **Coverage-guided test selection** - Only run tests that cover mutated code (#17)
- **Incremental analysis cache** - Skip unchanged code/tests on subsequent runs (#21)
- **HTML report generation** - Detailed mutation reports via `--gremlin-report=html` (#28)
- **pyproject.toml configuration** - Configure operators, paths, and thresholds (#29)
- **Parallel execution** - Distribute gremlins across CPU cores with `--gremlin-parallel` (#30)
- **Batch execution mode** - Reduce subprocess overhead with `--gremlin-batch` (#55)
- **Prioritized test selection** - Run most likely-to-kill tests first (#57)
- **Worker pool optimization** - Configurable process start method and warmup (#58)
- **Continuous benchmark CI** - Automated performance regression detection (#59)

### Performance

Benchmarked against mutmut (Python 3.12, Docker):

| Mode                    | vs mutmut                           |
| ----------------------- | ----------------------------------- |
| Sequential              | 0.84x (16% slower, more operators)  |
| Parallel                | **3.73x faster**                    |
| Full (parallel + cache) | **13.82x faster**                   |

### Documentation

- Performance benchmark section in README
- Sequential mode profiling report (#54)
- Docker-based benchmark tooling for reproducible comparisons

### Fixes

- Incremental cache batch writes and key collision fix (#56)
- YAML parsing error in release workflow (#19)

## v0.1.1 (2026-01-21)

### Fix

- **deps**: upgrade packages with security vulnerabilities
- **lint**: add noqa for pytest import in tests/conftest.py
- **tests**: move marker hook to root conftest.py
- **ci**: fix Windows PowerShell and doctest markers
- **tests**: rename coverage dir to avoid conflict with coverage.py
- **tests**: use tryfirst hook to add markers before pytest-test-categories
- **ci**: ignore pytest-test-categories size marker warning
- **ci**: use --extra dev for optional-dependencies format

## v0.1.0 (2026-01-21)

### Feat

- implement coverage-guided test selection (#10)
- Add reporting system for mutation testing results (#9)
- implement mutation operator system (#8)
- implement mutation switching architecture (#7)
- initial project scaffolding
