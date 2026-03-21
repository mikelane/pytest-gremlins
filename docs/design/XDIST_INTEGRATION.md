# xdist Deep Integration Design

> **Issue:** #181 — `pytest --gremlins -n auto --cov` produces incorrect results
> **Status:** Implemented
> **Date:** 2026-02-20

---

## 1. The Problem

### What breaks

Running `pytest --gremlins -n auto` causes gremlins to run mutation testing against an
empty test suite. The mutation score is always 0% survived, 0% zapped — nothing happens.

Here is why.

When xdist is active, `DSession.pytest_collection` returns `True`. That truthy return
value is pytest's signal to skip collection in the calling process. So the controller
never collects any test items. `session.items` is empty when `pytest_collection_finish`
fires on the controller, which means `GremlinSession.total_tests = 0` and
`GremlinSession.test_node_ids = {}`. Every mutation subprocess then runs with no test
filter and no coverage data — it runs all tests, but the result is uncorrelated with
any coverage-guided selection.

The subprocess nesting makes it visually clear how far off the current model is:

```text
pytest (controller, --gremlins -n auto)
  ├── xdist worker gw0  (runs real tests, coverage tracked by pytest-cov)
  ├── xdist worker gw1  (runs real tests, coverage tracked by pytest-cov)
  ...
  └── pytest_sessionfinish fires on the controller
        ├── gremlins pre-scan subprocess  (coverage run -m pytest, no xdist)
        ├── gremlins mutation subprocess  (ACTIVE_GREMLIN=g001, no xdist)
        ├── gremlins mutation subprocess  (ACTIVE_GREMLIN=g002, no xdist)
        ...
```

The xdist workers run the tests correctly. Then gremlins fires in `pytest_sessionfinish`
with no knowledge of what the workers collected.

### The full list of problems

**A: Empty item list on the controller.**
Covered above. The root cause of the broken mutation run.

**B: xdist parallelism does nothing for mutations.**
The `-n auto` flag speeds up the initial test run that xdist handles. The mutation
phase spawns its own subprocesses via `ProcessPoolExecutor` — it does not use xdist at
all. So `-n auto` gives users the impression that mutations will run faster, but it only
speeds up the phase gremlins does not own.

**C: Coverage pre-scan does not suppress xdist.**
`_run_tests_with_coverage` runs `coverage run -m pytest -o addopts= ...`. The
`addopts=` override clears any `-n` set in `addopts`, but if the user has
`-n auto` in `pytest.ini` instead, it survives. The pre-scan needs
`-p no:xdist` explicitly, because `dynamic_context = test_function` does not
work across xdist workers — each worker writes a separate `.coverage` file, and
coverage contexts do not merge cleanly.

**D: `ACTIVE_GREMLIN` could leak into xdist workers if the architecture ever changes.**
Currently safe because gremlins only sets the env var inside mutation subprocesses,
after workers are done. But worth documenting as a constraint: xdist workers are
started before `pytest_sessionfinish`, so gremlins must never set `ACTIVE_GREMLIN`
in the controller process environment.

**E: Workers trigger gremlins hooks spuriously.**
Each xdist worker runs a full pytest session, including `pytest_collection_finish` and
`pytest_sessionfinish`. Gremlins hooks currently have no guard against running inside
a worker. Gremlins will attempt to instrument source code and run mutations inside
each worker process — this is silent waste at best, a crash at worst.

---

## 2. How xdist Actually Works (Verified from Source)

Before discussing the fix it is worth nailing down the facts, because the xdist
execution model is easy to get wrong.

**Workers are subprocesses, not forks.** `execnet` spawns workers via `popen` (a fresh
Python interpreter). The `__channelexec__` block at the bottom of `xdist/remote.py` is
the worker entry point — it receives config over a channel, calls `_prepareconfig`,
and runs the pytest session. Environment variables are not inherited from the controller
via fork. Workers get only what execnet explicitly sets (`PYTEST_XDIST_WORKER`,
`PYTEST_XDIST_WORKER_COUNT`, `PYTEST_XDIST_TESTRUNUID`) plus whatever was in the
environment when `popen` was called.

