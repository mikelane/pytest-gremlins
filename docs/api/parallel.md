# Parallel Module

The parallel module implements **parallel execution**, the fourth pillar of pytest-gremlins' speed
strategy. Gremlins are distributed across multiple worker processes for faster results on
multi-core machines.

## Overview

Sequential execution:

```text
1000 gremlins x 50ms = 50 seconds (1 worker)
```

Parallel execution:

```text
1000 gremlins x 50ms / 8 workers = 6.25 seconds
```

The mutation switching architecture makes parallelization safe because each worker operates
independently with its own `ACTIVE_GREMLIN` environment variable.

## Module Exports

```python
from pytest_gremlins.parallel.pool import WorkerPool, WorkerResult
from pytest_gremlins.parallel.pool_config import PoolConfig
from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool
from pytest_gremlins.parallel.batch_executor import BatchExecutor
from pytest_gremlins.parallel.aggregator import ResultAggregator
from pytest_gremlins.parallel.distribution import (
    DistributionStrategy,
    RoundRobinDistribution,
    WeightedDistribution,
)
```

---

## WorkerPool

Basic worker pool using `ProcessPoolExecutor`.

::: pytest_gremlins.parallel.pool.WorkerPool
    options:
      show_root_heading: true
      show_source: true
      members:
        - "__init__"
        - max_workers
        - timeout
        - submit
        - shutdown

### WorkerPool Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_workers` | `int \| None` | CPU count | Number of worker processes |
| `timeout` | `int` | `30` | Timeout per gremlin (seconds) |

### Usage Example

```python
from concurrent.futures import as_completed
from pytest_gremlins.parallel.pool import WorkerPool

with WorkerPool(max_workers=4, timeout=30) as pool:
    futures = {}

    for gremlin_id in ['g001', 'g002', 'g003']:
        future = pool.submit(
            gremlin_id=gremlin_id,
            test_command=['pytest', '-x', 'tests/'],
            rootdir='/path/to/project',
            instrumented_dir='/tmp/instrumented',
            env_vars={},
        )
        futures[future] = gremlin_id

    for future in as_completed(futures):
        result = future.result()
        print(f'{result.gremlin_id}: {result.status.value}')
```

---

## WorkerResult

Result from a worker process (serializable for multiprocessing).

::: pytest_gremlins.parallel.pool.WorkerResult
    options:
      show_root_heading: true
      show_source: true

### WorkerResult Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `gremlin_id` | `str` | ID of the tested gremlin |
| `status` | `GremlinResultStatus` | ZAPPED, SURVIVED, TIMEOUT, or ERROR |
| `killing_test` | `str \| None` | Test that killed the gremlin |
| `execution_time_ms` | `float \| None` | Execution time in milliseconds |

---

## PoolConfig

Configuration for optimized worker pool settings.

::: pytest_gremlins.parallel.pool_config.PoolConfig
    options:
      show_root_heading: true
      show_source: true

### PoolConfig Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_workers` | `int` | CPU count | Number of worker processes |
| `timeout` | `int` | `30` | Timeout per gremlin (seconds) |
| `start_method` | `StartMethod` | `'auto'` | Process start method |
| `warmup` | `bool` | `True` | Pre-warm workers on startup |
| `batch_size` | `int` | `10` | Gremlins per batch |

### Start Methods

| Method | Description | Platform |
|--------|-------------|----------|
| `'auto'` | Optimal for platform | All |
| `'spawn'` | Fresh interpreter (safest, slowest) | All |
| `'fork'` | Copy parent process (fast, unsafe with threads) | Unix |
| `'forkserver'` | Fork from pre-warmed server (recommended) | Unix |

### Usage Example

```python
from pytest_gremlins.parallel.pool_config import PoolConfig

# Create optimized configuration
config = PoolConfig(
    max_workers=8,
    timeout=60,
    start_method='forkserver',
    warmup=True,
    batch_size=20,
)

# Get multiprocessing context
ctx = config.get_mp_context()
print(ctx.get_start_method())  # 'forkserver'
```

### get_optimal_start_method

::: pytest_gremlins.parallel.pool_config.get_optimal_start_method
    options:
      show_root_heading: true
      show_source: true

---

