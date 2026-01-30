# API Reference

This section documents the complete public API of pytest-gremlins, a fast-first mutation testing plugin for pytest.

## Architecture Overview

pytest-gremlins achieves speed through four architectural pillars:

| Pillar | Module | Description |
|--------|--------|-------------|
| Mutation Switching | `instrumentation` | Instrument code once, toggle mutations via environment variable |
| Coverage-Guided Selection | `coverage` | Run only tests that cover the mutated code |
| Incremental Analysis | `cache` | Skip unchanged code/tests on subsequent runs |
| Parallel Execution | `parallel` | Distribute gremlins across worker processes |

## Module Map

```
pytest_gremlins/
├── __init__.py           # Package info, version
├── config.py             # Configuration loading
├── plugin.py             # pytest plugin hooks
│
├── operators/            # Mutation operators
│   ├── protocol.py       # GremlinOperator protocol
│   ├── registry.py       # Operator registration
│   ├── arithmetic.py     # +, -, *, / mutations
│   ├── boolean.py        # and/or, True/False mutations
│   ├── boundary.py       # Off-by-one mutations
│   ├── comparison.py     # <, <=, >, >= mutations
│   └── return_value.py   # Return statement mutations
│
├── instrumentation/      # AST transformation
│   ├── gremlin.py        # Gremlin dataclass
│   ├── transformer.py    # AST transformer
│   ├── switcher.py       # Environment-based switching
│   ├── finder.py         # Mutation point finder
│   └── import_hooks.py   # Import interception
│
├── coverage/             # Coverage-guided selection
│   ├── mapper.py         # Line-to-test mapping
│   ├── collector.py      # Coverage data collection
│   ├── selector.py       # Test selection
│   └── prioritized_selector.py  # Prioritized selection
│
├── cache/                # Incremental analysis
│   ├── hasher.py         # Content hashing
│   ├── store.py          # SQLite result cache
│   └── incremental.py    # Cache coordinator
│
├── parallel/             # Parallel execution
│   ├── pool.py           # Worker pool
│   ├── pool_config.py    # Pool configuration
│   ├── persistent_pool.py # Persistent workers
│   ├── batch_executor.py # Batch execution
│   ├── distribution.py   # Work distribution
│   └── aggregator.py     # Result aggregation
│
└── reporting/            # Result reporting
    ├── results.py        # GremlinResult dataclass
    ├── score.py          # MutationScore aggregation
    ├── console.py        # Terminal output
    ├── html.py           # HTML reports
    └── json_reporter.py  # JSON reports
```

## Quick Navigation

### Core Plugin

- [Plugin Module](plugin.md) - pytest hooks and session management
- [Configuration](plugin.md#configuration) - Loading config from pyproject.toml

### Mutation Operators

- [Operators Module](operators.md) - All mutation operators
    - [GremlinOperator Protocol](operators.md#protocol)
    - [OperatorRegistry](operators.md#registry)
    - [Built-in Operators](operators.md#built-in-operators)

### Instrumentation

- [Instrumentation Module](instrumentation.md) - AST transformation and switching
    - [Gremlin Dataclass](instrumentation.md#gremlin)
    - [Source Transformation](instrumentation.md#transformer)
    - [Import Hooks](instrumentation.md#import-hooks)

### Coverage

- [Coverage Module](coverage.md) - Coverage-guided test selection
    - [CoverageMap](coverage.md#coveragemap)
    - [TestSelector](coverage.md#testselector)
    - [PrioritizedSelector](coverage.md#prioritizedselector)

### Cache

- [Cache Module](cache.md) - Incremental analysis caching
    - [ContentHasher](cache.md#contenthasher)
    - [ResultStore](cache.md#resultstore)
    - [IncrementalCache](cache.md#incrementalcache)

### Parallel Execution

- [Parallel Module](parallel.md) - Worker pools and distribution
    - [WorkerPool](parallel.md#workerpool)
    - [PersistentWorkerPool](parallel.md#persistentworkerpool)
    - [BatchExecutor](parallel.md#batchexecutor)

### Reporting

- [Reporting Module](reporting.md) - Result presentation
    - [GremlinResult](reporting.md#gremlinresult)
    - [MutationScore](reporting.md#mutationscore)
    - [Reporters](reporting.md#reporters)

## Domain Language

pytest-gremlins uses a playful "gremlins" theme throughout its API:

| Traditional Term | Gremlin Term | Description |
|------------------|--------------|-------------|
| Original code | **Mogwai** | The innocent, unmutated code |
| Mutant | **Gremlin** | A mutation injected into code |
| Kill mutant | **Zap** | Test catches the mutation |
| Surviving mutant | **Survivor** | Test gap found |
| Start mutation testing | **Feed after midnight** | Enable with `--gremlins` |

## Quick Start Example

```python
# Run mutation testing from command line
# pytest --gremlins

# Programmatic access to operators
from pytest_gremlins.operators import OperatorRegistry, ComparisonOperator

registry = OperatorRegistry()
registry.register(ComparisonOperator)

# Transform source code
from pytest_gremlins.instrumentation import transform_source

source = '''
def is_adult(age):
    return age >= 18
'''
gremlins, tree = transform_source(source, 'example.py')
print(f'Found {len(gremlins)} gremlins')

# Work with results
from pytest_gremlins.reporting import MutationScore, GremlinResultStatus

# score = MutationScore.from_results(results)
# print(f'Mutation score: {score.percentage:.1f}%')
```

## Package Info

::: pytest_gremlins
    options:
      show_root_heading: true
      show_source: false
      members:
        - __version__