**The controller never collects items.** `DSession.pytest_collection` returns `True`,
which stops pytest's collection machinery in the controller. Workers collect items
independently and report their collections back via the `collectionfinish` event.
`DSession.worker_collectionfinish` receives these and feeds them to the scheduler.
`LoadScheduling._check_nodes_have_same_collection` aborts the run if any two workers
disagree.

**Workers reset their own xdist options.** `setup_config` in `remote.py` sets
`config.option.numprocesses = None` and `config.option.dist = "no"` inside each worker,
so workers never recurse into xdist.

**A worker is identifiable by `hasattr(config, 'workerinput')`.** This is how
pytest-cov does it. Does not require xdist to be installed on the gremlins side.

**`pytest_configure_node(node)` fires on the controller before each worker starts.**
`node.workerinput` is a dict that gets serialized and sent to the worker as
`config.workerinput`. This is how pytest-cov passes coverage config to workers — it is
the right injection point for anything a worker needs to know before collection starts.

**`pytest_xdist_node_collection_finished(node, ids)` fires on the controller per
worker.** `ids` is the list of test node ID strings from that worker. All workers
report identical lists (or the run aborts). This is the hook gremlins needs.

---

## 3. The Fix

### Chosen approach

Gremlins stays controller-side and out of xdist's way. The mutation subprocess
architecture does not change. What changes is how gremlins learns about the test items
and how it guards itself from running in worker processes.

Three concrete changes:

**1. Guard hooks against worker context.**

Add `_is_xdist_worker(config)` that checks `hasattr(config, 'workerinput')`. Return
early from `pytest_collection_finish` and `pytest_sessionfinish` when inside a worker.
This stops the spurious mutation runs in workers.

**2. Capture item IDs from `pytest_xdist_node_collection_finished`.**

Add `xdist_item_ids: list[str]` to `GremlinSession`. Implement the hook:

```python
def pytest_xdist_node_collection_finished(
    node: WorkerController,
    ids: Sequence[str],
) -> None:
    gremlin_session = _get_session()
    if gremlin_session is None or not gremlin_session.enabled:
        return
    # Use the first worker's collection — xdist guarantees all are identical.
    if not gremlin_session.xdist_item_ids:
        gremlin_session.xdist_item_ids = list(ids)
```

Then in `pytest_sessionfinish`, if `xdist_item_ids` is non-empty, use it to populate
`test_node_ids` and `total_tests`. When xdist is not active, `xdist_item_ids` is empty
and `session.items` is used as today — no change to the non-xdist path.

The source discovery, gremlin generation, and instrumented source writing currently in
`pytest_collection_finish` need to move into `pytest_sessionfinish` for the xdist path,
since `pytest_collection_finish` fires before any tests run but after workers have
reported back — the timing works, but only if we restructure the hook. Specifically:
`pytest_collection_finish` should become a no-op when xdist is active (detected by
`config.option.dist != 'no'`), and `pytest_sessionfinish` must do the full setup when
`xdist_item_ids` is populated.

**3. Add `-p no:xdist` to the coverage pre-scan subprocess.**

One line change in `_run_tests_with_coverage`:

```python
cmd = [
    sys.executable, '-m', 'coverage', 'run',
    f'--rcfile={coveragerc_path}',
    '-m', 'pytest',
    '-o', 'addopts=',
    '-p', 'no:xdist',    # prevents -n from pytest.ini surviving the addopts= override
    *test_node_ids,
    '--tb=no', '-q',
]
```

### Why not the fancier approaches

**Synthetic pytest items per `(mutation_id, test_node_id)` pair:** Every worker would
need to collect the same synthetic items, meaning every worker would need access to the
fully-instrumented source tree before collection. The bootstrap-script architecture
exists because the import hook must be installed before any `import` fires — you cannot
retrofit that into a worker that is already importing. Also, N_mutations × M_tests items
in the collection would make xdist's collection-equality check fragile, and the item
count shown to users would be meaningless.

