# Cache Module

The cache module implements **incremental analysis**, the third pillar of pytest-gremlins' speed
strategy. Results are cached keyed by content hashes, allowing unchanged code/tests to be skipped
on subsequent runs.

## Overview

Traditional mutation testing runs all gremlins every time:

```text
Run 1: 1000 gremlins tested (5 minutes)
Run 2: 1000 gremlins tested (5 minutes)  # No changes
Run 3: 1000 gremlins tested (5 minutes)  # 1 file changed
```

Incremental analysis skips unchanged code:

```text
Run 1: 1000 gremlins tested (5 minutes)
Run 2: 0 gremlins tested (0 seconds)     # Cache hit
Run 3: 10 gremlins tested (30 seconds)   # Only changed file
```

## Module Exports

```python
from pytest_gremlins.cache import (
    CachedGremlinResult,  # TypedDict for cached result shape
    ContentHasher,        # SHA-256 content hashing
    IncrementalCache,     # Cache coordinator
    ResultStore,          # SQLite-backed result cache
)
```

---

## ContentHasher

Produces deterministic SHA-256 hashes for files and strings.

::: pytest_gremlins.cache.hasher.ContentHasher
    options:
      show_root_heading: true
      show_source: true

### ContentHasher Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `hash_string(content)` | `str` | Hash a string (64 hex chars) |
| `hash_file(path)` | `str` | Hash a file's content |
| `hash_files(paths)` | `dict[str, str]` | Hash multiple files |
| `hash_combined(hashes)` | `str` | Combine multiple hashes |

### Helper modules under the test root

A test's verdict can depend on code the test file never names: a fixture module loaded through `pytest_plugins`, a
helper that a test or a `conftest.py` imports, or a helper defined inside another test file. The cache key covers all
three.

**Helper modules.** pytest-gremlins hashes every Python file under the test root that is not a test file into the cache
key of each test file there. The test root is the top-level directory under the pytest rootdir that holds the test file
(for example `tests/`). A test file that sits directly in the rootdir has no directory to sweep, so only the `.py` files
beside it count. A file is a test file when its name matches the `python_files` setting (default `test_*.py` and
`*_test.py`); that is decided by the name alone, never by what pytest collected in the run. So a test file has the same
key whether you run it alone or with the whole suite. `conftest.py` files (hashed separately along the path to each
test) and `__pycache__` are skipped.

The trade-off is coarse on purpose: **editing any helper under the test root re-runs gremlins for every test file
under that root.** The cost is extra misses after a helper edit. Python files outside the test root do not affect the
key.

**Imported test files.** Other test files that a test, or a `conftest.py` on its path, imports are hashed into its key
too, so editing `make()` in `tests/test_b.py` re-runs the gremlins of a `tests/test_a.py` that imports it. pytest-gremlins
reads each file's `import x`, `from x import y` and relative imports with `ast`, resolves them to `.py` files under the
test root, and follows them transitively (import cycles are safe). A module named in a module-level `pytest_plugins`
assignment (a string, or a list or tuple of strings) counts as an import, so a test-named fixture module loaded that way
is in the key. An absolute import is looked up from rootdir, from each directory between the importing file and
rootdir, and from each `pythonpath` entry in your pytest ini (resolved against rootdir). Source with a byte-order mark
or a `coding:` declaration is read correctly. A file that cannot be parsed contributes nothing.
A test file that nothing imports does not affect other files' keys.

**Limit: dynamic imports are not followed.** A test file reached only through `importlib.import_module` with a computed
name, or any other import resolved at run time, is not in the key. Editing it replays the cached verdicts of the files
that load it. Import it statically, or clear the cache with `--gremlin-clear-cache` after editing one.

### Usage Example

```python
from pathlib import Path
from pytest_gremlins.cache import ContentHasher

hasher = ContentHasher()

# Hash a string
code = 'def foo(): return 42'
hash1 = hasher.hash_string(code)
print(hash1)  # 64-character hex string

# Hash a file
file_hash = hasher.hash_file(Path('src/module.py'))

# Hash multiple files
hashes = hasher.hash_files([
    Path('src/module.py'),
    Path('tests/test_module.py'),
])
# {'src/module.py': 'abc...', 'tests/test_module.py': 'def...'}

# Combine hashes for composite keys
combined = hasher.hash_combined([hash1, file_hash])
```

### Hash Properties

- **Deterministic**: Same content always produces same hash
- **Collision-resistant**: Different content produces different hashes
- **Fast**: SHA-256 is hardware-accelerated on modern CPUs
- **Fixed-size**: Always 64 hexadecimal characters

