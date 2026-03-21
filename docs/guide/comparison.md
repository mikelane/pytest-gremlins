# Comparison Guide

This guide provides a fair, factual comparison of pytest-gremlins with other Python mutation testing tools.

!!! note "Data Currency"
    Tool information verified as of March 2026. Check each tool's repository for the latest updates.

## Quick Comparison

| Feature | pytest-gremlins | mutmut | cosmic-ray | mutatest |
| ------- | --------------- | ------ | ---------- | -------- |
| **Speed Architecture** | Mutation switching | Environment variable switching (fork-based) | Import hooks (custom finder/loader) | `__pycache__` modification |
| **pytest Integration** | Native plugin | Runs pytest externally | Standalone CLI | Standalone CLI |
| **Parallelization** | Built-in worker pool + pytest-xdist | Built-in (v3+) | Celery distributors (multi-machine) | Built-in (Python 3.8+) |
| **Coverage Guidance** | Yes (built-in) | Yes (`mutate_only_covered_lines`) | Yes | Yes |
| **Incremental Runs** | Yes (hash-based cache) | Limited (improvements being upstreamed) | Yes (session database) | Limited |
| **GitHub Action** | Yes | No | No | No |
| **Python Support** | 3.11+ | 3.8+ | 3.9+ | 3.7+ |
| **Installation** | `pip install pytest-gremlins` | `pip install mutmut` | `pip install cosmic-ray` | `pip install mutatest` |
| **Platform** | All | Unix/WSL only | All | All |
| **Maintenance** | Active | Active (v3.5.0, Feb 2026) | Active | Inactive (last release 2022) |

## Detailed Comparisons

### mutmut

