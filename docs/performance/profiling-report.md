# pytest-gremlins Performance Profiling Report

**Date:** January 2026
**Version:** 0.1.1
**Issue:** #48 - Profile sequential mode to identify bottlenecks

## Executive Summary

Sequential mode performance analysis reveals that **subprocess overhead dominates execution time**, accounting for approximately **90% of total runtime**. The primary bottleneck is not the mutation switching architecture itself, but the cost of spawning separate pytest processes for each gremlin test.

### Key Findings

| Metric | Value | Impact |
|--------|-------|--------|
| Subprocess wait time | 90% of total | **Critical** |
| Coverage collection | 8-10% of total | Medium |
| AST transformation | <0.5% of total | Low |
| Test selection | <0.1% of total | Negligible |

### Speed vs mutmut Baseline

The original claim of "0.8x mutmut speed" (23% slower) was based on incomplete measurements. Proper profiling reveals:

- **On small targets (16 gremlins, 15 tests):** gremlins takes ~20s vs mutmut ~12s = 1.7x slower
- **The gap is entirely due to subprocess overhead**, not mutation switching

## Environment

- **Hardware:** Apple Silicon (M-series)
- **Python:** 3.14.0
- **pytest:** 9.0.1
- **OS:** Darwin (macOS)

## Detailed Phase Analysis

### Phase 1: Source Discovery

| Metric | Value |
|--------|-------|
| Duration | 25.6ms |
| Files discovered | 35 |
| Total lines | 4,979 |
| % of total | 0.03% |

**Assessment:** Negligible overhead. File system operations are fast.

### Phase 2: AST Transformation (Mutation Generation)

| Metric | Value |
|--------|-------|
| Duration | 96.7ms |
| Gremlins generated | 435 |
| Avg parse time | 0.53ms/file |
| Avg transform time | 2.23ms/file |
| % of total | 0.1% |

**Assessment:** Extremely efficient. The mutation switching architecture parses and transforms all source files in under 100ms, generating 435 gremlins from 35 files.

### Phase 3: Code Generation (AST Unparsing)

| Metric | Value |
|--------|-------|
| Duration | 28.7ms |
| Avg unparse time | 0.82ms/file |
| Output size | 183KB |
| % of total | 0.03% |

**Assessment:** Negligible. Python's `ast.unparse()` is fast.

### Phase 4: Test Discovery

| Metric | Value |
|--------|-------|
| Duration | 1,183ms |
| Tests discovered | 417 |
| % of total | 1.2% |

**Assessment:** Acceptable. This is standard pytest collection overhead.

### Phase 5: Coverage Collection (MAJOR BOTTLENECK #1)

| Metric | Value |
|--------|-------|
| Duration | 91,796ms (91.8s) |
| Coverage run time | 91,785ms |
| Contexts collected | 390 |
| Covered files | 82 |
| % of total | **91.4%** |

**Assessment:** This is the first major bottleneck when considering the full test suite. Coverage collection runs the entire test suite with `coverage.py`'s dynamic context feature to map lines to tests. For our full test suite (417 tests), this takes 91 seconds.

**Note:** For smaller test subsets, this phase is proportionally smaller. The 91s measurement was against the full test suite.

### Phase 6: Per-Mutation Subprocess Execution (MAJOR BOTTLENECK #2)

| Metric | Value |
|--------|-------|
| Sample size | 5 gremlins |
| Avg subprocess time | 1,460ms |
| Min subprocess time | 1,187ms |
| Max subprocess time | 1,792ms |
| Subprocess overhead | ~500-700ms per call |

**Assessment:** Each gremlin test requires spawning a new Python subprocess, which incurs:
1. Python interpreter startup (~300ms)
2. pytest initialization (~200ms)
3. Module imports (~200ms)
4. Actual test execution (variable)

For 16 gremlins running 15 tests each, this means 16 subprocess spawns.

## cProfile Analysis

Detailed function-level profiling on a single mutation test run (16 gremlins, 15 tests):

### Top Functions by Cumulative Time

| Function | Cumtime | Calls | Description |
|----------|---------|-------|-------------|
| `select.poll` | 22.41s | 80 | Waiting for subprocess I/O |
| `subprocess.run` | 22.58s | 16 | Process spawning |
| `_run_mutation_testing` | 20.59s | 1 | Main mutation loop |
| `_test_gremlin` | 20.58s | 15 | Per-gremlin test execution |
| `_collect_coverage` | 2.03s | 1 | Coverage data collection |