---

## ResultStore

SQLite-backed cache for gremlin test results.

::: pytest_gremlins.cache.store.ResultStore
    options:
      show_root_heading: true
      show_source: true

### ResultStore Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get(cache_key)` | `dict \| None` | Retrieve cached result |
| `put(cache_key, result)` | `None` | Store result (immediate commit) |
| `put_deferred(cache_key, result)` | `None` | Store result (batch commit) |
| `flush()` | `None` | Commit all deferred writes |
| `has(cache_key)` | `bool` | Check if key exists |
| `delete(cache_key)` | `None` | Remove single entry |
| `delete_by_prefix(prefix)` | `None` | Remove entries by prefix |
| `prune_stale_source_hashes(current_hashes)` | `None` | Remove rows whose source hash is not a current hash of their file prefix |
| `clear()` | `None` | Remove all entries |
| `keys()` | `list[str]` | Get all cache keys |
| `count()` | `int` | Get entry count |
| `close()` | `None` | Close database connection |

### Usage Example

```python
from pathlib import Path
from pytest_gremlins.cache import ResultStore

# Create store (creates parent directories if needed)
store = ResultStore(Path('.gremlins_cache/results.db'))

# Store a result (immediate commit)
store.put('g001:abc123:def456', {
    'status': 'zapped',
    'killing_test': 'test_boundary',
    'execution_time_ms': 150.5,
})

# Retrieve a result
result = store.get('g001:abc123:def456')
if result:
    print(f"Status: {result['status']}")

# Batch operations (faster for bulk inserts)
for i in range(100):
    store.put_deferred(f'key_{i}', {'value': i})
store.flush()  # Single commit for all 100

# Clean up
store.close()
```

### Context Manager

```python
from pathlib import Path
from pytest_gremlins.cache import ResultStore

with ResultStore(Path('.cache/results.db')) as store:
    store.put('key', {'data': 'value'})
# Automatically closes on exit
```

### Database Schema

```sql
CREATE TABLE results (
    cache_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
);
```

### Error Recovery

If the database is corrupted, `ResultStore` automatically:

1. Detects the corruption on open
2. Logs a warning
3. Deletes the corrupted file
4. Creates a fresh database

---

## IncrementalCache

Coordinates content hashing and result storage for smart cache invalidation.

::: pytest_gremlins.cache.incremental.IncrementalCache
    options:
      show_root_heading: true
      show_source: true

### IncrementalCache Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_cached_result(gremlin_id, source_hash, test_hashes)` | `dict \| None` | Get cached result |
| `cache_result(gremlin_id, source_hash, test_hashes, result)` | `None` | Cache result (immediate) |
| `cache_result_deferred(...)` | `None` | Cache result (batch) |
| `flush()` | `None` | Commit deferred writes |
| `invalidate_file(file_prefix)` | `None` | Invalidate file's gremlins |
| `prune_stale_sources(current_hashes)` | `None` | Delete rows stranded by an edited source file |
| `clear()` | `None` | Clear entire cache |
| `get_stats()` | `dict` | Get hit/miss statistics |
| `close()` | `None` | Close and release resources |

### Cache Key Structure

Cache keys incorporate three components:

```text
{gremlin_id}:{source_hash}:{combined_test_hash}
```

| Component | Changes When |
|-----------|--------------|
| `gremlin_id` | Never (uniquely identifies mutation) |
| `source_hash` | Source file content changes |
| `combined_test_hash` | Any covering test file changes |

