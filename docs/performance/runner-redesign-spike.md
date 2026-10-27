# Runner redesign spike (#538)

No production code changed. This document records what the spike measured, what a throwaway prototype of design 1
showed, and the follow-up issues.

## What exists today

- `parallel/persistent_pool.py::_run_gremlin_batch` reuses a worker *process pool*, but each gremlin still
  runs `subprocess.run(test_command)`. It is a persistent pool of launchers, not a persistent pytest session,
  so none of design 1 exists yet. `--gremlin-batch` therefore does not reduce pytest startups.
- `build_lightweight_command` returns `None`, so the batch loop always takes the full bootstrap path.
- Node ids now travel through an internal node ids file argument (#485), so any revival must read that file rather
  than scan argv for `::`.

## Bootstrap profile (design 3 input)

Plain suite: one module, two trivial tests, `python -m pytest -q -p no:cacheprovider`, Python venv of this
repository (pytest 9.1.1), macOS. Wall time per process in milliseconds, nine runs each, minimum and median.
Load average at the start of the run: 6.4 (1 minute), 10.9 (5 minutes). The machine was not idle, so read the
figures as relative costs. An earlier pass at load 16 to 20 gave figures about twice as high, which shows how
much the load moves absolute numbers.

| Phase or variant | Min ms | Median ms |
| --- | --- | --- |
| Interpreter start (`python -c pass`) | 16 | 21 |
| `import pytest` | 103 | 103 |
| `pytest --version` (no plugin is imported, same cost as `import pytest`) | 103 | 124 |
| `--collect-only` (config, plugins, collection) | 422 | 482 |
| Full run, all plugins | 415 | 497 |
| Full run, `-p no:gremlins` | 363 | 421 |
| Full run, `-p no:test_categories` | 252 | 278 |
| Full run, `-p no:gremlins -p no:test_categories` | 186 | 221 |
| Full run, `-p no:cov -p no:xdist` | 392 | 444 |
| Full run, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` | 163 | 198 |

The plugin's pytest11 entry point is named `gremlins`, so the flag that unloads it is `-p no:gremlins`.
`pytest --version` exits before plugins are loaded, so it measures the same cost as `import pytest`. Plugin
cost shows up only in the full-run rows.

Where the roughly 415 to 500ms goes, from these rows:

- Interpreter start: about 20ms.
- `import pytest`: about 80ms more.
- Config, plugin load and collection on top of that, with all plugins: about 300 to 400ms. Plugin load for the
  installed plugins is most of it: autoload off runs in about 165 to 200ms in total.
- pytest-gremlins' own plugin: about 55 to 75ms (min 415 against 363, median 497 against 421). This is
  measurable cost the project controls (#802).
- `pytest_test_categories` and its `beartype` dependency: about 160 to 220ms. It is a third-party plugin.
- The test run itself is under 0.1s.

The `--collect-only` row is about as large as the full run, so collection and its imports cost about as much
as everything else after plugin load. Config, plugin load and collection are not separable with these wall-time
rows alone; `-X importtime` would be needed to split them.

## Design 1 prototype results

A throwaway harness (not merged, not wired into the plugin) collects once and re-runs the collected items in
one pytest session, three rounds, through `pytest_runtest_protocol`. Its source is on the
`issue-538-design1-prototype` branch under `prototypes/issue-538-design1/`; run `python proto.py suite 3`. It
checks five cases that the fidelity suites cover as classes of difference from the bootstrap. Verdict compared
with a fresh bootstrap run of the same
suite, where all five pass.

| Case | Round 1 | Rounds 2 and 3 | Matches bootstrap |
| --- | --- | --- | --- |
| Plain test | pass | pass | yes |
| Module-level state (counter in the test module) | pass | fail | no |
| Session-scoped fixture used once per gremlin | pass | pass (rebuilt each round) | yes, but setup cost repeats |
| Conftest counters (`pytest_configure` runs once, session fixture rebuilt each round) | pass | fail | no |
| Environment toggle read per run | pass | pass | yes |

Per-round cost after the first: 2 to 4ms for five tests, against about 415 to 500ms for a bootstrap. The speedup
is real, and it is the upper bound the issue quotes. Two of five cases give a different verdict from the bootstrap.
A mutation that survives only because a second run sees leaked state, or is killed only because of it, would
produce a wrong verdict.

Not done: the two fidelity suites (`tests/integration/test_runner_fidelity.py` and
`tests/integration/test_runner_conftest_and_path_fidelity.py`) were not run against the prototype, because
they drive the real CLI and the prototype is not wired into the gremlin command path. This leaves the third
acceptance criterion only partly met. Wiring the prototype in is a production-path change, which the spike's
time limit and its no-production-code rule do not allow, so the spike stops here and #803 carries it. The table
above is the pass/fail list the spike can honestly give.

## Design comparison

| Design | Fidelity cases it can guarantee | Estimated speedup | Risk |
| --- | --- | --- | --- |
| 3. Cheaper bootstrap | All. Same pytest, same hooks. Autoload and `-p no:` changes alter which plugins run, so they must not be applied silently. | Up to about 2.5x only if plugin autoload is disabled, which changes behavior for suites that need those plugins. | Disabling plugins is a semantic change. Cannot be a default without a decision. |
| 1. Persistent pytest worker | Measured: plain tests, env toggles; session fixtures are rebuilt. Not guaranteed: module-level state, `pytest_configure` side effects and import caches persist between gremlins. | Removes the bootstrap per gremlin: 2 to 4ms per round against about 415 to 500ms. | High until isolation exists. This class of difference produced fabricated verdicts in #486. |
| 2. Fork after collect (paper only) | Child gets copy-on-write copies of the collected session, so state does not leak back to the parent. | Similar to design 1. | Unix only. Threads, open sockets and C-extension state at fork time. Windows needs the bootstrap fallback. Needs maintainer approval (see issue). |

## One subprocess per batch (scope addition from #733)

Today a batch of N gremlins costs N bootstraps, as described above. One subprocess per batch means starting
pytest once, then selecting each gremlin's tests and recording its verdict inside that process. That is design 1
with a batch as the lifetime of the worker, so it inherits the same isolation problem: between gremlins in a
batch, module-level and configure-time state must be reset or the suite must fall back. Estimated gain: a batch
of N saves N minus 1 bootstraps, about 415 to 500ms each on a plain suite. It is not safe to build before design 1
isolation exists, so it is filed as #804 and blocked by #803.

Recommendation: pursue design 1 as an opt-in, correct-or-abstain persistent worker (#803), with one subprocess
per batch (#804) as its first consumer, and keep design 2 on paper. Design 3 work (#802) is advisory measurement
tooling and is not a speedup on its own.

## Cases that must fall back to the bootstrap (proposed)

Suites with conftest `pytest_runtest_*`, `pytest_pyfunc_call` or `pytest_runtest_makereport` hookwrappers,
`pytest_configure` side effects, module-level mutable state in test or conftest modules, session or
module-scoped fixtures with external state, ini `pythonpath`, async tests, and anything using `pytest.exit()`.
The persistent worker must prove each case identical to the bootstrap before leaving this list.

Any default that disables plugins, or any new option, is a user-facing decision and is left to the maintainer.

## Follow-ups

- #802: report per-plugin bootstrap cost as an advisory (design 3 input).
- #803: persistent pytest worker behind an experimental flag, run against both fidelity suites. Blocked on the
  maintainer decision about the flag.
- #804: one subprocess per `--gremlin-batch` batch. Blocked by #803.