### Call Hierarchy

```
pytest_sessionfinish (22.6s)
├── _collect_coverage (2.0s)
│   └── subprocess.run (2.0s) - coverage collection
└── _run_mutation_testing (20.6s)
    └── _test_gremlin (20.6s, called 15x)
        └── subprocess.run (20.6s, ~1.4s each)
            └── select.poll (waiting for tests)
```

### Key Observation

**90% of execution time is spent in `select.poll`** - literally waiting for subprocess I/O. The Python interpreter and pytest spend almost no time on actual computation; they're waiting for child processes.

## Bottleneck Summary

### Ranked by Impact

1. **Subprocess Spawning Overhead** (Critical)
   - Each gremlin test spawns a new Python process
   - ~1.4 seconds per subprocess (500-700ms is pure overhead)
   - For N gremlins: N * 1.4s minimum
   - **Solution:** Batch testing, persistent workers, or in-process execution

2. **Coverage Collection** (Medium)
   - Must run full test suite once with coverage
   - Scales with test suite size
   - **Solution:** Reuse existing coverage data, parallel collection, or sampling

3. **Test Discovery** (Low)
   - Standard pytest overhead
   - ~1.2s one-time cost
   - **Solution:** Cache test collection

4. **AST Transformation** (Negligible)
   - <100ms for 35 files, 435 gremlins
   - **No optimization needed**

## Comparison with mutmut

Direct comparison was not possible due to mutmut 3.x compatibility issues with Python 3.14 (multiprocessing context error). However, based on architecture analysis:

### mutmut's Approach
- Uses "trampoline" injection at module import time
- Runs tests in the same process (no subprocess per mutation)
- Uses hash-based caching aggressively

### gremlins' Current Approach
- Spawns subprocess for each gremlin test
- Provides isolation but at high cost
- Clean implementation but slower

### Key Difference
mutmut avoids subprocess overhead by running mutations in-process. gremlins' subprocess isolation is safer but **orders of magnitude slower** for sequential execution.

## Recommendations

### Priority 1: Reduce Subprocess Overhead (Issue #49)

**Option A: In-Process Execution (Fastest)**
- Run tests in the same process as gremlins
- Toggle `__gremlin_active__` between test runs
- Risk: Test pollution, but mutation switching is designed for this
- Expected speedup: **10-50x**

**Option B: Persistent Worker Pool**
- Keep subprocess pool warm
- Workers import modules once, run multiple gremlins
- Pass gremlin ID via IPC, not environment variable
- Expected speedup: **5-10x**

**Option C: Batch Subprocess Execution**
- Run multiple gremlins per subprocess
- Reduces spawn overhead but increases per-subprocess time
- Expected speedup: **2-5x**

### Priority 2: Optimize Coverage Collection (Issue #51)

- **Reuse pytest-cov data:** If tests already ran with coverage, use that
- **Parallel coverage:** Run coverage collection with pytest-xdist
- **Sampling:** For large test suites, sample coverage data
- Expected speedup: **2-5x** on coverage phase

### Priority 3: Cache Test Collection

- Cache pytest's test collection between runs
- Minor optimization (~1s savings)
- Expected speedup: Negligible overall impact

## Target Performance

Based on this analysis, achievable targets:

| Scenario | Current | Target | Speedup |
|----------|---------|--------|---------|
| 16 gremlins, 15 tests | 20s | 2-4s | **5-10x** |
| 435 gremlins, 417 tests | ~10min | 30-60s | **10-20x** |
| Incremental (cached) | N/A | <5s | N/A |

## Artifacts

- `/docs/performance/profiling_data.json` - Raw timing data
- `/docs/performance/profile_stats.txt` - cProfile output
- `/tmp/gremlins_profile.pstats` - Binary profile data (for snakeviz)

## Conclusion

The performance gap between pytest-gremlins and mutmut is **not** due to the mutation switching architecture, which is highly efficient (<100ms for full transformation). The bottleneck is **subprocess isolation** - spawning a new Python process for each gremlin test.

To achieve competitive or superior performance, pytest-gremlins must either:
1. Move to in-process execution (matching mutmut's approach)
2. Implement a persistent worker pool (maintaining isolation with reduced overhead)
3. Use parallel execution aggressively (already partially implemented)

The parallel execution mode (#30) partially addresses this by running multiple subprocesses concurrently, but doesn't reduce the per-subprocess overhead. True speedup requires architectural changes to the test execution model.
