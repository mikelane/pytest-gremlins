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

A throwaway harness (not merged) collects once and re-runs the collected items in one pytest session, three
rounds, through `pytest_runtest_protocol`. Its source is on the `issue-538-design1-prototype` branch under
`prototypes/issue-538-design1/`; run `python proto.py suite 3` from a directory outside the repository. It checks
five cases that the fidelity suites cover as classes of difference from the bootstrap. Verdict compared with a
fresh bootstrap run of the same suite, where all five pass. The environment toggle case
changes the active-gremlin toggle each round (`round1`, `round2`, `round3`) and records the value each test sees.

| Case | Round 1 | Rounds 2 and 3 | Matches bootstrap |
| --- | --- | --- | --- |
| Plain test | pass | pass | yes |
| Module-level state (counter in the test module) | pass | fail | no |
| Session-scoped fixture used once per gremlin | pass | pass (rebuilt each round) | yes, but setup cost repeats |
| Conftest counters (`pytest_configure` runs once, session fixture rebuilt each round) | pass | fail | no |
| Environment toggle read per run | pass | pass (saw `round1`, `round2`, `round3`) | yes |

Measured per-round cost for five tests, over three runs of five rounds on a busy machine:

| Round | Cost |
| --- | --- |
| Round 1 | about 2ms |
| Round 2 | about 26 to 30ms (the first failing reports are built here) |
| Round 3 and later | about 3 to 4ms |

A bootstrap costs about 415 to 500ms. The speedup is real, and it is the upper bound the issue quotes. Two of
five cases give a different verdict from the bootstrap. A mutation that survives only because a second run sees
leaked state, or is killed only because of it, would produce a wrong verdict.

### Fidelity suites against the prototype

The prototype is wired into the gremlin command path on the throwaway branch only (never merged). With
`GREMLINS_PROTO_PERSISTENT=1`, `_test_gremlin` keeps one pytest session per distinct test command, sends it the
active gremlin id, and reads back pass or fail, after collecting once. Both suites ran to completion
and all 13 cases pass, but only 11 of the 13 cases went through the prototype. The `[parallel]` and `[batch]`
cases never reach it: `_test_gremlin` is called only from `plugin.py`, the code in `parallel/` has no prototype
hook, and the worker log shows 0 spawns and 0 reuses for both. They passed through the bootstrap. For the 11 cases
that did, the run created 17 sessions and reused a session 17 times, so the reuse path was exercised.

| Suite | Test | Result |
| --- | --- | --- |
| `test_runner_fidelity.py` | `it_zaps_every_mutant_whatever_the_test_style[default]` | pass |
| `test_runner_fidelity.py` | `it_zaps_every_mutant_whatever_the_test_style[parallel]` | pass (bootstrap, not the prototype) |
| `test_runner_fidelity.py` | `it_zaps_every_mutant_whatever_the_test_style[batch]` | pass (bootstrap, not the prototype) |
| `test_runner_fidelity.py` | `it_runs_every_style_of_test_body_against_a_mutant` | pass |
| `test_runner_fidelity.py` | `it_leaves_every_mutant_survived[fixture]` | pass |
| `test_runner_fidelity.py` | `it_leaves_every_mutant_survived[parametrized]` | pass |
| `test_runner_fidelity.py` | `it_still_zaps_with_a_fixture_taking_test_that_covers_the_target` | pass |
| `test_runner_fidelity.py` | `it_does_not_count_a_hook_dependent_test_as_a_kill` | pass |
| `test_runner_conftest_and_path_fidelity.py` | `it_does_not_count_a_conftest_dependent_test_as_a_kill[module_level]` | pass |
| `test_runner_conftest_and_path_fidelity.py` | `it_does_not_count_a_conftest_dependent_test_as_a_kill[pytest_configure]` | pass |
| `test_runner_conftest_and_path_fidelity.py` | `it_does_not_count_a_failed_lazy_helper_import_as_a_kill` | pass |
| `test_runner_conftest_and_path_fidelity.py` | `it_zaps_with_a_test_that_imports_a_sibling_helper` | pass |
| `test_runner_conftest_and_path_fidelity.py` | `it_zaps_with_a_test_whose_helper_is_on_the_pytest_ini_pythonpath` | pass |

The suites also cannot tell whether a reused worker switches to the new gremlin: with the per-round toggle removed,
a reused worker stays on the first gremlin it was spawned with and the prototype still passes `[default]`, the
`survived[fixture]` case, conftest `module_level` and the sibling-helper case. A control that always reports 0 does
fail, so the worker's verdict is used. #803 must close this gap too.

This does not show that design 1 is safe. The two suites do not cover cross-gremlin state leakage: each of their
suites has few gremlins and no test that fails when it is run a second time in the same session, while the
harness above shows module-level and conftest state failing on round 2. The suites check that a run reports the
same verdict as the bootstrap for one pass over each test. #803 must add a leakage case to the fidelity suites
before a persistent worker can claim to pass them.

## Design comparison

| Design | Fidelity cases it can guarantee | Estimated speedup | Risk |
| --- | --- | --- | --- |
| 3. Cheaper bootstrap | All. Same pytest, same hooks. Autoload and `-p no:` changes alter which plugins run, so they must not be applied silently. | Up to about 2.5x only if plugin autoload is disabled, which changes behavior for suites that need those plugins. | Disabling plugins is a semantic change. Cannot be a default without a decision. |
| 1. Persistent pytest worker | Measured: plain tests, env toggles that change each round; session fixtures are rebuilt. Not guaranteed: module-level state, `pytest_configure` side effects and import caches persist between gremlins. | Removes the bootstrap per gremlin: about 3 to 4ms per round from round 3 (about 26 to 30ms in round 2) against about 415 to 500ms. | High until isolation exists. This class of difference produced fabricated verdicts in #486. |
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

## Open questions for the maintainer

These are decisions, not work for the spike. They are also listed on #803.

- Is a Unix-only fork-after-collect (design 2) acceptable, given that Windows is a supported platform? Without a
  yes, design 2 stays on paper.
- Is an option that disables plugin autoload (`PYTEST_DISABLE_PLUGIN_AUTOLOAD`) or unloads individual plugins
  acceptable, given that it changes which plugins a suite runs under? It is the largest design 3 gain (about
  2.5x) and a semantic change.
- What is the experimental flag for the persistent worker (#803), and may it ship as opt-in?
