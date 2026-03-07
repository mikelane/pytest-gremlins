# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.5.0b2 (2026-03-07)

### Feat

- **config**: add --gremlin-max-pardons-pct threshold enforcement (#268)
- **pragma**: inline suppression pragma for equivalent/untestable mutations (#261) (#266)

## v1.5.0b1 (2026-03-07)

### Fix

- **a11y**: resolve WCAG violations in HTML report (#255) (#264)
- **html**: fix light mode contrast and expand-all overflow (#262)

## v1.5.0b0 (2026-03-07)

### Feat

- **reporting**: wire append_history_entry into HtmlReporter.write_report (#257)
- **config**: pyproject.toml config support for workers, cache, report, batch_size (#254)
- **parallel**: add --gremlin-workers=auto support (#251)

### Fix

- **reporting**: load and pass history to to_html() for trend chart rendering (#259)
- **config**: validate TOML types for batch_size, cache, report (#253) (#258)
- **types**: replace cast(Any, node) with _XdistWorkerNode Protocol (#250)
- **plugin**: guard xdist hooks when pytest-xdist is absent (#243)
- **release**: move new_tag to env: block on Summarize release step (#242)
- **tests**: reclassify parallel process pool tests as medium (#241)
- **release**: add explicit tag push as safety net in cut-release.yml (#239)
- **instrumentation**: insert gremlin injection after future imports at AST level (#238)
- **release**: add annotated_tag and fix changelog extraction (#235)

### Refactor

- **types**: define TypedDict hierarchies for reporting export formats (#247)
- **types**: use module.__dict__ for __gremlin_active__ access (#248)
- **types**: define TypedDicts for coverage stats return types (#246)
- **types**: define JsonValue TypeAlias and CachedGremlinResult TypedDict (#245)
- **types**: centralise config.rootdir access via _get_rootdir helper (#244)
- **types**: narrow Gremlin.mutated_node and define ASTLocated Protocol (#249)

## v1.4.0 (2026-03-02)

### Feat

- **demo**: Epic F capstone narrated demo — Rich HTML Reports milestone (#229)
- **demo**: narrated Epic E historical trend tracking demo (#228)
- **demo**: narrated Epic D code diff sections demo (#224)
- **demo**: narrated Epic C chart visualizations demo (#226)
- **demo**: narrated MP4 demo for epic-a report location (#225)
- **reporting**: Epics B–E — theme, charts, diffs, history (#212)
- **reporting**: Epic A — default output path + --gremlins-html-dir option (#211)
- **release**: adopt frequent stable releases (FastAPI/Ruff model) (#210)

### Fix

- **demo**: correct version number in capstone outro to 1.3.0 (#231)
- **reporting**: add logging to silent exception handlers in html.py (#223)
- **reporting**: pin Chart.js to 4.4.4 with SRI hash and remove Google Fonts (#222)
- **reporting**: WCAG 2.2 AA accessibility for HTML report (#219)
- **docs**: add project.optional-dependencies for RTD compatibility (#209)
- **docs**: replace --gremlin-workers=auto with --gremlin-parallel (#195)

### Refactor

- **reporting**: extract history.py and diff.py from html.py (#220)
- **tests**: domain-organized directories, explicit markers, fixture consolidation (#208)

## v1.3.0 (2026-02-21)

### Added

- `--gremlin-workers=N` now implies `--gremlin-parallel` — specifying a worker count
  automatically enables parallel mode. Use `pytest --gremlins --gremlin-workers=auto`
  without needing to also pass `--gremlin-parallel`. (#188)

### Fixed

- `pytest --gremlins --cov` now produces real coverage output alongside mutation results.
  Previously the mutation pre-scan subprocess corrupted the `.coverage` data. (#184)
- Windows: Fixed path separator bug in `WorkerPool` sources.json that caused worker
  failures on Windows. (#185)
- Mutation subprocesses now suppress `addopts` and coverage instrumentation from the
  host environment, preventing subprocess interference. (#128)
- `pytest --gremlins -n N` (combining with pytest-xdist) now raises a clear error
  instead of silently producing incorrect results. (#183)

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
