# Verdicts and Exit Codes

This page explains how pytest-gremlins decides each gremlin's verdict, which code it mutates,
and what pytest's exit code means after a `--gremlins` run. The version in parentheses is the
release whose changelog entry describes the behavior; see the [Changelog](../changelog.md) for
details.

## How a Gremlin Is Scored

Each gremlin's selected tests run in a separate pytest subprocess with the gremlin active. The
subprocess's exit code decides the verdict:

| Subprocess result | Verdict | Counts toward the score as |
|-------------------|---------|----------------------------|
| Exit 0: every selected test passed | `survived` | a miss |
| Exit 1: a selected test failed | `zapped` | a kill |
| The mutant stopped the suite from loading (a conftest import error, a collection error, a changed parametrize id) | `zapped`, with killing test `<collection>` | a kill |
| The run went over the per-mutant timeout, and the unmutated tests finish within half of it | `timeout` | a kill |
| Any other exit code, or a timeout that isn't confirmed | `error` | a miss (it stays in the denominator) |
| An inline `# gremlin: pardon[...]` pragma covers the line | `pardoned` | left out of the score |

The mutation score is `(zapped + timeout) / (total - pardoned) * 100`; see
[Understanding Mutation Score](reports.md#understanding-mutation-score). For how timeouts are
confirmed, see [Error: Test timeout exceeded](troubleshooting.md#error-test-timeout-exceeded).

### Crashes Before Any Test Runs Are Errors (v1.12.0)

If the gremlin subprocess crashes outside a test, for example because a plugin fails to register
at startup, it exits 3 (pytest's internal-error code) and the gremlin is scored `error`, not
`zapped`. Its error output starts with:

```text
pytest-gremlins: the gremlin subprocess crashed outside a test, so pytest did not finish: <cause>
```

If the subprocess can't find its instrumented sources because `PYTEST_GREMLINS_SOURCES_FILE` is
not set, it prints `Error: PYTEST_GREMLINS_SOURCES_FILE not set` and exits 4, and the gremlin is
scored `error` too.

### Selected Tests Without a Node Id Are Errors (v1.11.1)

Coverage selects tests by name. A selected test that can't be matched to a pytest node id, for
example because of an unusual parametrize id, is not run. A gremlin left with no runnable
selected test is scored `error` instead of borrowing a verdict from other tests. Once per run,
stderr reports how many tests were dropped:

<!-- markdownlint-disable MD013 -->
```text
pytest-gremlins: <N> selected test(s) for <M> gremlin(s) have no pytest node id and were not run, e.g. <test>. Gremlins left with no runnable test are scored ERROR.
```
<!-- markdownlint-enable MD013 -->

To see the dropped tests for one gremlin, use
[`--gremlin-explain`](configuration.md#explaining-a-survivor).

## What Gets Mutated

- **Test files are skipped (v1.11.3).** Inside a target directory, files named `test_*.py`,
  `*_test.py` or `conftest.py` are not mutated. A file is mutated anyway when you name it
  explicitly in `--gremlin-targets` or `paths`. You don't need `exclude` patterns for test
  files.
- **Modules that pytest rewrites assertions in are mutated (v1.11.3).** That covers a
  `conftest.py` named as a target, modules matching a custom `python_files` pattern, and packages
  passed to `pytest.register_assert_rewrite`. Plugins that pytest loads before it reads
  `conftest.py` files (through `-p` in `addopts`, entry points or `PYTEST_PLUGINS`) are not
  instrumented.
- **`multiprocessing` children run the mutated code (v1.11.4).** Children started with `spawn`
  (the default on macOS and Windows) or `forkserver` load the instrumented code, so a test that
  catches a gremlin through a child process zaps it. A child running a different Python version
  or implementation from pytest's still runs the original code.
- **Files that can't be instrumented are reported (v1.11.4).** Each one prints
  `pytest-gremlins: skipped <path>: could not instrument (<Type>: <message>)` and is left out of
  the score.

## The Coverage Pre-Scan

Before any gremlin runs, pytest-gremlins runs the suite once under coverage.py to learn which
tests cover which lines. The pre-scan pins coverage.py's `ctrace` core and ignores a
`COVERAGE_CORE` or `COVERAGE_FILE` set in your environment (v1.10.1). pytest-cov options
(`--cov*`, `--no-cov*`) in `addopts` are stripped from the pre-scan and the gremlin runs, so they
don't need to be removed for `--gremlins`.

## pytest's Exit Code

- **Survivors don't fail the run.** pytest's exit code is the same as it would be without
  `--gremlins`, however many gremlins survive. To fail CI on a low score, check
  `summary.percentage` in the [JSON report](reports.md#json-report).
- **A failing baseline skips mutation testing.** If any test fails or errors, collection fails,
  or the run stops early, pytest-gremlins prints
  `pytest-gremlins: skipping mutation testing because <reason>` to stderr and runs no gremlins.
  pytest's exit code is unchanged. A failing non-test check such as `--cov-fail-under` doesn't
  block mutation testing (v1.10.1).
- **Pardon checks exit 1.** `--strict-pardons` ends the run with exit code 1 when any gremlin is
  pardoned. `--gremlin-max-pardons-pct` and `--max-pardons` end it with exit code 1 when their
  limit is exceeded.
- **Invalid configuration exits 4 (v1.11.0).** A bad `[tool.pytest-gremlins]` value, an
  out-of-range `--gremlin-*` value, or `--gremlin-executor=fork`/`inprocess` stops the run with
  a usage error before any test runs. See
  [Configuration Validation](configuration.md#configuration-validation).
