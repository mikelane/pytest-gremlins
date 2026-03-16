# Troubleshooting

This guide documents common errors you may encounter when using pytest-gremlins, along with their causes and solutions.

## Installation Errors

### Error: Python version not supported

**Symptom:**

```text
ERROR: Package 'pytest-gremlins' requires a different Python: 3.10.x not in '>=3.11'
```

Or when using pip:

```text
ERROR: Ignored the following versions that require a different python version: ...
```

**Cause:** pytest-gremlins requires Python 3.11 or later. You are running an older Python version.

**Solution:**

1. Check your Python version:

   ```bash
   python --version
   ```

2. Install Python 3.11 or later:

   ```bash
   # macOS with Homebrew
   brew install python@3.11

   # Ubuntu/Debian
   sudo apt install python3.11

   # Using pyenv
   pyenv install 3.11.0
   pyenv local 3.11.0
   ```

3. Create a virtual environment with the correct Python:

   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install pytest-gremlins
   ```

**Prevention:** Always verify your Python version meets requirements before installing packages.

---

### Error: Dependency conflict with pytest

**Symptom:**

```text
ERROR: pytest-gremlins requires pytest>=7.0.0, but you have pytest 6.x.x
```

Or pip resolver errors mentioning pytest version conflicts.

**Cause:** Your project has an older version of pytest pinned that conflicts with pytest-gremlins requirements.

**Solution:**

1. Upgrade pytest:

   ```bash
   pip install --upgrade pytest
   ```

2. If you have version constraints in your `pyproject.toml` or `requirements.txt`, update them:

   ```toml
   [project]
   dependencies = [
       "pytest>=7.0.0",
   ]
   ```

3. Re-install pytest-gremlins after upgrading pytest.

**Related:** [Getting Started](getting-started.md#requirements)

---

### Error: Dependency conflict with coverage.py

**Symptom:**

```text
ERROR: pytest-gremlins requires coverage>=7.12.0, but you have coverage 6.x.x
```

**Cause:** Your project has an older version of coverage.py that doesn't support the features
pytest-gremlins needs (like dynamic contexts for test selection).

**Solution:**

1. Upgrade coverage:

   ```bash
   pip install --upgrade coverage
   ```

2. If using pytest-cov, ensure it's also up to date:

   ```bash
   pip install --upgrade pytest-cov
   ```

**Prevention:** Use a dependency manager like uv or poetry that handles transitive dependencies correctly.

---

## Configuration Errors

### Error: Unknown operator requested

**Symptom:**

```text
UserWarning: Unknown operator 'comparision' requested, ignoring
```

(Note: no gremlins found because the operator name was misspelled)

**Cause:** You specified an operator name in configuration that doesn't exist. Common causes:

- Typo in operator name
- Using a deprecated operator name
- Missing a custom operator registration

**Solution:**

1. Check the correct operator names. Available operators are:

   - `comparison` (not "comparision")
   - `arithmetic`
   - `boolean`
   - `boundary`
   - `return`

2. Fix your configuration:

   ```toml
   [tool.pytest-gremlins]
   operators = ["comparison", "arithmetic", "boolean"]
   ```

3. Or on the command line:

   ```bash
   pytest --gremlins --gremlin-operators=comparison,arithmetic
   ```

**Related:** [Operators](operators.md)

---

### Error: No source paths discovered

**Symptom:**

No gremlins found, even though your code has mutable expressions.

```text
================== pytest-gremlins mutation report ==================

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