**Custom `pytest_xdist_make_scheduler`:** A scheduler controls which items go to which
workers, but it cannot change what items are collected. The scheduler's `schedule()`
method is called after collection completes but before tests run — too early for
coverage data to exist. The coverage pre-scan dependency cannot be satisfied there.

**Disable xdist when `--gremlins` is active:** This works and is easy. The user
experience is bad if they have `-n auto` in `addopts` for normal test runs — they would
lose parallelism entirely when running mutation tests. Worth offering as a short-term
fallback with a warning:

> `pytest-gremlins: xdist detected but not yet fully supported. Disabling xdist for
> this run. Track #181 for native integration.`

This could ship faster than the full fix while #181 is in progress.

### What stays the same

The mutation subprocess architecture is unchanged. Each mutation still runs via the
bootstrap script with `ACTIVE_GREMLIN` set in the subprocess environment.
`ProcessPoolExecutor` still handles parallelism. The `-n N` flag still maps to
`parallel_workers` via `_resolve_parallel_from_xdist` — that plumbing already exists
and works correctly.

### Architecture diagram

```text
pytest --gremlins -n 4 --cov
│
├─ pytest_configure
│   └─ GremlinSession created (enabled=True, parallel_workers=4)
│
├─ DSession.pytest_sessionstart
│   └─ NodeManager spawns gw0..gw3 (fresh subprocesses, not forks)
│       Each worker independently:
│         ├─ collects tests
│         ├─ fires "collectionfinish" → pytest_xdist_node_collection_finished on controller
│         ├─ runs assigned tests (pytest-cov accumulates coverage per worker)
│         └─ fires "workerfinished" → controller
│
├─ pytest_xdist_node_collection_finished  [NEW]
│   └─ GremlinSession.xdist_item_ids = ids  (from first worker)
│
├─ DSession.pytest_runtestloop
│   └─ drives scheduler until all 4 workers done, then pytest_sessionfinish fires
│
├─ pytest_sessionfinish  (controller only — returns early inside workers)  [CHANGED]
│   ├─ Populate test_node_ids and total_tests from xdist_item_ids  [NEW]
│   ├─ Discover source files, generate gremlins, write instrumented dir
│   ├─ _collect_coverage subprocess  (single-process, -p no:xdist)  [CHANGED]
│   └─ _run_parallel_mutation_testing  (ProcessPoolExecutor, 4 workers)
│       ├─ bootstrap subprocess (ACTIVE_GREMLIN=g001)
│       ├─ bootstrap subprocess (ACTIVE_GREMLIN=g002)
│       ...
│
└─ pytest_terminal_summary
    └─ mutation score
```

---

## 4. Open Questions

**Hook ordering for `pytest_sessionfinish`.** When both gremlins and xdist are active,
`DSession.pytest_sessionfinish` calls `nm.teardown_nodes()` to shut down workers.
Gremlins' `pytest_sessionfinish` spawns mutation subprocesses. These need to fire in
the right order — gremlins after xdist tears down workers, not before or during.
pytest's hook ordering for `pytest_sessionfinish` is not documented with the same
precision as `tryfirst`/`trylast` allows. This needs a test to confirm the ordering is
safe, not just assumed.

**What if `pytest_xdist_node_collection_finished` never fires** (e.g. the user presses
Ctrl-C during collection, or collection fails). `xdist_item_ids` would be empty and
`pytest_sessionfinish` would proceed with `session.items` — which is also empty on the
controller. Gremlins should detect this and emit a warning rather than silently running
with no tests.

**`pytest_collection_finish` currently does source discovery and gremlin generation.**
Moving these to `pytest_sessionfinish` for the xdist path means the xdist branch of
`pytest_sessionfinish` needs to do: populate `test_node_ids`, discover source files,
generate gremlins, write instrumented dir, run pre-scan, run mutations — all in one
hook. The non-xdist path has this split across two hooks. The refactor needs to avoid
duplicating that logic. The cleanest approach is a shared `_setup_gremlin_session()`
function called from whichever hook is appropriate.

