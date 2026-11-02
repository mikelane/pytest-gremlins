# Common Beginner Questions

## How long does mutation testing take?

Mutation testing is computationally intensive because it runs your test suite multiple times.
pytest-gremlins uses several optimizations:

- **Coverage-guided selection**: Only runs tests that cover the mutated code
- **Early exit**: Stops testing a gremlin as soon as one test fails
- **Incremental caching**: Skips unchanged code on subsequent runs (use `--gremlin-cache`)
- **Parallel execution**: Distributes gremlins across CPU cores (use `-n auto` with xdist, or `--gremlin-parallel`)

For a first run, expect 10-100x the time of a normal test run. Subsequent cached runs are much faster.

## What mutation score should I aim for?

A good target depends on your project:

| Score | Interpretation |
|-------|----------------|
| < 60% | Significant test gaps exist |
| 60-80% | Average coverage, room for improvement |
| 80-90% | Good coverage for most projects |
| > 90% | Excellent coverage (may have diminishing returns) |

Some mutations are "equivalent" -- they produce identical behavior to the original code. A 100%
score is often impossible and not worth pursuing. You can mark these with an inline
[pardon pragma](configuration.md#inline-pardoning) so they stop counting as survivors.

## Which files should I mutate?

Focus on:

- **Business logic** - Core functionality that must be correct
- **Security-critical code** - Authentication, authorization, validation
- **Financial calculations** - Money handling, pricing, taxes

Skip:

- **Configuration files** - Static data, settings
- **Migration scripts** - One-time database operations
- **Generated code** - Auto-generated files

## Why does it say "No gremlins found"?

The plugin auto-discovers source paths from your project metadata. It checks (in order):
`--gremlin-targets` CLI option, `[tool.pytest-gremlins] paths` in pyproject.toml,
`[tool.setuptools]` package config, `[project].name` heuristic, `setup.cfg` packages config,
installed package metadata via `importlib.metadata`, and finally `src/` as a fallback. If none
of these match your project layout, pass the path explicitly:

```bash
pytest --gremlins --gremlin-targets=my_package
```

## How do I run mutation testing in CI?

Add a step to your CI pipeline:

```yaml
- name: Run mutation testing
  run: |
    pytest --gremlins --gremlin-report=json
    SCORE=$(jq '.summary.percentage' coverage/gremlins/gremlins.json)
    if (( $(echo "$SCORE < 80" | bc -l) )); then
      echo "Mutation score $SCORE% is below threshold 80%"
      exit 1
    fi
```

This runs mutation testing, outputs a JSON report, then checks if the mutation score meets your threshold.

## What if mutation testing is too slow?

Try these strategies:

1. **Start small**: Target specific files with `--gremlin-targets`
2. **Use incremental mode**: `--gremlin-cache` skips unchanged code
3. **Enable parallel execution**: `--gremlin-parallel`
4. **Focus operators**: `--gremlin-operators=comparison,boolean`
5. **Run in CI only**: Skip mutation testing in local development
