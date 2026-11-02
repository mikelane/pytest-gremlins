# pytest-gremlins Performance Profiling Report

**Date:** July 2026
**Version:** 1.9.0
**Supersedes:** [`0.1.1/profiling-report.md`](0.1.1/profiling-report.md) (archived)

!!! warning "Historical report"
    This report describes v1.9.0. Since v1.10.1, `--gremlin-executor=fork` and
    `--gremlin-executor=inprocess` exit with a usage error, pending
    [#532](https://github.com/mikelane/pytest-gremlins/issues/532): they did not run the mutated
    code, so their results were wrong. The only working executor is `subprocess` (what `auto`
    resolves to). Wherever this report mentions the `inprocess` or `fork` executors as a speedup,
    that speedup was never real and isn't available today. The measurements below are of the
    `subprocess` executor. v1.10.1 also disabled the lightweight runner, so every gremlin now runs
    through the full pytest bootstrap; that release's changelog notes that per-mutant runs are
    slower as a result.

## Executive Summary

Rerunning the phase-by-phase profiler against the current codebase (52 source files, 1,022
gremlins, 1,498 tests) shows the same shape of bottleneck as the original v0.1.1 report:
**coverage collection now dominates runtime**, at over 91% of total time. This report profiles
the default (`subprocess`) executor for direct comparison with the prior report.

### Key Findings

| Metric               | Value          | Impact       |
| --------------------- | -------------- | ------------ |
| Coverage collection   | 91.3% of total | **Critical** |
| Subprocess sample     | 4.6% of total  | Medium       |
| Test discovery        | 3.9% of total  | Low          |
| AST transformation    | 0.2% of total  | Negligible   |
| Code generation       | 0.1% of total  | Negligible   |
| Source discovery      | 0.04% of total | Negligible   |

## Environment

- **Hardware:** Apple Silicon (M-series), macOS 15.6.1 (arm64)
- **Python:** 3.14.0
- **pytest:** 9.1.1
- **pytest-gremlins:** 1.9.0

## Detailed Phase Analysis

### Phase 1: Source Discovery

| Metric           | Value   |
| ----------------- | ------- |
| Duration          | 24.76ms |
| Files discovered  | 52      |
| Total lines       | 10,769  |
| % of total        | 0.04%   |

**Assessment:** Negligible, consistent with the prior report.

### Phase 2: AST Transformation (Mutation Generation)

| Metric              | Value       |
| -------------------- | ----------- |
| Duration             | 137.78ms    |
| Gremlins generated   | 1,022       |
| Avg parse time       | 0.50ms/file |
| Avg transform time   | 2.15ms/file |
| % of total           | 0.2%        |

**Assessment:** Still extremely efficient. Gremlin count has grown ~2.3x since the v0.1.1
report (435 → 1,022) alongside the larger codebase, but per-file timings are essentially
unchanged.

### Phase 3: Code Generation (AST Unparsing)

| Metric            | Value       |
| ------------------ | ----------- |
| Duration           | 43.35ms     |
| Avg unparse time   | 0.83ms/file |
| Output size        | 445KB       |
| % of total         | 0.1%        |

**Assessment:** Negligible, unchanged from prior report.

### Phase 4: Test Discovery

| Metric            | Value     |
| ------------------ | --------- |
| Duration           | 2,552ms   |
| Tests discovered   | 1,498     |
| % of total         | 3.9%      |

**Assessment:** Scales with test suite size (417 → 1,498 tests since v0.1.1) but remains a
minor, one-time cost.

### Phase 5: Coverage Collection

| Metric               | Value             |
| --------------------- | ----------------- |
| Duration              | 60,166ms (60.2s)  |
| Coverage run time     | 60,165ms          |
| Contexts collected    | 1                 |
| Covered files         | 8                 |
| % of total            | **91.3%**         |

**Assessment:** As in the v0.1.1 report, running the full test suite once under `coverage.py`
with dynamic contexts remains the dominant cost. This is proportionally similar to the earlier
measurement (91.4%) despite the codebase and test suite both growing substantially — this phase
scales with test suite size, not with mutation count, so it hasn't improved on its own.

### Phase 6: Per-Mutation Subprocess Execution (Sample)

| Metric               | Value     |
| --------------------- | --------- |
| Sample size           | 5 gremlins |
| Avg subprocess time   | 600.78ms  |
| Min subprocess time   | 596.54ms  |
| Max subprocess time   | 609.70ms  |

**Assessment:** Roughly 2.4x faster per-subprocess than the v0.1.1 measurement (1,460ms avg),
likely reflecting general interpreter/pytest startup improvements rather than an architecture
change. This sample uses the default `subprocess` executor.

## What Changed Since v0.1.1

1. **In-process and fork executors were added** (#349) to address the v0.1.1 report's
   "Priority 1" recommendation. They have since been disabled (see the warning above), so they
   don't change the numbers that matter today.
2. **Persistent worker pool** (#58) is available for the subprocess path but not
   exercised by this single-process profiling script.
3. **Coverage collection is now the clear #1 bottleneck** in relative terms, since subprocess
   overhead has shrunk per call. None of the v0.1.1 report's "Priority 2: Optimize Coverage
   Collection" recommendations (reuse pytest-cov data, parallel coverage via xdist, sampling)
   had shipped at the time of this report.

## Parallel Coverage Pre-Scan (#527)

`--gremlin-prescan-workers N` splits the coverage pre-scan across N serial processes and combines their
coverage data (see [Parallel Coverage Pre-Scan](../guide/configuration.md#parallel-coverage-pre-scan)). It
was measured separately from the profile above, on a synthetic suite built for the purpose.

| Pre-scan workers | Wall clock (3 runs) | Mean | Speedup |
| ---------------- | ------------------- | ---- | ------- |
| 1 (default)      | 37.6 s, 37.6 s, 37.9 s | 37.7 s | 1.0x |
| 2                | 19.2 s, 19.4 s, 19.5 s | 19.4 s | 1.9x |
| 4                | 10.1 s, 10.1 s, 10.2 s | 10.1 s | 3.7x |

- **Suite:** 4,000 tests in 40 files, each running a few lines of a three-function package and sleeping
  4 ms, so the pre-scan is bound by test time rather than coverage tracing. Tests share no state, which is the
  best case for sharding; a suite with a slow session fixture pays that fixture once per shard.
- **Method:** the plugin's `_run_tests_with_coverage` was called directly, so the timings cover the pre-scan
  and reading its data back, not the mutation run. Before any timing was accepted, the coverage map was
  checked: it held all 4,000 tests and 31,600 covered lines, and was identical at 1, 2 and 4 workers.
- **Machine:** Apple M2 Max, 12 cores, 64 GB, macOS, Python 3.14.0, pytest 9.1.1, coverage.py 7.17.0. The
  machine was shared, with a load average between 4 and 9 during the runs, so read the speedups as
  indicative. Sleep-bound tests parallelize better than CPU-bound ones, which share cores with the other
  work on the machine.

## Recommendations

### Priority 1: Optimize Coverage Collection

This is now the largest remaining lever, at 91% of total runtime:

- **Reuse existing coverage data** if tests already ran with coverage as part of the normal
  test suite invocation.
- **Parallel coverage collection**, now available as `--gremlin-prescan-workers` (#527, measured above).
- **Incremental/cached coverage** keyed by content hash, to skip full re-collection when
  unchanged files dominate.

### Priority 2: A faster executor that runs the mutated code

The `inprocess` and `fork` executors were meant to remove the per-gremlin subprocess cost, but
they did not run the mutated code and are disabled. A replacement is tracked in
[#532](https://github.com/mikelane/pytest-gremlins/issues/532).

### Priority 3: Re-profile the current release

This report predates the v1.10.1 change that runs every gremlin through the full pytest
bootstrap. A new end-to-end profile of the `subprocess` executor on the current release would
show today's real numbers.

## Artifacts

- `docs/performance/profiling_data.json` — raw timing data for this run
- `docs/performance/profile_stats.txt` — cProfile output for this run
- `docs/performance/0.1.1/` — archived v0.1.1 report and data, for historical comparison

## Conclusion

At v1.9.0, per this profiling run of the default subprocess path, coverage collection accounted
for the large majority of runtime and scaled with test suite size rather than mutation count.
The `inprocess`/`fork` executors that were expected to cut the subprocess-spawn cost turned out
not to run the mutated code and are disabled (see the warning at the top). None of the
coverage-side recommendations from the original report had been implemented at the time.
