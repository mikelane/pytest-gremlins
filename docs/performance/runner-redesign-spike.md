# Runner redesign spike (#538)

Status: partial findings. This document records what the first pass of the spike measured and what it could not.
No production code changed.

## What is not done

- Design 1 (persistent pytest worker) is **not prototyped**. The fidelity suites were not run against it.
- All timings below were taken on a machine with a load average above 150, so absolute numbers are inflated
  and noisy. Only the relative ordering is trustworthy. Re-measure on an idle machine before quoting figures.

## What exists today

- `parallel/persistent_pool.py::_run_gremlin_batch` reuses a worker *process pool*, but each gremlin still
  runs `subprocess.run(test_command)`. It is a persistent pool of launchers, not a persistent pytest session,
  so none of design 1 exists yet. `--gremlin-batch` therefore does not reduce pytest startups.
- `build_lightweight_command` returns `None`, so the batch loop always takes the full bootstrap path.
- Node ids now travel through `--gremlins-node-ids-file` (#485), so any revival must read that file rather
  than scan argv for `::`.

## Bootstrap profile (design 3 input)

Plain suite: one module, two trivial tests, `python -m pytest -q -p no:cacheprovider`, Python venv of this
repository (pytest 9.1.1), under heavy machine load. Wall time per process, milliseconds, three runs each.

| Phase or variant | Measured ms | Note |
| --- | --- | --- |
| Interpreter start (`python -c pass`) | 97-116 | floor |
| `import pytest` | 773-839 | includes load-inflated import of pytest's own tree |
| Full run, plugin autoload on | 2937-3441 | |
| Full run, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` | 979-1366 | about 2.5x faster |
| `-p no:test_categories` | 1778 | one third-party plugin is about half of the extra cost |
| `-p no:cov`, `-p no:xdist`, `-p no:rerunfailures`, `-p no:pytest_gremlins` | no measurable change | within noise |

`-X importtime` ranks `pytest_test_categories` (and its `beartype` dependency) and `_pytest.assertion.rewrite`
as the largest import costs. The test run itself is under 0.1s.

Reading: on a plain suite most of the per-gremlin cost is importing pytest and *whichever third-party plugins
are installed*. The cost is dominated by the user's environment, not by pytest-gremlins.

## Design comparison

| Design | Fidelity cases it can guarantee | Estimated speedup | Risk |
| --- | --- | --- | --- |
| 3. Cheaper bootstrap | All. Same pytest, same hooks. Autoload and `-p no:` changes alter which plugins run, so they must not be applied silently. | Up to about 2.5x only if plugin autoload is disabled, which changes behavior for suites that need those plugins. Collecting only the selected files is already done through node ids. | Disabling plugins is a semantic change. Cannot be a default without a decision. |
| 1. Persistent pytest worker | Fixtures, hooks, conftest, `sys.path` behave as in a normal run on the first gremlin. Later gremlins reuse session state: module-level conftest state, session-scoped fixtures, `pytest_configure` side effects and import caches persist between gremlins. | Removes the whole bootstrap per gremlin (the 5.5x in the issue is the upper bound). | High. This is exactly the class of difference that produced fabricated verdicts in #486. Needs per-gremlin state reset that pytest does not provide. |
| 2. Fork after collect (paper only) | Child gets copy-on-write copies of the collected session, so state does not leak back to the parent. Conftest state is shared at fork time but isolated afterwards. | Similar to design 1. | Unix only. Threads, open sockets and C-extension state at fork time. Windows needs the bootstrap fallback. Needs maintainer approval (see issue). |

## Recommendation

1. Do design 3 first as pure measurement tooling: report, per run, how much of the per-gremlin cost is
   plugin import. Surface it to users as an advisory ("plugin X adds Y ms per gremlin"), without changing
   which plugins load. This adds no correctness surface.
2. Then prototype design 1 behind an experimental flag and run both fidelity suites against it. Until that
   data exists, the recommendation for designs 1 and 2 is "not yet safe enough".

Any default that disables plugins, or any new option, is a user-facing decision and is left to the maintainer.

## Cases that must fall back to the bootstrap (proposed)

Suites with conftest `pytest_runtest_*`, `pytest_pyfunc_call` or `pytest_runtest_makereport` hookwrappers,
`pytest_configure` side effects, session or module-scoped fixtures with external state, ini `pythonpath`,
async tests, and anything using `pytest.exit()`. This list is the full #486 inventory; a persistent worker
would need to prove each case identical to the bootstrap before leaving the list.

## Follow-ups

See the implementation issues linked from #538.