**`--dist=loadscope` and `--dist=loadfile` affect test ordering on workers** but not
the item list itself. Gremlins does not care about ordering of the initial test run —
it builds its own ordered list from coverage data. No special handling needed.

**The `pytest_configure_node` path (a possible Phase 2).** Rather than running mutation
subprocesses, gremlins could inject the instrumented sources and the gremlin assignment
into each worker via `node.workerinput` before the worker starts — similar to how
pytest-cov passes coverage config. Workers would then register the `GremlinFinder`
import hook in their own `pytest_configure` phase and run their assigned gremlin
in-process. This eliminates the mutation subprocess layer entirely and gives gremlins
a genuine in-process xdist integration. It requires coverage data to be available
before workers start, which means the pre-scan must run before `DSession.pytest_sessionstart`
— a non-trivial ordering change. Worth designing separately once the current fix is stable.

---

## 5. Implementation Plan

Five sub-issues, each independently mergeable. A through D fix the bug; E validates it.

### A: Guard hooks against worker context

Add `_is_xdist_worker(config: pytest.Config) -> bool` that checks
`hasattr(config, 'workerinput')`. Add early returns to `pytest_collection_finish` and
`pytest_sessionfinish` when inside a worker.

No behavior change on any currently-working invocation. Test by verifying that running
`pytest --gremlins -n 2` does not spawn mutation subprocesses from inside worker
processes.

### B: Capture item IDs from workers

Add `xdist_item_ids: list[str]` to `GremlinSession`. Implement
`pytest_xdist_node_collection_finished`. In `pytest_sessionfinish`, prefer
`xdist_item_ids` over `session.items` when the list is non-empty.

Test: `pytest --gremlins -n 2` against a fixture project, assert
`GremlinSession.total_tests > 0`.

### C: Move source discovery to `pytest_sessionfinish` for the xdist path

Extract a `_setup_gremlin_session_items(session, gremlin_session)` function that
handles source discovery, gremlin generation, and instrumented dir creation. Call it
from both `pytest_collection_finish` (non-xdist path) and `pytest_sessionfinish`
(xdist path, after populating `test_node_ids` from `xdist_item_ids`).
`pytest_collection_finish` returns early when `config.option.dist != 'no'`.

Test: verify correct gremlin count in both paths.

### D: Suppress xdist in the coverage pre-scan

Add `-p no:xdist` to `_run_tests_with_coverage`. Test: add `-n auto` to `addopts` in
a fixture project's `pyproject.toml`, verify the pre-scan returns non-empty coverage
data.

This sub-issue has no dependency on A, B, or C. Can merge in any order.

### E: End-to-end test for `--gremlins -n 2 --cov`

A medium or large test (using `pytester`) against a minimal fixture:

- 3 source functions with comparison mutations
- 5 tests with known coverage overlap
- `pytest --gremlins -n 2 --cov` completes without error
- Mutation score is non-zero
- Coverage report is not corrupted (`.coverage` file has expected content)

---

## 6. Compatibility

| Invocation | Current behaviour | After this fix |
|-----------|-----------------|----------------|
| `pytest --gremlins` | Correct | Unchanged |
| `pytest --gremlins -n auto` | Broken (0 mutations tested) | Fixed |
| `pytest --gremlins -n 4` | Broken | Fixed |
| `pytest --gremlins -n auto --cov` | Broken + pre-scan fragile | Fixed |
| `pytest --gremlins --gremlin-parallel` | Correct (deprecation warning if xdist present) | Unchanged |
| `pytest -n auto` (no `--gremlins`) | Correct | Unchanged |

No new CLI flags. No new dependencies. xdist is not modified.

---

## 7. Files to Change

| File | What changes |
|------|-------------|
| `src/pytest_gremlins/plugin.py` | `_is_xdist_worker`, `pytest_xdist_node_collection_finished`, guards in `pytest_collection_finish` and `pytest_sessionfinish`, `-p no:xdist` in pre-scan command, `xdist_item_ids` field on `GremlinSession` |
| `tests/plugin/` | Sub-issue A, B, C, D tests (medium) and Sub-issue E end-to-end test (large) |
