# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.8.0b2 (2026-03-29)

### Fix

- **Coverage selection**: use full pytest node IDs instead of bare function names — fixes silent
  test dropping when multiple files contain functions with the same name (common in BDD-style
  `it_*` naming) (#357)

## v1.8.0b1 (2026-03-28)

### Feat

- **`--gremlin-executor=auto`** is now the default — resolves to `subprocess` (safe, full pipeline)
  with infrastructure in place to switch to `fork` once the fork executor supports coverage-guided
  selection, progress reporting, and cache integration (#354)

## v1.8.0b0 (2026-03-28)

### Feat

- **InProcessExecutor**: toggle `__gremlin_active__` in-process instead of spawning subprocess —
  263x faster per mutation on micro-benchmarks (#349)
- **ForkExecutor**: fork-per-batch isolation wrapping InProcessExecutor — 22x faster with full
  process isolation (#349)
- **`--gremlin-executor`** CLI option: choose `subprocess` (default), `fork`, or `in-process`
  execution strategy (#349)
- **`selected_tests`** field in JSON report: see which tests were selected for each gremlin (#351)
- **`execution_time_ms`** exported in JSON report (#351)
- **`--gremlin-no-coverage-filter`** CLI flag: disable coverage-guided test selection for
  debugging (#351)

### Fix

- Tri-state `_TestOutcome` in `_run_test_spec`: distinguishes test failures from infrastructure
  errors — no more false-positive zaps (#349)
- Use `dataclasses.replace()` for safe `GremlinResult` field attachment (#351)
- Windows: `discover_by_*` functions return `Path` objects instead of `str` — eliminates
  backslash path comparison failures (#349)

## v1.7.0 (2026-03-27)

### Perf

- **parallel**: lightweight test runner bypasses full pytest startup for per-gremlin subprocesses,
  reducing per-gremlin cost from ~950ms to ~200ms; sequential mode 4.8x faster, parallel 3.4x
  faster on the synthetic benchmark; attrs (681 gremlins) drops from ~315s to ~87s (#344)

### Feat

- **reporting**: surface `error_output` in all report formats (console, HTML, JSON) so users can
  see why gremlins errored without re-running with verbose flags (#339)
- **instrumentation**: log the exception before re-raising in the import hook, making instrumentation
  failures diagnosable from logs instead of opaque tracebacks (#338)
- **ci**: add attrs compatibility smoke test to CI matrix — catches real-world regressions on every
  PR (#343)

### Fix

- **parallel**: remove early termination in `_run_gremlin_batch()` that silently skipped gremlins
  after the first zap; batch mode was testing only 17/117 gremlins, producing incorrect mutation
  scores (#344)
- **plugin**: only pass `--no-cov` to per-gremlin subprocesses when pytest-cov is actually
  installed; projects without it received an unknown CLI flag causing pytest exit-code 4 (#341)

## v1.6.0 (2026-03-23)

### Feat

- **config**: `--gremlin-exclude` CLI flag and `exclude` TOML key for glob patterns to skip
  during source file discovery (e.g. `--gremlin-exclude="**/migrations/*"`); repeatable on
  the command line, list in TOML (#322, #324)
- **pragma**: pardon pragmas can now be placed on the line immediately above the code they
  apply to, solving the line-length problem when inline pragmas push past 120 characters;
  both same-line and line-above placements are supported (#327, #328)

### Fix

- **tests**: mock config fixtures now include `gremlin_exclude` attribute, fixing 20 medium
  test failures introduced by #324 (#328)
- **tests**: remove flaky `it_adds_minimal_overhead_for_cold_cache_over_no_cache` — timing
  assertion on subprocess wall-clock was sensitive to CI runner jitter; remaining cache perf
  tests already prove warm < cold speedup (#334)

### Docs

- comprehensive line-by-line documentation audit against the codebase — removed 13 fictional
  CLI flags, 6 fictional TOML keys, fixed env var references, added 5 missing CLI flags to
  the configuration reference, corrected score formula, and updated mutmut comparisons per
  maintainer feedback (#315, #326)

### Dependencies

- bump dorny/paths-filter 3 → 4 (#316)
- bump tox-uv 1.33.1 → 1.33.4 (#319)
- bump tox 4.49.0 → 4.50.3 (#330)
- bump pytest-cov 7.0.0 → 7.1.0 (#331)
- bump coverage 7.13.4 → 7.13.5 (#332)
- bump ruff 0.15.5 → 0.15.7 (#333)

## v1.5.1 (2026-03-15)

### Feat

- **config**: `--gremlin-report` now accepts comma-separated formats (e.g.
  `--gremlin-report=json,html`) to write multiple reports in a single run; TOML config
  accepts both `report = "json,html"` and `report = ["json", "html"]` (#308, #309)
- **reporting**: wire `JsonReporter` into the plugin dispatch — `--gremlin-report=json`
  now writes `coverage/gremlins/gremlins.json` (previously implemented but never called)
- **config**: validate report formats against an allowlist (`console`, `html`, `json`)
  at both CLI and TOML layers with clear error messages for unknown formats

## v1.5.0 (2026-03-14)

### Feat

- **xdist**: two-phase integration — Phase 1 distributes the test suite with `-n auto`; Phase 2 uses xdist's
  resolved worker count for mutation evaluation, making `-n auto` sufficient for both test distribution and
  parallelism without `--gremlin-workers` (#296)
- **pragma**: inline suppression `# gremlin: pardon[reason]` suppresses a mutation with a documented reason;
  valid reasons are `equivalent`, `untestable`, `out_of_scope` (#261, #266, #275)
- **pragma**: `--max-pardons` (absolute) and `--gremlin-max-pardons-pct` (percentage) enforce a ceiling on
  pardoned mutations to prevent silent score inflation (#268, #270)
- **config**: `[tool.pytest-gremlins]` in `pyproject.toml` now accepts `workers`, `cache`, `report`, and
  `batch_size` — all CLI flags have a config-file equivalent (#254)
- **config**: `--gremlin-workers=auto` resolves to `os.cpu_count()` at option parse time (#251)
- **config**: source discovery now supports `project-name`, `setup.cfg`, and `importlib` strategies for
  non-standard project layouts (#273)
- **reporting**: HTML report shows a mutation score trend chart across runs; chart renders after ≥ 2 runs
  (#257, #259)

### Fix

- **instrumentation**: gremlin injection now inserts after `__future__` imports at the AST level, fixing
  `SyntaxError` in files using `from __future__ import annotations` (#238)
- **plugin**: running without `pytest-xdist` installed no longer raises `check_pending()`
  failures — the plugin operates in single-worker mode when xdist is absent (#243)
- **config**: TOML type validation for `batch_size`, `cache`, and `report` with actionable error messages
  (#253, #258)
- **reporting**: HTML report WCAG 2.1 AA accessibility — contrast ratios, keyboard navigation, expand-all
  overflow (#255, #262, #264)

### Changed

- **pragma**: suppression keyword renamed from `survivor` to `pardon`. Update existing pragmas:
  `# gremlin: survivor[equivalent]` → `# gremlin: pardon[equivalent]`. The old keyword no longer works.
  (#275)

## v1.5.0b8 (2026-03-11)

### Feat

- **xdist**: implement two-phase xdist integration (#296) (#301)

### Fix

- **xdist**: strip wip markers from BDD scenarios now that #296 is merged (#303)

## v1.5.0b7 (2026-03-10)

### Fix

- **tests**: prevent TC006 timing violations in test_toml_config.py (#293)
- **ci**: disable hermeticity enforcement for doctest run (#299) (#300)
- **tests**: eliminate importlib package scan from small tests (#291)

## v1.5.0b6 (2026-03-08)

### Fix

- **pragma**: include filename in suppression pragma warning messages (#277)

## v1.5.0b5 (2026-03-08)

### Refactor

- **pragma**: rename survivor keyword to pardon in inline suppression syntax (#275)

## v1.5.0b4 (2026-03-08)

### Feat

- **config**: add project-name, setup.cfg, and importlib source discovery strategies (#273)

## v1.5.0b3 (2026-03-07)

### Feat

- **pragma**: enforce maximum pardon count via --max-pardons / config (#270)

### Refactor

- **tests**: extract _MockOption/_MockConfig into shared make_pytest_config fixture (#269)

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
