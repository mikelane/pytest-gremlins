# Configuration

pytest-gremlins can be configured via command-line options or `pyproject.toml`. This page
documents all configuration options with examples.

## Configuration Precedence

Configuration values are resolved in this order (highest priority first):

1. **Command-line options** -- Flags passed to pytest (e.g., `--gremlin-targets`)
2. **pyproject.toml** -- `[tool.pytest-gremlins]` section

When the same option is specified at both levels, the CLI value wins. This applies to all nine
configurable fields (operators, paths, exclude, workers, cache, report, batch_size, max_pardons,
max-pardons-pct), as well as `coverage_timeout` / `--gremlin-coverage-timeout` and
`mutant_timeout` / `--gremlin-mutant-timeout`.

**Source path auto-discovery** is a separate mechanism that kicks in only when neither
`--gremlin-targets` nor `[tool.pytest-gremlins] paths` is set. It tries seven strategies in
order (see [Troubleshooting](#troubleshooting-configuration) for the full list).

## Command-Line Options Reference

All command-line options are prefixed with `--gremlin` or `--gremlins`.

### Core Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--gremlins` | flag | `false` | Enable mutation testing |
| `--gremlin-operators` | string | all | Comma-separated list of operators to use |
| `--gremlin-targets` | string | auto-discovered | Comma-separated list of files/directories to mutate (see [precedence](#configuration-precedence)) |
| `--gremlin-exclude` | string | none | Glob pattern to exclude from mutation (repeatable, overrides pyproject.toml) |
| `--gremlin-report` | string | `console` | Report format: `console`, `html`, or `json` (repeatable: pass multiple times to combine formats) |

### Performance Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--gremlin-cache` | flag | `false` | Enable incremental analysis cache |
| `--gremlin-clear-cache` | flag | `false` | Clear cache before running |
| `--gremlin-parallel` | flag | `false` | Enable parallel mutation execution |
| `--gremlin-workers` | integer | CPU count | Number of parallel workers (implies `--gremlin-parallel`) |
| `--gremlin-batch` | flag | `false` | Enable batch execution mode |
| `--gremlin-batch-size` | integer | `10` | Number of gremlins per batch |
| `--gremlin-coverage-timeout` | integer | `120` | Seconds (1-86400) the coverage pre-scan may run before coverage-guided test selection is disabled |
| `--gremlin-mutant-timeout` | integer | `30` | Seconds (1-86400) one attempt of a gremlin's test run may take before the gremlin is reported as a timeout; scaled up when pytest-rerunfailures reruns are configured ([details](#flaky-tests-and-pytest-rerunfailures)) |

### Output Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--gremlins-html-dir` | string | `coverage/gremlins/` | Custom output directory for the HTML report |

### Pardon Enforcement Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--strict-pardons` | flag | `false` | Treat pardoned gremlins as CI failures |
| `--gremlin-audit-pardons` | flag | `false` | List all active suppression pragmas with location, reason, and justification |
| `--gremlin-max-pardons-pct` | float | disabled | Fail if pardoned gremlins exceed this percentage of total |
| `--max-pardons` | integer | disabled | Fail if absolute pardoned gremlin count exceeds N |

### Usage Examples

**Basic mutation testing:**

```bash
pytest --gremlins
```

**Target specific files:**

```bash
pytest --gremlins --gremlin-targets=src/auth.py,src/api.py
```

**Target a directory:**

```bash
pytest --gremlins --gremlin-targets=src/mypackage
```

**Exclude files matching a glob pattern:**

```bash
pytest --gremlins --gremlin-exclude="**/migrations/*"
```

**Exclude multiple patterns (repeatable flag):**

```bash
pytest --gremlins --gremlin-exclude="**/migrations/*" --gremlin-exclude="**/generated/*"
```

**Use specific operators only:**

```bash
pytest --gremlins --gremlin-operators=comparison,boolean
```

**Generate HTML report:**

```bash
pytest --gremlins --gremlin-report=html
```

**Generate both HTML and JSON reports (repeatable flag):**

```bash
pytest --gremlins --gremlin-report=html --gremlin-report=json
```

**Custom HTML output directory:**

```bash
pytest --gremlins --gremlin-report=html --gremlins-html-dir=reports/mutations
```

**Enable incremental caching:**

```bash
pytest --gremlins --gremlin-cache
```

**Clear cache and run fresh:**

```bash
pytest --gremlins --gremlin-cache --gremlin-clear-cache
```

**Enable parallel execution (use all CPU cores):**

```bash
pytest --gremlins --gremlin-parallel
```

**Parallel with specific worker count:**

```bash
pytest --gremlins --gremlin-workers=4
```

**Enable batch mode for reduced overhead:**

```bash
pytest --gremlins --gremlin-batch --gremlin-batch-size=20
```

**Audit all active pardon pragmas:**

```bash
pytest --gremlins --gremlin-audit-pardons
```

**Treat pardoned gremlins as failures (strict mode):**

```bash
pytest --gremlins --strict-pardons
```

**Combine multiple options:**

```bash
pytest --gremlins \
    --gremlin-targets=src/core \
    --gremlin-exclude="**/migrations/*" \
    --gremlin-operators=comparison,boundary \
    --gremlin-cache \
    --gremlin-parallel \
    --gremlin-report=html
```

## pyproject.toml Configuration

Configure pytest-gremlins in your `pyproject.toml` file under the `[tool.pytest-gremlins]` section.

### Complete Configuration Reference

```toml
[tool.pytest-gremlins]
# Paths to scan for source files to mutate
# Optional: auto-discovered from setuptools metadata, falling back to src/
paths = ["src", "lib"]

# Glob patterns for files to exclude from mutation
# Default: []
exclude = [
    "**/migrations/*",
    "**/test_*",
    "**/__pycache__/*",
    "**/conftest.py",
]

# Operators to enable (in order of priority)
# Default: all operators
operators = [
    "comparison",
    "boundary",
    "boolean",
    "arithmetic",
    "return",
]

# Number of parallel workers (integer or "auto" for os.cpu_count())
# Default: 1 (sequential)
workers = "auto"

# Enable incremental analysis cache
# Default: false
cache = true

# Report format(s): a single string, comma-separated string, or list
# Valid formats: "console", "html", "json"
# Default: "console"
report = ["html", "json"]

# Number of gremlins per batch in batch execution mode
# Default: 10
batch_size = 20

# Seconds the coverage pre-scan may run before coverage-guided test selection
# is disabled (raise it for slow suites)
# Default: 120
coverage_timeout = 300

# Seconds one gremlin's test run may take before the gremlin is reported
# as a timeout (raise it when a survivor's covering tests take longer)
# Default: 30
mutant_timeout = 120

# Maximum number of pardoned gremlins (absolute ceiling)
# Default: no limit
max_pardons = 10

# Maximum percentage of pardoned gremlins (0-100)
# Default: no limit
max-pardons-pct = 5.0
```

### Configuration Options Table

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `paths` | list[string] | auto-discovered | Directories or files to scan for source code (falls back to `src/`) |
| `exclude` | list[string] | `[]` | Glob patterns for files to exclude |
| `operators` | list[string] | all | Operators to enable, in priority order |
| `workers` | int or `"auto"` | sequential | No parallelism unless `-n` or `--gremlin-parallel` is used; `"auto"` resolves to `os.cpu_count()` |
| `cache` | boolean | `false` | Enable incremental analysis cache |
| `report` | string or list | `"console"` | Report format(s): `"html"`, `"json"`, `"console"`, or a list like `["html", "json"]` |
| `batch_size` | int | `10` | Number of gremlins per batch in batch execution mode |
| `coverage_timeout` | int | `120` | Seconds (1-86400) the coverage pre-scan may run; on expiry gremlins warns and runs every test per gremlin |
| `mutant_timeout` | int | `30` | Seconds (1-86400) one attempt of a gremlin's test run may take before the gremlin is reported as a timeout; scaled up when pytest-rerunfailures reruns are configured ([details](#flaky-tests-and-pytest-rerunfailures)) |
| `max_pardons` | int | no limit | Absolute ceiling on pardoned gremlins |
| `max-pardons-pct` | float | no limit | Maximum percentage of pardoned gremlins (0-100) |

### Example Configurations

**Minimal configuration:**

```toml
[tool.pytest-gremlins]
paths = ["src"]
```

**Django project:**

```toml
[tool.pytest-gremlins]
paths = ["myapp"]
exclude = [
    "**/migrations/*",
    "**/admin.py",
    "**/apps.py",
]
operators = ["comparison", "boolean", "return"]
```

**Library with multiple packages:**

```toml
[tool.pytest-gremlins]
paths = ["src/mylib", "src/mylib_extras"]
exclude = [
    "**/_compat.py",
    "**/deprecated/*",
]
```

**Focused on high-value mutations:**

```toml
[tool.pytest-gremlins]
paths = ["src"]
operators = ["comparison", "boundary"]  # Only boundary-related bugs
```

## Excluding Code from Mutation

Use glob patterns in `pyproject.toml` to exclude files from mutation testing:

```toml
[tool.pytest-gremlins]
exclude = [
    "**/migrations/*",      # Django migrations
    "**/test_*",            # Test files
    "**/conftest.py",       # pytest configuration
    "**/__pycache__/*",     # Cache directories
    "**/vendor/*",          # Vendored dependencies
]
```

## Inline Pardoning

Some gremlins produce code that behaves identically to the original (equivalent mutants), or
exercise paths you deliberately chose not to test. Rather than letting these inflate your
survivor count, you can **pardon** them with an inline pragma.

### Pragma Syntax

The pragma can appear in two positions:

**Same line** -- after the code it pardons:

```python
return a // b  # gremlin: pardon[equivalent] integer division rounds same as subtraction
```

**Line above** -- on a standalone comment line immediately above the code:

```python
# gremlin: pardon[equivalent] integer division rounds same as subtraction
return a // b
```

The line-above form is useful when the same-line form would push past your line-length
limit. Both forms require the pragma to be adjacent to the code -- a blank line between
a line-above pragma and the code it targets will cause the pragma to be ignored with a
warning.

The pragma has three parts:

1. `# gremlin: pardon` -- the keyword (must be `pardon`, not `survivor`)
2. `[reason]` -- one of the valid reason codes (see below)
3. Free-text justification -- explains *why* this gremlin is pardoned

If both a line-above and same-line pragma target the same code line, the same-line
pragma takes precedence.

### Reason Codes

| Code | When to use |
|------|-------------|
| `equivalent` | The mutation produces identical behavior to the original code |
| `untestable` | The mutation affects code that cannot be exercised in a unit test (e.g., defensive `except` around OS calls) |
| `out_of_scope` | The mutation is in code you intentionally exclude from quality targets |

### Examples

```python
# Same-line form (short justifications)
flags = set(items) | set(extras)  # gremlin: pardon[equivalent] union is commutative

# Line-above form (when same-line would exceed line length)
# gremlin: pardon[untestable] OS-level failure path requires hardware fault to trigger
except OSError:
    raise SystemExit(1)

# gremlin: pardon[out_of_scope] legacy adapter scheduled for removal in Q3
return legacy_convert(data)
```

### Enforcing Pardon Limits

Pardons are useful, but too many can silently inflate your mutation score. Use limits to
keep them in check:

**CLI flags:**

```bash
pytest --gremlins --max-pardons=10                 # fail if more than 10 pardons
pytest --gremlins --gremlin-max-pardons-pct=5.0    # fail if pardons exceed 5% of total
```

**pyproject.toml:**

```toml
[tool.pytest-gremlins]
max_pardons = 10
max-pardons-pct = 5.0
```

When either limit is exceeded, pytest-gremlins exits with a non-zero status and reports
which limit was violated.

### Migrating from `survivor` to `pardon`

In v1.5.0, the pragma keyword changed from `survivor` to `pardon`. The old keyword no
longer works. Update existing pragmas:

```python
# Old (no longer recognized)
x = val  # gremlin: survivor[equivalent] ...

# New
x = val  # gremlin: pardon[equivalent] ...
```

A project-wide find-and-replace handles this:

```bash
# Preview changes
grep -rn 'gremlin: survivor\[' src/

# Apply
sed -i 's/gremlin: survivor\[/gremlin: pardon\[/g' src/**/*.py
```

## Performance Tuning

### Incremental Caching

Enable caching to skip unchanged code on subsequent runs:

```bash
pytest --gremlins --gremlin-cache
```

The cache is stored in `.gremlins_cache/` in your project root. Cache keys include:

- Source file content hash
- Test file content hash
- Gremlin ID
- Effective mutant timeout, the optimize level and the pytest-rerunfailures budget (`reruns` and `reruns_delay`)

When source or test files change, affected gremlins are re-tested.

**Clear the cache:**

```bash
pytest --gremlins --gremlin-cache --gremlin-clear-cache
```

### Parallel Execution

Use `--gremlin-parallel` to distribute mutations across multiple worker processes. Specifying a
worker count with `--gremlin-workers=N` automatically enables parallel mode:

```bash
pytest --gremlins --gremlin-parallel        # use all CPU cores
pytest --gremlins --gremlin-workers=4       # use 4 workers (implies --gremlin-parallel)
```

`--gremlin-parallel` without `--gremlin-workers` defaults to `os.cpu_count()` workers.
`--gremlin-workers=1` runs sequentially (useful for debugging).

Since v1.5.0, `--gremlins` and `-n` (pytest-xdist) work together via a **two-phase integration**:

- **Phase 1** distributes the test suite across xdist workers (the normal `-n auto` behavior)
- **Phase 2** uses xdist's resolved worker count for parallel mutation evaluation

This means `-n auto` is sufficient for both test distribution and mutation parallelism:

```bash
pytest --gremlins -n auto              # recommended: automatic parallelism
pytest --gremlins -n 4                 # explicit worker count
```

`--gremlin-workers` and `--gremlin-parallel` still work as standalone alternatives when you do
not want xdist involved in test distribution:

```bash
pytest --gremlins --gremlin-parallel   # use all CPU cores (no xdist)
pytest --gremlins --gremlin-workers=4  # specific worker count (no xdist)
```

The coverage pre-scan that drives coverage-guided test selection always runs as a single,
non-distributed pytest process, because coverage.py does not trace xdist workers. Gremlins strips
every pytest-xdist option (`-n`, `--numprocesses`, `--maxprocesses`, `--dist`, `--tx`, and the rest)
from your `addopts` and from the `PYTEST_ADDOPTS` environment variable for that run, so `-n auto`
no longer produces an empty coverage map. The xdist plugin itself stays loaded and runs in-process,
so its `worker_id` and `testrun_uid` fixtures and hooks keep working.

Every per-gremlin test run is stripped the same way. The gremlin import hook is installed only in the
process that runs each gremlin, so xdist workers would import your original, unmutated code and every
gremlin would be reported as a survivor. With `addopts = "-n 2"` (or `PYTEST_ADDOPTS="-n 2"`) the tests
for each gremlin therefore run in-process, not in workers; your `-n` setting still sizes the mutation
worker pool.

As a second layer, per-gremlin runs force `-n 0` whenever pytest-xdist is loaded. pytest keeps the last
value of `-n`, so this also covers spellings the option stripper cannot see, such as a clustered
`addopts = "-xn 2"` or `PYTEST_ADDOPTS="-xn 2"`. xdist stays loaded, so `worker_id` still works. Without
xdist installed, nothing is added.

### Flaky Tests and pytest-rerunfailures

A gremlin is zapped when a test that covers it fails. A flaky test that fails for reasons unrelated to the
mutation would therefore zap every gremlin it covers, inflating your mutation score with kills your tests did not
earn.

If [pytest-rerunfailures](https://github.com/pytest-dev/pytest-rerunfailures) is installed, per-gremlin runs use
the same rerun settings as your baseline run, so a gremlin is zapped only when the test fails on every attempt:

- Options in `addopts` and `PYTEST_ADDOPTS` reach per-gremlin runs as they always did.
- The rerun ini settings (`reruns`, `reruns_delay`, `reruns_delay_backoff_factor`, `only_rerun`, `rerun_except`)
  reach them too. Without `-c`/`--config-file`, a gremlin run finds the same project config file you did and
  reads the settings itself; gremlins forwards nothing. With `-c` or `--config-file` (also through
  `PYTEST_ADDOPTS` or an `@file`), the gremlin runs cannot read that file, so gremlins passes each setting that
  is set as `--override-ini`, and a rerun option typed on the command line still wins over the file, as in pytest.
- With `-c`, a gremlin run finds the project's own config file (`pytest.ini`, `pyproject.toml`...), which your
  baseline never read. So under `-c`, gremlins also resets each rerun key that the `-c` file leaves unset, or that
  it cannot carry (next item), with an empty `--override-ini`. Empty means what your baseline ran with: no
  filter for `only_rerun` and `rerun_except`, no reruns for `reruns`, and no delay and a backoff factor of 1.0 for
  `reruns_delay` and `reruns_delay_backoff_factor`. So the project file can neither restrict reruns nor make the
  gremlin runs wait where your baseline did not. Every rerun key is either forwarded or reset. A key that a
  rerun option already sets is left alone, wherever the option comes from: the command line, the `addopts` of the
  `-c` file or `PYTEST_ADDOPTS`. pytest-rerunfailures reads the option before the ini key, and gremlin runs receive
  those `addopts` themselves. (A `-c` that reaches the gremlin runs through `PYTEST_ADDOPTS` is read by them.)
- pytest strips each line of a list value given with `-o`, splits it at line breaks and drops empty lines. Under
  `-c`, an `only_rerun` or `rerun_except` list with an empty item, or an item that has leading or trailing
  whitespace, a line break or a NUL byte (possible in a TOML list such as `rerun_except = ["xyz "]`), would
  reach the gremlin runs changed, and a changed pattern reruns fewer failures than your baseline did. So
  gremlins does not forward that key: it resets it to no filter and prints
  `pytest-gremlins: warning: the ini setting 'rerun_except' is not carried into gremlin runs ...`.
  The gremlin runs then rerun more failures than the baseline, so a gremlin your tests would zap can survive,
  but a flaky test never zaps one it should not. To avoid this, remove the whitespace, line breaks, NUL bytes
  and empty items from the list, or put the config in a file pytest finds without `-c`.
  The warning is not printed when `--only-rerun` or `--rerun-except` (from the command line, the `-c` file's
  `addopts` or `PYTEST_ADDOPTS`) or a `-o` setting already replaces the key.
- Rerun options typed on the command line are carried over too: `--reruns`, `--reruns-delay`,
  `--reruns-delay-backoff-factor`, `--reruns-mode`, `--only-rerun`, `--rerun-except`, `--rerun-exclude-path`,
  `--force-reruns` and `--max-suite-reruns`. They go last on the command, so they win over `addopts`, as in pytest.
- Rerun options kept in a file passed as `@file` on the command line are carried over as well, and so are
  `-o` settings for any ini key pytest-rerunfailures reads (`reruns`, `reruns_delay`, `reruns_delay_backoff_factor`,
  `only_rerun`, `rerun_except`), also spelled `--override-ini` or clustered as in `-qo reruns=2`.
- The coverage pre-scan gets the same rerun options, so a test that flakes before it reaches your code is rerun
  and still counts as covering it (otherwise gremlins only it could catch would survive).
- `--fail-on-flaky` and `--rerun-show-tracebacks` are not carried over. `@pytest.mark.flaky` markers work with no
  extra setup.
- No rerun options are added when the plugin is not loaded under either of its names, `rerunfailures` or
  `pytest_rerunfailures`. `-p no:rerunfailures` is handed on instead (see **Timeout scaling** below). pytest
  accepts it even when the plugin is not installed, so a project without it never receives an unknown flag.
- A command-line `-p` plugin loader is not carried into gremlin runs, with one exception: when plugin autoload is
  disabled for them and the session loaded rerunfailures, gremlins puts `-p` and the name the session registered
  (`rerunfailures` or `pytest_rerunfailures`) first among the options it hands on, so gremlin runs, the coverage
  pre-scan and the confirmation runs rerun like the main run. Autoload is disabled for gremlin runs when
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD` is set to any non-empty value, or when `--disable-plugin-autoload` comes from
  the `addopts` of your config file or from `PYTEST_ADDOPTS`, because gremlin runs inherit both. Without the
  loader they would not load the plugin and never rerun, while the rerun budget, the scaled timeout and the cache
  key still described reruns. The loader repeats the name the session registered, so it is skipped when `addopts`,
  `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` or a conftest loads the plugin too. With autoload on for gremlin runs nothing
  is added: they load the plugin through its entry point. A `--disable-plugin-autoload` typed on the command line is
  not inherited, so a session started with it and a `-p` loader still has gremlin runs that autoload the plugin and
  rerun. Other plugins loaded only by a command-line `-p` with autoload disabled, pytest-cov for one, are still not
  carried over (see [#654](https://github.com/mikelane/pytest-gremlins/issues/654)).

If a baseline test needed a rerun to pass, gremlins prints one warning that names it (up to ten tests; the rest are
counted):

```text
pytest-gremlins: warning: 1 baseline test(s) needed a rerun to pass: tests/test_api.py::test_fetch. Gremlin runs use ...
```

The warning does not fail the run. It tells you which tests to stabilize so your score reflects your tests, not
luck.

**Cost.** A gremlin that your tests do kill runs the failing test up to `N + 1` times (with `--reruns N`), plus
any `--reruns-delay`. Survivors cost nothing extra, because their tests pass. A suite whose tests fail often
under mutation therefore takes noticeably longer, most of all with a large `--reruns-delay`. Without
pytest-rerunfailures, gremlins does not re-run a killing test before it counts the kill.

**Timeout scaling.** A killed gremlin's test fails, waits out `--reruns-delay`, is rerun and fails again, once
for each rerun. With `--reruns 2 --reruns-delay 20`, the waits alone take 40 seconds, past the default
30-second limit. Judged against the plain limit, the kill would be reported as a timeout or, when the
unmutated tests use more than half the limit, downgraded to an error. So when pytest-rerunfailures is loaded,
gremlins scales the per-mutant timeout by the rerun budget of the session:

```text
effective timeout = limit * (reruns + 1) + ceil(reruns * reruns_delay)
```

`limit` is the configured per-mutant timeout (`--gremlin-mutant-timeout`, `[tool.pytest-gremlins].mutant_timeout`
or the default of 30). It is the budget of one attempt, so it is scaled too, not treated as an absolute cap.
For example, `--reruns 2 --reruns-delay 20` with the default limit gives `30 * 3 + 40 = 130` seconds. The result
is capped at 86400 seconds, and a negative delay counts as 0. Nothing is scaled with `--reruns 0`, when no reruns
are configured, or when pytest-rerunfailures is not loaded in the parent run.

When pytest-rerunfailures is not loaded in the session (a command-line `-p no:rerunfailures`,
`--disable-plugin-autoload`, or the plugin is not installed), gremlins passes `-p no:rerunfailures` on to gremlin
runs, the coverage pre-scan and the confirmation runs. They do not load pytest-rerunfailures either, so they never
rerun a failing test, whatever the ini file says, and the timeout is not scaled. This matches the main run, and the
cache keys these verdicts as having no reruns, which is how they were reached. `-p no:rerunfailures` in `addopts`
or `PYTEST_ADDOPTS` already reaches gremlin runs on its own.

`-p no:pytest_rerunfailures` blocks only the module name: pytest still loads the plugin through its entry point, so
the main run reruns. Gremlin runs rerun too, and no block is passed on.

- The reruns and the delay are read the way pytest-rerunfailures reads them for a test with no marker:
  `--force-reruns` sets the count outright; otherwise `--reruns` wins over the `reruns` ini key, and
  `--reruns-delay` wins over the `reruns_delay` ini key. An ini value that is not a number counts as unset.
  `addopts`, `PYTEST_ADDOPTS`, `@file` arguments and `-c` files are all covered, because they are read from
  the parsed session.
- The scaled value is the timeout everywhere: the timeout warning, the `mutant_timeout` field of the JSON report
  and the timeout-downgrade message show it, not the configured limit. The half-the-limit check for
  confirming a timeout kill uses it too.
- The incremental cache keys each verdict on the effective timeout and on the rerun budget itself (the rerun count,
  including `--force-reruns`, and the delay), so cached verdicts are judged again when either changes. Two settings
  that scale to the same timeout still do not share verdicts. For example, `--gremlin-mutant-timeout 60` with no
  reruns and `--gremlin-mutant-timeout 30 --reruns 1` both give 60 seconds, but each is judged on its own. The same
  holds for two settings that both reach the 86400 cap. A kill from a flaky test that failed without reruns must
  not be reused by a run that reruns it.
- **A large delay makes runs slower, not wrong.** A kill is only finished after every rerun, so each killed
  gremlin costs about `reruns * reruns_delay` seconds of waiting on top of the test time. Lower
  `--reruns-delay` if your mutation runs become too slow.
- `@pytest.mark.flaky(reruns=..., reruns_delay=...)` markers are not visible at session level and are not
  counted. A test whose marker sets a long delay can still exceed the timeout. If it does, raise
  `--gremlin-mutant-timeout` yourself.
- The formula assumes a constant delay and one failing test. `--reruns-delay-backoff-factor` (which multiplies the
  delay after each attempt), `--reruns-mode append` (which adds the global count to a marker's count) and a
  selection with several failing tests, each rerun in turn, can need more time than the formula allows. A
  gremlin that runs out of time this way is still reported as a timeout and counted as a kill when its
  unmutated tests finish within half the effective timeout; it is never counted as a survivor. Raise
  `--gremlin-mutant-timeout` if you rely on these options. `--max-suite-reruns` and `--only-rerun` can only make
  the real time shorter than the formula, never longer.

### Coverage Pre-Scan Timeout

The pre-scan is limited to 120 seconds by default. If it runs longer, gremlins emits this warning (wrapped here for width)

```text
pytest-gremlins: coverage pre-scan exceeded 120s; coverage-guided test selection disabled
(set coverage_timeout / --gremlin-coverage-timeout to raise it)
```

and falls back to running every test for every gremlin. Raise the limit with the CLI or TOML:

```bash
pytest --gremlins --gremlin-coverage-timeout=600
```

```toml
[tool.pytest-gremlins]
coverage_timeout = 600
```

The value must be a positive integer number of seconds, at most 86400 (one day); the CLI flag wins over
the TOML key.

### Per-Mutant Timeout

Each gremlin's test run is limited to 30 seconds by default, in sequential, `--gremlin-parallel` and
`--gremlin-batch` runs alike. A run that takes longer is reported as a timeout. A surviving gremlin runs
every test selected for it, so on a slow suite survivors are the first to hit the limit. Raise it with the
CLI or TOML:

```bash
pytest --gremlins --gremlin-mutant-timeout=120
```

```toml
[tool.pytest-gremlins]
mutant_timeout = 120
```

The value must be a positive integer number of seconds, at most 86400 (one day); the CLI flag wins over
the TOML key. The incremental cache keys each verdict on the timeout it was reached under, so a changed
timeout judges every gremlin again. So does a changed rerun count or delay.

With pytest-rerunfailures configured, the limit is the budget of one attempt and the effective timeout is
larger; see [Flaky Tests and pytest-rerunfailures](#flaky-tests-and-pytest-rerunfailures).

A timeout is only scored as a kill when the gremlin's tests finish within half the limit without
the mutant. In parallel and batch mode a gremlin first runs among other workers, so a timeout there may
only be contention (a shared lock, a saturated CPU). pytest-gremlins therefore re-runs a timed-out
gremlin alone, with the mutant active, under the same selection and limit. If that run finishes, it is
scored as usual (a failing test is a kill, a pass is a survivor) and cached like any other result.
Sequential mode already runs gremlins alone, so it skips this step.

If the gremlin times out alone too, pytest-gremlins reruns its exact selection of tests unmutated
under the same limit (once per distinct selection). The timeout stays a kill only if that run finishes
within half the limit. If it takes longer, or times out, the timing is too close to call, so the
gremlin is reported as an error, not a kill, with the measured unmutated time and the limit, and the
summary and JSON report say how many were downgraded. A limit that is too short can only lower the
score. Downgraded results are not written to the incremental cache.

If you see downgrades, raise the limit (or speed up the slow tests): a real hang outlasts any limit,
so a longer one costs you no kills. The trade-off is time, since in parallel and batch mode each
genuine hang costs one extra solo run, up to the limit.

### Batch Execution

Batch mode reduces subprocess overhead by testing multiple gremlins per subprocess:

```bash
pytest --gremlins --gremlin-batch --gremlin-batch-size=20
```

Batch size tuning:

| Batch Size | Tradeoff |
|------------|----------|
| Small (5-10) | More subprocess overhead, but faster feedback on failures |
| Medium (20-50) | Balanced for most projects |
| Large (100+) | Less overhead, but slower feedback |

### Combined Performance Options

For maximum speed, combine all performance options:

```bash
pytest --gremlins \
    --gremlin-cache \
    --gremlin-parallel \
    --gremlin-batch \
    --gremlin-batch-size=20
```

## CI Integration

### GitHub Actions (Recommended)

The [pytest-gremlins-action](https://github.com/marketplace/actions/pytest-gremlins)
handles installation, parallel execution, caching, and score gating in a single step:

```yaml
- uses: mikelane/pytest-gremlins-action@v1
  with:
    threshold: 80
    parallel: 'true'
    cache: 'true'
```

See the [GitHub Action cookbook](../cookbook/github-action.md) for full configuration
options, caching details, and advanced usage.

If you need a manual workflow instead (e.g., self-hosted runners without marketplace access):

```yaml
name: Mutation Testing

on: [push, pull_request]

jobs:
  mutation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync

      - name: Run mutation testing
        run: |
          uv run pytest --gremlins \
            --gremlin-cache \
            --gremlin-parallel \
            --gremlin-report=json

      - name: Upload mutation report
        uses: actions/upload-artifact@v4
        with:
          name: mutation-report
          path: coverage/gremlins/gremlins.json
```

### GitLab CI

```yaml
mutation_testing:
  stage: test
  script:
    - pip install uv && uv sync
    - uv run pytest --gremlins --gremlin-cache --gremlin-parallel --gremlin-report=json
  artifacts:
    reports:
      junit: coverage/gremlins/gremlins.json
    paths:
      - coverage/gremlins/
```

### Pre-commit Hook

Add mutation testing as a pre-commit hook (warning: can be slow):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: mutation-testing
        name: Mutation Testing
        entry: pytest --gremlins --gremlin-cache --gremlin-parallel
        language: system
        pass_filenames: false
        stages: [pre-push]  # Run on push, not commit
```

## Troubleshooting Configuration

### Common Issues

**No gremlins found:**

```text
$ pytest --gremlins
No gremlins found: no source paths were discovered.

pytest-gremlins looks for source code in this order:
  1. --gremlin-targets CLI option
  2. [tool.pytest-gremlins] paths in pyproject.toml
  3. [tool.setuptools] package config in pyproject.toml
  4. [project].name heuristic
  5. setup.cfg packages config
  6. importlib.metadata (installed package metadata)
  7. src/ directory

If your source code is elsewhere, use: pytest --gremlins --gremlin-targets=your_package
```

The plugin auto-discovers source paths using seven strategies, tried in order:

1. `--gremlin-targets` CLI option
2. `[tool.pytest-gremlins] paths` in `pyproject.toml`
3. `[tool.setuptools]` package config in `pyproject.toml`
4. `[project].name` heuristic (looks for a directory matching the project name)
5. `setup.cfg` packages config
6. `importlib.metadata` (installed package metadata)
7. `src/` fallback

The first strategy that finds source files wins. If none of them match your layout:

1. Use `--gremlin-targets=your_package` to point at your source directly
2. Verify files are not excluded by `exclude` patterns
3. Ensure source files contain mutable code (not just imports/constants)
4. If you don't have a `pyproject.toml`, you must use `--gremlin-targets`

**Cache not working:**

If caching does not seem to skip unchanged code:

1. Ensure `--gremlin-cache` flag is present
2. Check `.gremlins_cache/` directory exists
3. Verify source and test files have not changed

**Parallel execution hanging:**

If parallel mode hangs or is very slow:

1. Reduce worker count: `--gremlin-workers=2`
2. Check for test isolation issues
3. Ensure tests do not have external dependencies

### Debug Mode

Enable verbose output to debug configuration issues:

```bash
pytest --gremlins -v
```

This shows:

- Which files are being scanned
- Number of gremlins found per file
- Which operators are active
- Cache hit/miss statistics

## Configuration Validation

pytest-gremlins validates configuration at startup and reports errors:

```text
pytest-gremlins: Invalid configuration
  - Unknown operator 'typo' in operators list
  - Path 'nonexistent/' does not exist
```

Use the `--collect-only` flag to validate configuration without running tests:

```bash
pytest --gremlins --collect-only
```

`--collect-only` loads and validates `[tool.pytest-gremlins]` and the `--gremlin-*` options,
so invalid values are rejected as usual. It then skips mutation testing entirely (no
instrumentation, coverage pre-scan, cache setup, or gremlin execution) and prints a one-line
notice to stderr, which keeps `--collect-only -q` node-id output on stdout clean.