## PersistentWorkerPool

Optimized worker pool that keeps workers alive across multiple gremlin tests.

::: pytest_gremlins.parallel.persistent_pool.PersistentWorkerPool
    options:
      show_root_heading: true
      show_source: true
      members:
        - "__init__"
        - from_config
        - max_workers
        - timeout
        - config
        - is_running
        - is_warmed_up
        - warmup_completed_count
        - submit
        - submit_batch

### Why Persistent Workers?

Standard approach (1 subprocess per gremlin):

```text
100 gremlins x 600ms startup = 60 seconds overhead
```

Persistent workers (reused processes):

```text
4 workers x 600ms startup = 2.4 seconds overhead
```

**25x reduction** in subprocess overhead.

### Usage Example

```python
from pytest_gremlins.parallel.pool_config import PoolConfig
from pytest_gremlins.parallel.persistent_pool import PersistentWorkerPool

config = PoolConfig(max_workers=4, warmup=True, start_method='forkserver')
pool = PersistentWorkerPool.from_config(config)

with pool:
    # Workers are warmed up
    print(f'Warmed up: {pool.is_warmed_up}')

    # Submit individual gremlins
    future = pool.submit(
        gremlin_id='g001',
        test_command=['pytest', '-x'],
        rootdir='/project',
        instrumented_dir='/tmp/inst',
        env_vars={},
    )
    result = future.result()

    # Or submit batches (even faster)
    batch_future = pool.submit_batch(
        gremlin_ids=['g002', 'g003', 'g004'],
        test_command=['pytest', '-x'],
        rootdir='/project',
        instrumented_dir='/tmp/inst',
        env_vars={},
    )
    batch_results = batch_future.result()
```

---

## BatchExecutor

Coordinates batch execution of gremlin tests for reduced subprocess overhead.

::: pytest_gremlins.parallel.batch_executor.BatchExecutor
    options:
      show_root_heading: true
      show_source: true
      members:
        - "__init__"
        - from_config
        - batch_size
        - max_workers
        - config
        - partition
        - execute

### Why Batch Execution?

Standard approach (1 subprocess call per gremlin):

```text
100 gremlins = 100 subprocess calls
100 x 600ms overhead = 60 seconds
```

Batch execution (batch_size=10):

```text
100 gremlins / 10 = 10 subprocess calls
10 x 600ms overhead = 6 seconds
```

**10x reduction** in subprocess overhead.

### Usage Example

```python
from pytest_gremlins.parallel.pool_config import PoolConfig
from pytest_gremlins.parallel.batch_executor import BatchExecutor

config = PoolConfig(max_workers=4, batch_size=20, warmup=True)
executor = BatchExecutor.from_config(config)

# Partition gremlins into batches
gremlin_ids = [f'g{i:03d}' for i in range(100)]
batches = executor.partition(gremlin_ids)
print(f'{len(batches)} batches of {executor.batch_size}')

# Execute all gremlins
results = executor.execute(
    gremlin_ids=gremlin_ids,
    test_command=['pytest', '-x', 'tests/'],
    rootdir='/path/to/project',
    instrumented_dir='/tmp/instrumented',
    env_vars={},
)

for result in results:
    print(f'{result.gremlin_id}: {result.status.value}')
```

---

## ResultAggregator

Thread-safe collection of results with progress tracking.

::: pytest_gremlins.parallel.aggregator.ResultAggregator
    options:
      show_root_heading: true
      show_source: true

### ResultAggregator Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `add_result(result)` | `None` | Add a worker result |
| `add_error(gremlin_id, error)` | `None` | Record an error |
| `get_results()` | `list[WorkerResult]` | Get all results (sorted) |
| `get_progress()` | `tuple[int, int]` | Get (completed, total) |

### ResultAggregator Properties

| Property | Type | Description |
|----------|------|-------------|
| `total_gremlins` | `int` | Total gremlins to test |
| `completed` | `int` | Completed count |
| `zapped_count` | `int` | Zapped gremlins |
| `survived_count` | `int` | Survived gremlins |
| `timeout_count` | `int` | Timed out gremlins |
| `error_count` | `int` | Error gremlins |
| `progress_percentage` | `float` | Progress (0.0 to 100.0) |

