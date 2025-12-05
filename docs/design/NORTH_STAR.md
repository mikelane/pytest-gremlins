# pytest-gremlins: North Star Design Document

> "Let the gremlins loose. See which ones survive."

## Vision

pytest-gremlins is a **fast-first** mutation testing plugin for pytest. We aim to make mutation testing practical for everyday development - not an overnight CI job, but part of the normal TDD feedback loop.

## Why Another Mutation Testing Tool?

The Python mutation testing landscape is broken:

| Tool | Fatal Flaw |
|------|-----------|
| **mutmut** | Single-threaded, no incremental analysis, 65+ minute runs on medium projects |
| **Cosmic Ray** | Requires Celery + RabbitMQ for parallelization, complex setup |
| **MutPy** | Dead (last update 2019), Python 3.4-3.7 only |
| **mutatest** | Dead (last update 2022), Python ≤3.8 only, random behavior |

Meanwhile, the JVM (PIT) and JavaScript (Stryker) worlds have solved these problems. We're bringing those lessons to Python.

## Core Principles

### 1. Speed Is Non-Negotiable

Mutation testing is useless if developers don't run it. Every architectural decision optimizes for speed:

- **Mutation switching** over file modification
- **Coverage-guided test selection** over running all tests
- **Incremental analysis** over full re-runs
- **Parallel execution** over sequential

### 2. Native pytest Integration

Not a wrapper. Not a separate CLI. A proper pytest plugin that respects:

- pytest's collection and execution model
- Fixtures and markers
- pytest-xdist for parallelization
- pytest-cov for coverage data

### 3. Actionable Output

No walls of text. Results should tell you:

1. Which gremlins survived (your tests are weak here)
2. Which tests would need strengthening
3. Which code is well-protected

---

## Speed Architecture

### The Four Pillars of Speed

```
┌─────────────────────────────────────────────────────────────┐
│                    SPEED STRATEGY                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   MUTATION      │    │   COVERAGE      │                │
│  │   SWITCHING     │    │   GUIDANCE      │                │
│  │                 │    │                 │                │
│  │  No file I/O    │    │  Only run tests │                │
│  │  No reloads     │    │  that matter    │                │
│  │  Single parse   │    │                 │                │
│  └────────┬────────┘    └────────┬────────┘                │
│           │                      │                          │
│           └──────────┬───────────┘                          │
│                      │                                      │
│  ┌─────────────────┐ │ ┌─────────────────┐                 │
│  │  INCREMENTAL   │◄─┴─►│    PARALLEL    │                 │
│  │   ANALYSIS     │     │   EXECUTION    │                 │
│  │                │     │                │                 │
│  │  Skip what     │     │  N workers,    │                 │
│  │  hasn't changed│     │  N gremlins    │                 │
│  └────────────────┘     └────────────────┘                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Pillar 1: Mutation Switching

**The Problem:** Traditional mutation testing modifies files on disk, reloads modules, runs tests, restores files. Repeat 1000x.

**The Solution:** Instrument code once with ALL mutations embedded, controlled by an environment variable:

```python
# Original
def is_adult(age):
    return age >= 18

# Instrumented (all gremlins baked in)
def is_adult(age):
    _g = __gremlin_active__
    if _g == "g001": return age > 18    # >= → >
    if _g == "g002": return age <= 18   # >= → <=
    if _g == "g003": return age < 18    # >= → <
    if _g == "g004": return age == 18   # >= → ==
    return age >= 18                     # original
```

**Benefits:**
- Zero file I/O during test runs
- Zero module reloads
- Single AST parse
- Test process stays hot (no reimporting numpy 1000x)
- Safe parallelization (workers just set different env vars)

**Inspiration:** Stryker 4.0's mutation switching delivers 20-70% speedup. For Python with slow imports, gains are even larger.

### Pillar 2: Coverage-Guided Test Selection

**The Problem:** 1,000 gremlins × 500 tests = 500,000 test runs. Most are pointless - a test that never touches the mutated code can't catch the gremlin.

**The Solution:** Build a coverage map, only run tests that cover each gremlin's location:

```python
coverage_map = {
    "src/auth.py:42": ["test_login_success", "test_login_failure"],
    "src/shipping.py:17": ["test_calculate_shipping"],
}

# Gremlin in auth.py:42 → run 2 tests, not 500
```

**Benefits:**
- 10-1000x reduction in test executions
- Scales better as project grows (more modular = more savings)
- Identifies "incidentally tested" code (touched by many tests but not directly targeted)

**Inspiration:** PIT and Stryker both do this. Stryker reports 40-60% additional speedup from coverage guidance.

### Pillar 3: Incremental Analysis

**The Problem:** You run mutation testing (10 minutes), fix one test, run again (10 minutes). Terrible feedback loop.

**The Solution:** Cache results keyed by content hashes. Only re-run when source or tests change:

```python
cache_key = hash(source_file + test_file + gremlin_definition)