[mutmut](https://github.com/boxed/mutmut) is a popular mutation testing tool focused on ease of use.

#### Strengths

- **Large community**: 1.2k GitHub stars, used by 700+ projects
- **Interactive browser**: Terminal UI for exploring surviving mutants
- **Apply mutations**: Easy `mutmut apply` command to fix surviving mutants
- **Active development**: Regular updates and maintenance

#### Considerations

- **Unix/WSL required**: Requires `fork()` support, no native Windows
- **Separate execution model**: Not a pytest plugin, but runs pytest internally (fixtures and config work)
- **v3 scope limitation**: Version 3+ only mutates code inside functions
- **Unix only**: Requires `fork()` for process isolation (no native Windows support)

#### Architecture Comparison

mutmut also uses environment variable switching for mutations and loads all mutated modules
into memory on the main process. It then uses `fork()` to run each mutation in its own
environment in parallel. It supports coverage-guided test selection
(`mutate_only_covered_lines = true` in config). Incremental caching is limited in the
current release but a contributor is upstreaming improvements.

The key architectural difference is in isolation: mutmut uses `fork()` to create isolated
processes per mutation, while pytest-gremlins runs mutations in subprocesses with the
active mutation selected by environment variable. Both avoid reloading modules per mutation.

```text
mutmut workflow:
1. Load all mutated modules into memory
2. fork() per mutation (parallel, isolated)
3. Set env var to select mutation
4. Run tests via pytest
5. Record result

pytest-gremlins workflow:
1. Instrument code once (all mutations embedded)
2. Set ACTIVE_GREMLIN=N
3. Run tests in subprocess
4. Change env var
5. Repeat (no I/O, no reloads)
```

The practical speed difference depends on your project. mutmut requires `fork()` (Unix
only), while pytest-gremlins uses subprocesses (cross-platform). For projects with slow
imports (NumPy, Pandas, Django), mutmut's fork-based approach may be faster since the
modules are already loaded in the parent process.

#### When to Choose mutmut

- You work exclusively on Unix/Linux/macOS (or WSL)
- You value the interactive mutation browser
- You want a mature, well-documented tool
- You prefer applying fixes directly from the tool

### cosmic-ray

[cosmic-ray](https://github.com/sixty-north/cosmic-ray) is a distributed mutation testing framework with a plugin architecture.

#### Strengths

- **Distributed execution**: Supports local, HTTP, and Celery-based distributors
- **Session management**: Database-backed sessions for large projects
- **Plugin architecture**: Extensible operators and distributors
- **Build tool integration**: CI/CD pipeline friendly

#### Considerations

- **Setup complexity**: Requires configuration and initialization steps
- **External tool**: Not integrated into pytest's execution model
- **Learning curve**: More concepts (sessions, distributors, operators)

#### Architecture Comparison

cosmic-ray uses import hooks (a custom finder/loader that intercepts imports and compiles
mutated AST) rather than rewriting source files on disk. Mutation testing state is stored
in a session database, which enables distributed execution via Celery but adds operational
complexity.

```text
cosmic-ray workflow:
1. Initialize session (create database)
2. Generate mutations
3. Distribute work to workers
4. Collect results
5. Report

pytest-gremlins workflow:
1. pytest --gremlins
2. (everything handled automatically)
```

#### When to Choose cosmic-ray

- You need distributed execution across multiple machines
- You're running mutation testing on very large codebases
- You want fine-grained control over the mutation process
- Your CI/CD requires explicit session management

### mutatest

[mutatest](https://github.com/EvanKepner/mutatest) is an AST-based mutation testing tool with random sampling capabilities.

#### Strengths

- **No source modification**: Only modifies `__pycache__`
- **Random sampling**: Useful for getting quick estimates
- **Cross-platform**: Works on Linux, Windows, and macOS
- **Full type annotations**: Well-typed codebase

#### Considerations

- **Inactive**: Last PyPI release was 2022 (v3.1.0). Development appears to have stopped.
- **Python version support**: Python 3.7+; multiprocessing requires 3.8+
- **Random behavior**: Non-deterministic by default
- **`__pycache__` only**: Modifies bytecode cache, not source files

#### When to Choose mutatest

- You need random sampling for quick mutation score estimates
- You want a tool that never touches your source files

!!! warning "Maintenance Status"
    mutatest has had no releases since 2022. Consider this when planning long-term use.

## Feature Deep Dive

### Speed Optimizations

| Optimization | pytest-gremlins | mutmut | cosmic-ray | mutatest |
| ------------ | --------------- | ------ | ---------- | -------- |
| Mutation switching | Yes (env var + subprocess) | Yes (env var + fork) | No | No |
| Coverage-guided test selection | Yes | Yes (`mutate_only_covered_lines`) | Yes | Yes |
| Incremental analysis | Hash-based | Yes (`mutants/` dir) | Session-based | Limited |
| Parallel execution | Built-in worker pool + pytest-xdist | Built-in | Celery distributors | Multiprocessing |
| GitHub Action | Yes | No | No | No |

**Mutation switching** is the key architectural difference. Traditional tools modify files, reload
modules, and run tests for each mutation. pytest-gremlins instruments code once and toggles
mutations via environment variables, eliminating:

- File I/O operations per mutation
- Module reload time (significant for heavy imports)
- Import-time side effects

### Operator Coverage

| Operator Type | pytest-gremlins | mutmut | cosmic-ray | mutatest |
| ------------- | --------------- | ------ | ---------- | -------- |
| Comparison (`<`, `>`, `==`) | Yes | Yes | Yes | Yes |
| Boundary (`x >= 18` to `x >= 19`) | Yes | Partial | Yes | Yes |
| Boolean (`and`/`or`, `True`/`False`) | Yes | Yes | Yes | Yes |
| Arithmetic (`+`, `-`, `*`, `/`) | Yes | Yes | Yes | Yes |
| Return values | Yes | Yes | Yes | Yes |
| Statement deletion | No | Yes | Yes | Yes |
| Exception handling | No | Limited | Yes | Yes |
| String literals | No | Yes | Limited | Yes |

### pytest Integration

| Integration Aspect | pytest-gremlins | mutmut | cosmic-ray | mutatest |
| ------------------ | --------------- | ------ | ---------- | -------- |
| Native plugin | Yes | No (runs pytest externally) | No | No |
| Respects fixtures | Yes | Yes (runs pytest) | No | No |
| Respects markers | Yes | Yes (runs pytest) | No | No |
| pytest-xdist compatible | Yes | No (see [#474](https://github.com/boxed/mutmut/issues/474)) | N/A | N/A |
| pytest-cov integration | Yes | Separate | Separate | Separate |
| Single command | `pytest --gremlins` | `mutmut run` | `cosmic-ray init && exec` | `mutatest` |

### Configuration

=== "pytest-gremlins"
    ```toml
    # pyproject.toml
    [tool.pytest-gremlins]
    operators = ["comparison", "boundary", "boolean"]
    exclude = ["tests/", "migrations/"]
    ```

=== "mutmut"
    ```toml
    # pyproject.toml or setup.cfg
    [tool.mutmut]
    paths_to_mutate = "src/"
    tests_dir = "tests/"
    ```

=== "cosmic-ray"
    ```toml
    # cosmic-ray.toml
    [cosmic-ray]
    module-path = "src/example"
    test-command = "pytest"
    ```

=== "mutatest"
    ```bash
    # Command-line only
    mutatest -s src/ -t tests/
    ```

### Reporting

| Report Type | pytest-gremlins | mutmut | cosmic-ray | mutatest |
| ----------- | --------------- | ------ | ---------- | -------- |
| Terminal summary | Yes | Yes | Yes | Yes |
| HTML report | Yes | Yes | Yes | Yes |
| JSON export | Yes | Yes | Yes | Limited |
| CI annotations | No | No | No | No |
| Surviving mutant details | Yes | Yes | Yes | Yes |

## Migration Guides

### Coming from mutmut

If you're switching from mutmut to pytest-gremlins:

1. **Install pytest-gremlins**:

   ```bash
   pip uninstall mutmut
   pip install pytest-gremlins
   ```

2. **Update configuration**:

   | mutmut | pytest-gremlins |
   | ------ | --------------- |
   | `paths_to_mutate` | `paths` |
   | `tests_dir` | N/A (uses pytest collection) |
   | `runner` | N/A (native pytest) |

3. **Run mutations**:

   ```bash
   # Before (mutmut)
   mutmut run
   mutmut results
   mutmut html

   # After (pytest-gremlins)
   pytest --gremlins
   pytest --gremlins --gremlin-report=html
   ```

4. **Key differences to note**:
   - No separate `mutmut apply` command (yet)
   - Results integrated into pytest output
   - Works on Windows without WSL

### Coming from cosmic-ray

If you're switching from cosmic-ray to pytest-gremlins:

1. **Install pytest-gremlins**:

   ```bash
   pip uninstall cosmic-ray
   pip install pytest-gremlins
   ```

2. **Simplify workflow**:

   ```bash
   # Before (cosmic-ray)
   cosmic-ray init config.toml session.sqlite
   cosmic-ray exec session.sqlite
   cosmic-ray dump session.sqlite | cr-html > report.html

   # After (pytest-gremlins)
   pytest --gremlins --gremlin-report=html
   ```

3. **Configuration mapping**:

   | cosmic-ray | pytest-gremlins |
   | ---------- | --------------- |
   | `module-path` | `paths` |
   | `test-command` | N/A (native pytest) |
   | `distributor` | `--gremlin-workers` or pytest-xdist |

4. **Key differences to note**:
   - No session database to manage
   - No separate init/exec/report steps
   - Parallelization via pytest-xdist instead of distributors

## Benchmarks

!!! info "No Fabricated Numbers"
    We do not publish benchmark numbers we cannot reproduce. Real performance depends heavily on
    your codebase, test suite, and hardware.

**Expected performance characteristics** based on architecture:

| Scenario | pytest-gremlins Advantage |
| -------- | ------------------------- |
| Heavy imports (NumPy, Django) | Significant (no reimport per mutation) |
| Many small mutations | Significant (no file I/O per mutation) |
| Repeat runs on unchanged code | Significant (hash-based caching) |
| Small projects with fast imports | Moderate |
| Distributed across machines | cosmic-ray may be faster |

To benchmark on your own codebase:

```bash
# Time mutmut
time mutmut run

# Time pytest-gremlins
time pytest --gremlins
```

## Summary

| Choose | When |
| ------ | ---- |
| **pytest-gremlins** | You want speed, native pytest integration, a GitHub Action, and cross-platform support |
| **mutmut** | You want a mature standalone CLI with interactive browsing (Unix/WSL only) |
| **cosmic-ray** | You need distributed execution across multiple machines via Celery |
| **mutatest** | You need random sampling (note: inactive since 2022) |

Each tool has valid use cases. pytest-gremlins focuses on making mutation testing fast enough for
everyday TDD workflows rather than overnight CI jobs.

## External Resources

- [mutmut Documentation](https://mutmut.readthedocs.io/)
- [cosmic-ray Documentation](https://cosmic-ray.readthedocs.io/)
- [mutatest Documentation](https://mutatest.readthedocs.io/)
- [pytest-gremlins Design: North Star](../design/NORTH_STAR.md)
