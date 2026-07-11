# pytest-gremlins Performance Profiling Report

**Date:** July 2026
**Version:** 1.9.0
**Supersedes:** [`0.1.1/profiling-report.md`](0.1.1/profiling-report.md) (archived)

## Executive Summary

Rerunning the phase-by-phase profiler against the current codebase (52 source files, 1,022
gremlins, 1,498 tests) shows the same shape of bottleneck as the original v0.1.1 report:
**coverage collection now dominates runtime**, at over 91% of total time. Per-mutation
subprocess overhead, once the largest single cost, has shrunk substantially in relative terms
now that `--gremlin-executor in-process`/`fork` exist as alternatives to the default subprocess
path — this report profiles the default (`subprocess`) executor for direct comparison with the
prior report.

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
change — this sample still uses the default `subprocess` executor, not `in-process`/`fork`.
The in-process executor (`--gremlin-executor in-process`, shipped in #349) bypasses this cost
entirely for non-import-time mutations and is not represented in this profiling run.

## What Changed Since v0.1.1

1. **In-process and fork executors now exist** (`--gremlin-executor in-process|fork`, #349),
   directly addressing the v0.1.1 report's "Priority 1" recommendation. This profiling run
   deliberately measures the default `subprocess` executor to stay comparable with the old
   report; it does not reflect the speedup available from switching executors.
2. **Persistent worker pool** (#58) is available for the subprocess/fork paths but not
   exercised by this single-process profiling script.
3. **Coverage collection is now the clear #1 bottleneck** in relative terms, since subprocess
   overhead has both shrunk per-call and is largely avoidable via `in-process` mode. None of
   the v0.1.1 report's "Priority 2: Optimize Coverage Collection" recommendations
   (reuse pytest-cov data, parallel coverage via xdist, sampling) have shipped yet.

## Recommendations

### Priority 1: Optimize Coverage Collection

This is now the largest remaining lever, at 91% of total runtime:

- **Reuse existing coverage data** if tests already ran with coverage as part of the normal
  test suite invocation.
- **Parallel coverage collection** via pytest-xdist.
- **Incremental/cached coverage** keyed by content hash, to skip full re-collection when
  unchanged files dominate.

### Priority 2: Default to a faster executor where safe

`in-process` is dramatically faster but currently misses ~15% of mutations (import-time
expressions) per its own docstring caveat. Consider whether the plugin should auto-detect and
warn when running in `subprocess` mode with no explicit `--gremlin-executor` flag, given
the size of the gap.

### Priority 3: Re-profile with `in-process`/`fork` executors

This report only characterizes the default subprocess path for continuity with v0.1.1.
A follow-up run profiling `--gremlin-executor in-process` and `--gremlin-executor fork` end to
end (not just the 5-sample subprocess microbenchmark) would show current real-world numbers
for the shipped fix.

## Artifacts

- `docs/performance/profiling_data.json` — raw timing data for this run
- `docs/performance/profile_stats.txt` — cProfile output for this run
- `docs/performance/0.1.1/` — archived v0.1.1 report and data, for historical comparison

## Conclusion

The subprocess-spawn bottleneck identified in v0.1.1 has been substantially mitigated by the
`in-process`/`fork` executors shipped since. What's left, per this profiling run of the default
subprocess path, is coverage collection: it now accounts for the large majority of runtime and
scales with test suite size rather than mutation count. None of the coverage-side
recommendations from the original report have been implemented yet — that's the next
architectural target for a step change in speed.