### Usage Example

```python
from pytest_gremlins.parallel.aggregator import ResultAggregator
from pytest_gremlins.parallel.pool import WorkerResult
from pytest_gremlins.reporting.results import GremlinResultStatus

aggregator = ResultAggregator(total_gremlins=100)

# Add results as they arrive
aggregator.add_result(WorkerResult(
    gremlin_id='g001',
    status=GremlinResultStatus.ZAPPED,
    killing_test='test_boundary',
))

# Progress reporting
completed, total = aggregator.get_progress()
print(f'Progress: {completed}/{total} ({aggregator.progress_percentage:.1f}%)')

# Final results
results = aggregator.get_results()
print(f'Zapped: {aggregator.zapped_count}')
print(f'Survived: {aggregator.survived_count}')
```

---

## Distribution Strategies

Strategies for distributing gremlins across workers.

### DistributionStrategy Protocol

::: pytest_gremlins.parallel.distribution.DistributionStrategy
    options:
      show_root_heading: true
      show_source: true

### RoundRobinDistribution

Simple round-robin assignment.

::: pytest_gremlins.parallel.distribution.RoundRobinDistribution
    options:
      show_root_heading: true
      show_source: true

```python
from pytest_gremlins.parallel.distribution import RoundRobinDistribution

strategy = RoundRobinDistribution()
gremlins = [g0, g1, g2, g3, g4]  # 5 gremlins
buckets = strategy.distribute(gremlins, num_workers=3)

# buckets[0] = [g0, g3]  # Worker 0
# buckets[1] = [g1, g4]  # Worker 1
# buckets[2] = [g2]      # Worker 2
```

### WeightedDistribution

Balances by test count (expensive gremlins distributed evenly).

::: pytest_gremlins.parallel.distribution.WeightedDistribution
    options:
      show_root_heading: true
      show_source: true

```python
from pytest_gremlins.parallel.distribution import WeightedDistribution

strategy = WeightedDistribution()

# Heavy gremlins (100 tests each) get distributed to different workers
test_counts = {
    'g0': 100,  # Heavy
    'g1': 100,  # Heavy
    'g2': 10,   # Light
    'g3': 10,   # Light
}

gremlins = [g0, g1, g2, g3]
buckets = strategy.distribute(gremlins, num_workers=2, test_counts=test_counts)

# buckets[0] = [g0, g2, g3]  # 100 + 10 + 10 = 120
# buckets[1] = [g1]          # 100
# Balanced workload!
```

---

## CLI Integration

Enable parallel execution via command line:

```bash
# Enable parallel execution (auto-detect workers)
pytest --gremlins --gremlin-parallel

# Specify worker count
pytest --gremlins --gremlin-parallel --gremlin-workers=8

# Enable batch mode
pytest --gremlins --gremlin-batch

# Customize batch size
pytest --gremlins --gremlin-batch --gremlin-batch-size=20

# Combine for maximum speed
pytest --gremlins --gremlin-parallel --gremlin-batch --gremlin-workers=8 --gremlin-batch-size=20
```

---

## Performance Comparison

| Mode | Subprocess Calls | Overhead | Best For |
|------|-----------------|----------|----------|
| Sequential | 1 per gremlin | High | Small projects |
| Parallel | 1 per gremlin | High (but concurrent) | Multi-core, many gremlins |
| Batch | 1 per batch | Low | Large test suites |
| Parallel + Batch | Batches in parallel | Lowest | Maximum speed |

### Example Timings

```text
Project: 1000 gremlins, 8 CPU cores

Sequential:           1000 x 600ms = 600 seconds
Parallel (8 workers): 1000 x 600ms / 8 = 75 seconds
Batch (size=10):      100 x 600ms = 60 seconds
Parallel + Batch:     100 x 600ms / 8 = 7.5 seconds

Speedup: 80x
```

---

## Best Practices

1. **Use forkserver on Unix** - Fastest subprocess creation
2. **Enable warmup** - Reduces latency on first batch
3. **Tune batch size** - Balance between overhead and early termination
4. **Match workers to cores** - No benefit beyond physical cores
5. **Monitor timeouts** - Increase if legitimate tests are timing out