=====================================================================
```

**Cause:** pytest-gremlins could not auto-discover your source code. This happens when:

- You don't have a `pyproject.toml` (e.g., using `requirements.txt`)
- Your `pyproject.toml` doesn't have `[tool.setuptools]` configuration
- Your source code is not in a `src/` directory

**Solution:**

1. Point directly at your source code:

   ```bash
   pytest --gremlins --gremlin-targets=mypackage
   ```

**Prevention:** Always verify your project structure matches your configuration.

---

### Error: TOML syntax error in pyproject.toml

**Symptom:**

```text
tomllib.TOMLDecodeError: Expected '=' after a key in a key/value pair (at line X, column Y)
```

**Cause:** Invalid TOML syntax in your configuration file.

**Solution:**

1. Validate your TOML syntax. Common mistakes:

   ```toml
   # WRONG - missing quotes around string
   [tool.pytest-gremlins]
   operators = [comparison, arithmetic]

   # CORRECT
   [tool.pytest-gremlins]
   operators = ["comparison", "arithmetic"]
   ```

2. Check for mismatched brackets or unclosed strings.

3. Use a TOML validator or IDE with TOML support.

---

## Runtime Errors

### Error: SyntaxError during instrumentation

**Symptom:**

```text
SyntaxError: invalid syntax
```

Or the mutation testing silently skips certain files.

**Cause:** pytest-gremlins couldn't parse a Python file. This typically happens when:

- The file contains syntax errors
- The file uses Python features newer than your Python version
- The file is not valid UTF-8

**Solution:**

1. Run your tests without mutation testing first to catch syntax errors:

   ```bash
   pytest
   ```

2. Check that all files can be parsed:

   ```bash
   python -m py_compile src/yourmodule.py
   ```

3. Ensure consistent encoding (UTF-8) in all source files.

**Prevention:** Set up pre-commit hooks to validate syntax before committing.

---

### Error: AST transformation produces unexpected result

**Symptom:**

```text
TypeError: Expected ast.Module, got <class 'X'>
```

**Cause:** Internal error during AST transformation. This is rare and typically indicates:

- An edge case in the code structure
- A bug in pytest-gremlins (please report it!)

**Solution:**

1. Try excluding the problematic file temporarily:

   ```toml
   [tool.pytest-gremlins]
   exclude = ["**/problematic_file.py"]
   ```

2. Report the issue with a minimal reproduction at:
   [https://github.com/mikelane/pytest-gremlins/issues](https://github.com/mikelane/pytest-gremlins/issues)

**Related:** [Contributing](../contributing.md)

---

### Error: Cache database corrupted

**Symptom:**

```text
WARNING: Cache database corrupted at .gremlins_cache/results.db, recreating
```

**Cause:** The SQLite cache database was corrupted. This can happen due to:

- Process termination during a write
- File system issues
- Concurrent access from multiple processes

**Solution:**

This warning is informational - pytest-gremlins automatically recreates the cache. No action
required.

To manually clear the cache:

```bash
pytest --gremlins --gremlin-clear-cache
```

Or delete the cache directory:

```bash
rm -rf .gremlins_cache/
```

**Prevention:** Avoid forcefully killing pytest-gremlins during execution.

---

### Error: Test timeout exceeded

**Symptom:**

Gremlin results show `TIMEOUT` status, or you see:

```text
Gremlin X/Y: g001 - TIMEOUT
```

**Cause:** A test took longer than the configured timeout (default: 30 seconds) when running with a
mutation active.

Common causes:

- Mutation caused an infinite loop
- Mutation caused extremely slow computation
- Test is inherently slow
- System under heavy load

**Solution:**

1. The default timeout is 30 seconds (currently not configurable). Identify slow tests and optimize
   them:

   ```bash
   pytest --durations=10
   ```

2. Exclude specific slow tests from mutation testing using pytest marks.

**Prevention:** Keep individual tests fast (under 1 second when possible).

---

### Error: Memory issues with large codebases

**Symptom:**

```text
MemoryError
```

Or the system becomes unresponsive during mutation testing.

**Cause:** pytest-gremlins instruments all source code at once, which can consume significant memory
for large codebases.

**Solution:**

1. Run mutation testing on specific paths:

   ```bash
   pytest --gremlins --gremlin-targets=src/core
   ```

2. Reduce the number of parallel workers:

   ```bash
   pytest --gremlins --gremlin-workers=2
   ```

3. Run mutation testing in batches by module:

   ```bash
   pytest --gremlins --gremlin-targets=src/auth
   pytest --gremlins --gremlin-targets=src/api
   ```

4. Exclude non-critical code:

   ```toml
   [tool.pytest-gremlins]
   exclude = ["**/migrations/*", "**/generated/*"]
   ```

**Prevention:** Start with a subset of code and expand gradually.

---

### Error: RuntimeError - WorkerPool is not active

**Symptom:**

```text
RuntimeError: WorkerPool is not active. Use as context manager.
```

Or:

```text
RuntimeError: PersistentWorkerPool is not running. Use as context manager.
```

**Cause:** Internal error - the parallel worker pool was accessed outside its context manager.

**Solution:**

This indicates a bug in pytest-gremlins. Please:

1. Report the issue with full traceback at:
   [https://github.com/mikelane/pytest-gremlins/issues](https://github.com/mikelane/pytest-gremlins/issues)

2. As a workaround, disable parallel execution:

   ```bash
   pytest --gremlins  # without --gremlin-workers
   ```

---

### Error: Invalid pool configuration

**Symptom:**

```text
ValueError: Invalid start method: 'forkk'. Valid methods are: ['auto', 'fork', 'forkserver', 'spawn']
```

Or:

```text
ValueError: max_workers must be positive, got -1
```

Or:

```text
ValueError: timeout must be positive, got 0
```

**Cause:** Invalid configuration values for parallel execution settings.

**Solution:**

Use valid configuration values via CLI arguments:

- `--gremlin-workers`: A positive integer (or omit to use CPU count)
- `--gremlin-batch-size`: A positive integer (default: 10)

```bash
pytest --gremlins --gremlin-workers=4
```

Since v1.5.0, `workers` and `batch_size` are configurable via `pyproject.toml`. See
[Configuration](configuration.md#complete-configuration-reference) for the full list of keys.

---

## Integration Errors

### Error: Conflict with pytest-cov

**Symptom:**

Coverage numbers are incorrect or missing when running mutation testing.

**Cause:** Both pytest-gremlins and pytest-cov try to collect coverage data, which can conflict.

**Solution:**

1. Disable pytest-cov when running mutation testing:

   ```bash
   pytest --gremlins --no-cov
   ```

2. Or configure them to not run together:

   ```toml
   # pytest.ini or pyproject.toml [tool.pytest.ini_options]
   addopts = --cov=src  # only for regular test runs
   ```

3. Run them separately:

   ```bash
   # Regular tests with coverage
   pytest --cov=src

   # Mutation testing (has its own coverage collection)
   pytest --gremlins --no-cov
   ```

**Prevention:** Use separate pytest invocations for coverage and mutation testing.

---

### Using pytest-xdist with gremlins

Since v1.5.0, `--gremlins` and `-n` work together. The recommended way to run parallel
mutation testing is:

```bash
pytest --gremlins -n auto
```

This uses a two-phase model: Phase 1 distributes your test suite across xdist workers;
Phase 2 reuses xdist's resolved worker count for mutation evaluation.

**Common issues:**

**Workers crash or hang with `-n auto`:**

Reduce the worker count to give each process more memory:

```bash
pytest --gremlins -n 2
```

**You want parallel mutations without xdist test distribution:**

Use the built-in worker pool instead:

```bash
pytest --gremlins --gremlin-parallel       # all CPU cores
pytest --gremlins --gremlin-workers=4      # explicit count
```

**Running without xdist installed:**

pytest-gremlins operates in single-worker mode when xdist is absent. No error is raised.

---

### Error: SyntaxError with `from __future__ import annotations`

**Symptom:**

```text
SyntaxError: from __future__ imports must occur at the beginning of the file
```

**Cause:** In versions before v1.5.0, gremlin injection could insert code before `__future__`
imports. Python requires `__future__` imports to appear before any other statements.

**Solution:**

Upgrade to v1.5.0 or later. The instrumentation engine now inserts gremlin switches after
`__future__` imports at the AST level, so this error no longer occurs.

```bash
pip install --upgrade pytest-gremlins
```

---

### Low code coverage numbers for pytest-gremlins itself

**Symptom:**

When running coverage on pytest-gremlins itself (as a contributor), you see lower coverage than
expected (around 69%) despite comprehensive tests.

**Cause:** This is an inherent limitation of measuring code coverage for pytest plugins, not a testing
gap. The issue occurs because:

1. **Plugin import timing**: When pytest loads a plugin, it imports the entire module tree *before*
   coverage.py starts instrumenting code. Module-level imports, constants, and function definitions
   execute during loading, so they show as uncovered.

2. **Multiprocessing code paths**: Worker pool code runs in subprocesses where coverage measurement
   is complex to coordinate.

3. **Integration tests**: pytester (the pytest integration test fixture) runs pytest in isolated
   subprocesses, which don't share coverage data with the main process.

**Solution:**

This is expected behavior, not a bug. The test suite is comprehensive:

- Files like `results.py` and `score.py` have full test coverage in `tests/small/reporting/`
- The 69% coverage target reflects what's measurable, not test quality
- Function *bodies* are measured when tests call them; only function *definitions* appear uncovered

For contributors: see the
[Code Coverage section in CONTRIBUTING.md][coverage-docs]
for details on our coverage configuration.

[coverage-docs]: https://github.com/mikelane/pytest-gremlins/blob/main/CONTRIBUTING.md#code-coverage

**Related:** [Contributing Guide](https://github.com/mikelane/pytest-gremlins/blob/main/CONTRIBUTING.md)

---

### Error: Coverage collection fails

**Symptom:**

```text
pytest-gremlins: 0 tests cover this gremlin, marking as survived
```

For gremlins that should be covered by tests.

**Cause:** Coverage collection failed to map tests to source lines. Common causes:

- Source files are outside the coverage measurement scope
- Tests import modules before coverage starts
- Dynamic imports that bypass coverage

**Solution:**

1. Verify coverage is working normally:

   ```bash
   pytest --cov=src --cov-report=term-missing
   ```

2. Ensure source paths match what pytest-gremlins expects:

   ```toml
   [tool.pytest-gremlins]
   paths = ["src/mypackage"]  # Match your coverage source
   ```

3. Check for import order issues in conftest.py.

---

### Error: IDE integration issues

**Symptom:**

IDE shows errors or warnings about instrumented code, or debugging doesn't work correctly during mutation testing.

**Cause:** pytest-gremlins modifies code at runtime, which IDEs can't see.

**Solution:**

1. **For debugging:** Run without mutation testing first:

   ```bash
   pytest tests/test_specific.py
   ```

2. **For IDE analysis:** The original source is unchanged; IDE analysis should work normally on
   your source files.

3. **For test discovery:** pytest-gremlins doesn't affect test discovery. If tests aren't
   discovered, check your IDE's pytest configuration.

---

### Error: CI/CD environment issues

**Symptom:**

Mutation testing works locally but fails in CI with:

- Permission errors
- Missing dependencies
- Timeout errors

**Cause:** CI environments have different configurations than local development.

**Solution:**

1. **Permission errors:** Ensure the CI user can write to the cache directory:

   ```yaml
   # GitHub Actions
   - name: Run mutation testing
     run: |
       mkdir -p .gremlins_cache
       pytest --gremlins
   ```

2. **Timeout errors:** The timeout is currently fixed at 30 seconds. If tests are timing out,
   optimize them or exclude slow tests from mutation testing.

3. **Memory limits:** Reduce parallelism:

   ```bash
   pytest --gremlins --gremlin-workers=2
   ```

4. **Cache not persisting between runs:** Store the cache as an artifact:

   ```yaml
   # GitHub Actions
   - uses: actions/cache@v3
     with:
       path: .gremlins_cache
       key: gremlins-cache-${{ hashFiles('src/**/*.py') }}
   ```

---

## Getting Help

### Debugging Tips

1. **Enable verbose output:**

   ```bash
   pytest --gremlins -v
   ```

2. **Run on a single file first:**

   ```bash
   pytest --gremlins --gremlin-targets=src/mymodule.py tests/test_mymodule.py
   ```

3. **Generate an HTML report for detailed results:**

   ```bash
   pytest --gremlins --gremlin-report=html
   ```

   Then open `coverage/gremlins/index.html` in your browser for a detailed breakdown of all gremlins and
   their status.

4. **Disable caching to rule out cache issues:**

   ```bash
   pytest --gremlins --gremlin-clear-cache
   ```

### Reporting Issues

If you encounter a bug not covered here:

1. **Search existing issues:**
   [https://github.com/mikelane/pytest-gremlins/issues](https://github.com/mikelane/pytest-gremlins/issues)

2. **Create a new issue** with:

   - pytest-gremlins version (`pip show pytest-gremlins`)
   - Python version (`python --version`)
   - Operating system
   - Full error traceback
   - Minimal code to reproduce the issue
   - Configuration (pyproject.toml snippet)

3. **Include your environment:**

   ```bash
   pip freeze > requirements.txt
   ```

### Community Resources

- **GitHub Discussions:**
  [https://github.com/mikelane/pytest-gremlins/discussions](https://github.com/mikelane/pytest-gremlins/discussions)
- **Issue Tracker:**
  [https://github.com/mikelane/pytest-gremlins/issues](https://github.com/mikelane/pytest-gremlins/issues)

### Related Documentation

- [Getting Started](getting-started.md) - Installation and first run
- [Configuration](configuration.md) - All configuration options
- [Operators](operators.md) - Mutation operator reference
- [Reports](reports.md) - Understanding output and reports