if cache_key in history:
    return history[cache_key]  # Instant
else:
    result = run_tests()
    history[cache_key] = result
    return result
```

**Invalidation Rules:**
| Change | Action |
|--------|--------|
| Source file modified | Re-run gremlins in that file |
| Test file modified | Re-run gremlins covered by those tests |
| New test added | Re-run gremlins the new test covers |
| Test deleted | Re-run gremlins that test was zapping |
| Nothing changed | Return cached results instantly |

**Benefits:**
- Subsequent runs finish in seconds
- Enables mutation testing in TDD workflow
- CI caching works naturally

**Inspiration:** PIT reduced a 31-hour analysis to under 3 minutes with incremental mode.

### Pillar 4: Parallel Execution

**The Problem:** Even with all optimizations, 1000 gremlins still take time sequentially.

**The Solution:** Distribute gremlins across worker processes:

```
Main Process
    │
    ├── Worker 1: ACTIVE_GREMLIN=1,5,9...
    ├── Worker 2: ACTIVE_GREMLIN=2,6,10...
    ├── Worker 3: ACTIVE_GREMLIN=3,7,11...
    └── Worker 4: ACTIVE_GREMLIN=4,8,12...
```

**Why Mutation Switching Enables This:**
- Traditional approach: workers fight over file modifications
- Mutation switching: all workers read same instrumented code, just set different env vars
- No locks, no file copies, no coordination needed

**Benefits:**
- Linear speedup with core count
- Safe by design (no shared mutable state)
- Simple implementation (ProcessPoolExecutor)

---

## Combined Speedup

| Optimization | Individual Gain | Cumulative |
|--------------|-----------------|------------|
| Baseline (naive) | 1x | 1x |
| Mutation switching | 2-5x | 2-5x |
| Coverage guidance | 10-100x | 20-500x |
| Incremental analysis | 10-1000x (repeat runs) | 200-500,000x |
| Parallel (8 cores) | 8x | 1,600-4,000,000x |

A project that took 8 hours with naive mutation testing could complete in **seconds** on repeat runs with all optimizations.

---

## Domain Language (Gremlins Theme)

We use Gremlins movie references as our ubiquitous language:

| Traditional Term | Gremlin Term | Description |
|-----------------|--------------|-------------|
| Original code | **Mogwai** | Clean, untouched source code |
| Start mutation testing | **Feed after midnight** | Begin the mutation process |
| Mutation engine | **Midnight feeding** | Transforms mogwai into gremlins |
| Mutant | **Gremlin** | A mutation injected into code |
| Kill mutant | **Zap** | Test catches the mutation |
| Surviving mutant | **Survivor** | Mutation not caught (weak test coverage) |
| Cleanup/reporting | **Microwave** | Eliminate gremlins, generate report |

### The Workflow

```
1. MOGWAI        Your original, well-behaved source code
       │
       ▼
2. FEED AFTER    Start pytest-gremlins
   MIDNIGHT
       │
       ▼
3. GREMLINS      Mutations spawn throughout your code
   EMERGE
       │
       ▼
4. ZAP           Tests hunt and eliminate gremlins
   GREMLINS
       │
       ▼
5. SURVIVORS     Report which gremlins your tests missed
   REPORT
       │
       ▼
6. MICROWAVE     Clean up, strengthen tests, repeat
```

---

## Non-Goals (For Now)

- **Distributed execution across machines** - Celery/RabbitMQ complexity not worth it for v1
- **Every possible mutation operator** - Start with high-value operators, expand later
- **Python < 3.11 support** - Modern Python only, leverage match statements and type hints
- **Framework-specific integrations** - Django, Flask, etc. can come later

---

## Success Metrics

1. **Speed:** Incremental run on unchanged code < 5 seconds
2. **Speed:** Full run on 10K LOC project < 5 minutes (8 cores)
3. **Usability:** Zero config for basic usage (`pytest --gremlins`)
4. **Accuracy:** No false positives (gremlins reported as survivors that tests actually catch)

---

## Prior Art & Inspiration

- [PIT (Java)](https://pitest.org/) - Gold standard, incremental analysis, parallel execution
- [Stryker (JS/TS)](https://stryker-mutator.io/) - Mutation switching architecture
- [mutmut (Python)](https://github.com/boxed/mutmut) - What to avoid (slow, sequential)
- [Cosmic Ray (Python)](https://github.com/sixty-north/cosmic-ray) - Good operators, bad UX

---

## Open Questions

1. **AST vs. Bytecode mutation?** - AST is more readable/debuggable, bytecode might be faster
2. **How to handle module-level code?** - Code that runs at import time before gremlin switch
3. **What mutation operators for v1?** - Need to define the initial gremlin types
4. **Integration with pytest-test-categories?** - Run gremlins only on "small" tests for speed?
5. **Report format?** - HTML? JSON? GitHub annotations? All of the above?
