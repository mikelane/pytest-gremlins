# pytest-gremlins Benchmark Suite

This directory contains the benchmark infrastructure for comparing pytest-gremlins against mutmut.

## Quick Start

```bash
# Install benchmark dependencies
pip install psutil mutmut

# Run synthetic benchmark (fast, good for CI)
python benchmarks/run_benchmarks.py --project synthetic --runs 3

# Results are saved to benchmarks/results/
```

## Benchmark Philosophy

From [Issue #39](https://github.com/mikelane/pytest-gremlins/issues/39):

> The entire value proposition of pytest-gremlins is **speed**. If we can't demonstrate significant
> speed improvements over mutmut in fair, reproducible benchmarks, we have not achieved our MLP goals.

### Fairness Principles

1. **Same test suite** - Both tools run against identical code and tests
2. **Same mutations** - Similar mutation operators where possible
3. **Same environment** - Same hardware, Python version, dependencies
4. **Multiple runs** - Report mean and standard deviation
5. **Transparent methodology** - All settings and configurations documented
6. **Honest reporting** - If we're slower somewhere, we say so

### What We DON'T Do

- Cherry-pick benchmarks where we happen to win
- Use different mutation operators than mutmut
- Run mutmut with suboptimal settings
- Exclude warm-up runs that favor us
- Test only on tiny projects where overhead dominates
- Ignore scenarios where mutmut might win

## Benchmark Projects

### Synthetic (Default)

A small but representative Python project with:

- ~150 lines of source code across 3 modules
- ~50 test cases covering most code paths
- Arithmetic, comparison, and boolean operations
- Loops and conditional logic

Good for quick benchmarks and CI validation.

### Real Projects (TODO)

| Project | Size     | Status  |
| ------- | -------- | ------- |
| attrs   | ~2k LOC  | Planned |
| httpx   | ~10k LOC | Planned |
| rich    | ~15k LOC | Planned |

## Configurations Tested

### mutmut

| Config      | Description                             |
| ----------- | --------------------------------------- |
| `default`   | Standard mutmut run                     |
| `no-backup` | Skip backup file creation (--no-backup) |

### pytest-gremlins

| Config       | Description                   | Expected Speedup            |
| ------------ | ----------------------------- | --------------------------- |
| `sequential` | No parallelization or caching | ~2-5x (mutation switching)  |
| `parallel`   | Multiple workers              | ~N x cores additional       |
| `with-cache` | Incremental analysis          | ~100x on repeat runs        |
| `full`       | All optimizations             | Maximum speedup             |

## Running Benchmarks

### Basic Usage

```bash
# Run with defaults (synthetic project, 3 runs)
python benchmarks/run_benchmarks.py

# More runs for better statistics
python benchmarks/run_benchmarks.py --runs 10

# Specify output directory
python benchmarks/run_benchmarks.py --output /path/to/results
```

### CI Usage

```bash
# Single run for CI (fast)
python benchmarks/run_benchmarks.py --runs 1 --project synthetic
```

## Output

Results are saved in two formats:

1. **Markdown** (`benchmark_YYYYMMDD_HHMMSS.md`) - Human-readable report
2. **JSON** (`benchmark_YYYYMMDD_HHMMSS.json`) - Machine-readable data

## Metrics Collected

| Metric           | Description                        |
| ---------------- | ---------------------------------- |
| Wall time        | Total execution time               |
| Mutations total  | Number of mutations generated      |
| Mutations killed | Mutations caught by tests          |
| Mean/Stddev      | Statistical measures across runs   |

## Interpreting Results

### What Good Results Look Like

If pytest-gremlins is working as designed:

- **Sequential mode** should be ~2-5x faster than mutmut (mutation switching)
- **Parallel mode** should scale roughly linearly with cores
- **Cache mode** should be nearly instant on unchanged code
- **Full mode** should combine all benefits

### Warning Signs

If we see:

- Sequential slower than mutmut -> instrumentation overhead too high
- Parallel not scaling -> worker coordination issues
- Cache not helping -> invalidation problems
- Similar mutation counts but different kill rates -> operator differences

## Architecture Background

pytest-gremlins achieves speed through four pillars:

1. **Mutation Switching** - Instrument code once, toggle via env var
2. **Coverage Guidance** - Only run tests that cover mutated code
3. **Incremental Analysis** - Cache results, skip unchanged code
4. **Parallel Execution** - Distribute work across workers

See [NORTH_STAR.md](../docs/design/NORTH_STAR.md) for details.

## Development

### Adding New Benchmark Projects

1. Add a `ProjectConfig` in `run_benchmarks.py`
2. Define mutmut and gremlins configurations
3. Implement setup/teardown if needed

### Testing the Benchmark Suite

```bash
# Run benchmark tests
pytest tests/benchmark/
```

## Continuous Integration

Benchmarks run automatically in CI to prevent performance regressions.

### When Benchmarks Run

| Event                    | Runs? | Purpose                                      |
| ------------------------ | ----- | -------------------------------------------- |
| Push to main             | Yes   | Track trends, post results as commit comment |
| Weekly (Sunday midnight) | Yes   | Catch gradual regressions                    |
| Manual workflow_dispatch | Yes   | Investigation or baseline update             |
| Pull requests            | No    | Too slow, would block PRs                    |

### Regression Detection

The `check_regression.py` script compares current results against `baseline.json`:

```bash
# Check for regressions (exits non-zero if >10% slower)
python benchmarks/check_regression.py \
    --baseline benchmarks/baseline.json \
    --current benchmarks/results/benchmark_YYYYMMDD.json \
    --threshold 10
```

### Baseline Management

The baseline file (`baseline.json`) contains reference times from a known-good state:

```json
{
  "gremlins_sequential": 45.63,
  "gremlins_parallel": 10.36,
  "gremlins_full": 11.42,
  "mutmut_default": 37.22
}
```

To update the baseline after achieving performance improvements:

1. Go to Actions > Benchmarks workflow
2. Click "Run workflow"
3. Check "Update baseline with current results"
4. Click "Run workflow"

The workflow will commit the new baseline automatically.

### Regression Threshold

The default threshold is 10%, meaning:

- A config is flagged as regressed if it's >10% slower than baseline
- Improvements (>10% faster) are noted but don't cause failure
- Exact threshold changes should be discussed and documented