The cache also records which code produced its verdicts: an internal cache version, and every distribution that
provides a `pytest_gremlins.operators` entry point or owns the module of an operator registered for the run
(including operators a `conftest.py` registers). Upgrading pytest-gremlins keeps the cache, unless the release
changes how verdicts are computed and raises the cache version (then the first run is cold). Installing, removing,
upgrading or downgrading an operator package invalidates it. Old entries stop matching; they remain in `results.db`
until pruning ([#871](https://github.com/mikelane/pytest-gremlins/issues/871)).

Two sessions add a part to the key so that only they miss once after an upgrade: one that loads the pytester plugin
adds `pytester-615` (#891), and one whose gremlin runs load pytest-xdist themselves because plugin autoload is
disabled adds `xdist-668` (#668). Earlier versions could report false kills for tests using `worker_id` or
`testrun_uid` when xdist was loaded with `-p xdist.plugin` (spaced or joined) on the command line, or when
`--disable-plugin-autoload` came with `-p pytest_rerunfailures` in `addopts`, because the gremlin runs went without
xdist. A session that keeps autoload on but inherits `-p no:xdist` and loads xdist on its command line gets the part as
well (#685). Other sessions with the part just re-test once. Every other session keeps its key.

### Invalidation Rules

| Change | Cache Effect |
|--------|--------------|
| Source file modified | Miss for all gremlins in that file |
| Test file modified | Miss for gremlins covered by that test |
| New test added | Miss for gremlins the new test covers |
| Test deleted | Miss for gremlins that test was zapping |
| pytest-gremlins upgraded | Hit, unless the release raised the cache version (then a miss for every gremlin) |
| Distribution providing a `pytest_gremlins.operators` entry point installed, removed or changed version | Miss for every gremlin (old entries stop matching) |
| Installed package (including a PEP 610 editable install) that owns the module of a `conftest.py`-registered operator changes version | Miss for every gremlin (old entries stop matching) |
| Operator defined in a `conftest.py` that is registered as a plugin (its module is named `conftest` or ends in `.conftest` and its file is such a `conftest.py`, or a function in its class body comes from one). An operator from an installed package whose module is merely named `conftest` is not one: it is keyed by the package version, including one that subclasses the `GremlinOperator` protocol or is a dataclass | Hits stay intact while no loaded `conftest.py` changes. The versions part of every key gets one `conftest-operators=` label that hashes every `conftest.py` registered as a plugin when the cache opens (the rootdir's and those of the command-line arguments, such as `a/` and `b/` in `pytest a b`): its path, relative to the rootdir or absolute outside it, and its content. Editing any of them is a miss for every gremlin, wherever the operator's code comes from (a decorator or a method borrowed from another `conftest.py`). The test key alone hashes only the `conftest.py` files on the path to each covering test, so a gremlin covered only by tests in a sibling directory would otherwise replay a stale verdict. A loaded `conftest.py` that cannot be read misses on every run. A `conftest.py` pytest loads later, during collection, is not in the label. Helper modules a `conftest.py` imports are not in it either ([#924](https://github.com/mikelane/pytest-gremlins/issues/924)). An operator in a `conftest.py` that an installed package ships and registers as a plugin (`-p pkg.conftest`, a `pytest11` entry point or `pytest_plugins`) also keeps its `pkg==<version>` label, so an upgrade that changes only another file of the package is a miss. A project with no such operator gets the same keys as before |
| Operator that does not come from an installed distribution: a project-local helper module, a module loaded by file path or sharing a name with another module, a namespace-package module (unless an installed distribution in that namespace sits at the same top-level name), a class defined inside a function, a module with no file, or an editable install recorded only through a `.pth` file or a setuptools import finder | Every run misses the cache for every gremlin: the key carries a fresh random token, so the run is slower but never serves a stale verdict. The run also writes no results to the cache, since no later run could read them, so `results.db` does not grow. An operator keeps hits only when it is importable by its qualified name and an installed package owns its module. Restoring cache hits for the others is tracked in [#887](https://github.com/mikelane/pytest-gremlins/issues/887). An operator from an installed distribution still keys on that distribution's version |
| Helper module under the test root edited, added or removed: a `pytest_plugins` fixture module, or a module a test or `conftest.py` imports | Miss for every gremlin covered by any test file under that test root. The key folds in every `.py` file there whose name matches no `python_files` pattern, other than a `conftest.py` or a file under `__pycache__` |
| Helper code inside a test file edited, imported (statically) by another test file or its `conftest.py` | Miss for every gremlin covered by the importing test file. A test file imported only dynamically is not followed. See [Helper modules under the test root](#helper-modules-under-the-test-root) |
| Python file outside the test root edited, and not a source file a gremlin mutates | No effect on the key |
| Nothing changed | Hit (return cached result) |

A regular installed distribution owns an operator's module only when the distribution's install record (`RECORD` or
`installed-files.txt`) lists the module's file. A source checkout's `SOURCES.txt` is not an install record, so a
checkout on `sys.path` with a leftover `<pkg>.egg-info` and an unrecorded file in a shared namespace package both miss.
A PEP 660 editable install's `RECORD` lists only a `.pth` or finder file, so an editable install (PEP 610
`direct_url.json`) owns a module instead when the module's file is under the editable project directory and the
module's top-level name is in the install's `top_level.txt`. A helper elsewhere under an editable project directory
misses. An editable install without `top_level.txt` (non-setuptools backends such as hatchling,
uv_build, flit and pdm) always misses, because its `.pth` directory can hold packages the wheel does not
ship. Setuptools editables and normal wheels keep stable keys. An empty `RECORD` or `installed-files.txt` counts as
no install record. A `.egg` install has no install record, so it misses; zip installs keep their version label.

### Pruning stranded rows

Editing a source file changes its hash, so every row cached for that file stops matching. At the start of each run,
the controller process deletes, for each target file in the run, the rows whose gremlin id belongs to that file but
whose source-hash segment is not the file's current hash. The delete is one transaction and an indexed range scan on
the primary key, anchored on `{stem}_{path_hash}_g<digits>:` so a longer stem cannot be caught by mistake. Rows for
files outside the run are kept, unless the file shares a gremlin prefix with a file in the run (see below). Rows with
the current hash under any other key part are kept. `results.db` therefore
holds at most one source version per file instead of growing with every edit. xdist workers and
`--gremlin-parallel` workers never prune or write the cache. There is no flag or config key for it, and the key
format and `CACHE_VERSION` are unchanged.

Switching branches can cost hits: a branch that edits a file prunes the rows of the other branch's version of it, so
switching back re-tests that file's gremlins. Rows for deleted or renamed files and rows keyed by an old `v=` part are
not pruned.

A file left out of the run keeps its rows unless it shares a gremlin prefix with a file in the run. That means the
same file name and the same first 4 hex characters of the path hash, which is rare. Then its rows may be pruned. This
costs one cache miss for those gremlins and never changes a verdict.

### Usage Example

```python
from pathlib import Path
from pytest_gremlins.cache import IncrementalCache

cache = IncrementalCache(Path('.gremlins_cache'))

# Define content hashes
source_hash = 'abc123...'  # Hash of source file
test_hashes = {
    'test_login': 'def456...',  # Hash of test file
    'test_logout': 'ghi789...',
}

# Try to get cached result
result = cache.get_cached_result(
    gremlin_id='g001',
    source_hash=source_hash,
    test_hashes=test_hashes,
)

if result is not None:
    print(f"Cache hit: {result['status']}")
else:
    # Run the test
    actual_result = run_mutation_test('g001')

    # Cache the result
    cache.cache_result(
        gremlin_id='g001',
        source_hash=source_hash,
        test_hashes=test_hashes,
        result={
            'status': actual_result.status.value,
            'killing_test': actual_result.killing_test,
            'execution_time_ms': actual_result.execution_time_ms,
        },
    )

# Check statistics
stats = cache.get_stats()
print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")

cache.close()
```

### Batch Caching

For better performance during mutation testing runs:

```python
cache = IncrementalCache(Path('.gremlins_cache'))

# Use deferred writes (batched commits)
for gremlin_id, result in results:
    cache.cache_result_deferred(
        gremlin_id=gremlin_id,
        source_hash=source_hashes[gremlin_id],
        test_hashes=test_hashes[gremlin_id],
        result=result,
    )

# Single commit for all results
cache.flush()
cache.close()
```

### Context Manager

```python
from pathlib import Path
from pytest_gremlins.cache import IncrementalCache

with IncrementalCache(Path('.gremlins_cache')) as cache:
    result = cache.get_cached_result('g001', 'abc', {'test': 'def'})
# Automatically closes
```

---

## CLI Integration

Enable caching via command line:

```bash
# Enable incremental caching
pytest --gremlins --gremlin-cache

# Clear cache and start fresh
pytest --gremlins --gremlin-cache --gremlin-clear-cache
```

### Cache Location

By default, cache is stored in `.gremlins_cache/` in the project root:

```text
.gremlins_cache/
└── results.db    # SQLite database
```

---

## Performance Impact

### Example Scenario

```text
Initial run (cold cache):
  1000 gremlins x 50ms average = 50 seconds

Second run (no changes):
  1000 cache hits x 0.1ms lookup = 0.1 seconds

After changing one 50-gremlin file:
  50 cache misses x 50ms = 2.5 seconds
  950 cache hits x 0.1ms = 0.1 seconds
  Total: 2.6 seconds (vs 50 seconds without cache)
```

### Best Practices

1. **Enable caching in development** - Faster feedback during TDD
2. **Disable in CI** - Start fresh for authoritative results
3. **Clear cache after refactoring** - Major changes may confuse the cache
4. **Monitor hit rates** - Low hit rates may indicate frequent test changes
