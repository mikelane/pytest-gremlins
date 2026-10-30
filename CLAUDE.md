# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pytest-gremlins is a **fast-first** mutation testing plugin for pytest. Speed is the primary
differentiator - we aim to make mutation testing practical for everyday TDD, not just overnight
CI jobs.

## Design Documents

- [North Star](docs/design/NORTH_STAR.md) - Vision, speed architecture, success metrics
- [Operators](docs/design/OPERATORS.md) - Mutation operators design and registry
- [Agent Guidelines](docs/design/AGENT_GUIDELINES.md) - TDD laws, BDD process, CI/CD, release process

## Core Architecture (Speed-First)

Four pillars drive our speed strategy:

1. **Mutation Switching** - Instrument code once with all mutations embedded, toggle via environment
   variable. No file I/O, no module reloads during test runs.

2. **Coverage-Guided Test Selection** - Only run tests that actually cover the mutated code. 10-100x reduction in test executions.

3. **Incremental Analysis** - Cache results keyed by content hashes. Skip unchanged code/tests on subsequent runs.

4. **Parallel Execution** - Distribute gremlins across worker processes. Mutation switching makes
   this safe (no shared mutable state).

## Domain Language

| Traditional Term       | Gremlin Term            |
| ---------------------- | ----------------------- |
| Original code          | **Mogwai**              |
| Start mutation testing | **Feed after midnight** |
| Mutant                 | **Gremlin**             |
| Kill mutant            | **Zap**                 |
| Surviving mutant       | **Survivor**            |

## Project Structure

```text
pytest-gremlins/
├── src/pytest_gremlins/      # Source code
│   ├── __init__.py           # Package init with version
│   ├── config.py             # Configuration loading from pyproject.toml
│   ├── plugin.py             # pytest plugin hooks
│   ├── py.typed              # PEP 561 marker
│   ├── cache/                # Incremental analysis cache
│   ├── coverage/             # Coverage-guided test selection
│   ├── instrumentation/      # AST transformation and mutation switching
│   ├── operators/            # Mutation operator definitions
│   ├── parallel/             # Parallel execution support
│   └── reporting/            # Result reporting (console, HTML, JSON)
├── tests/
│   ├── conftest.py           # Shared fixtures
│   ├── benchmark/            # Benchmark tests
│   ├── cache/                # Cache domain tests
│   ├── config/               # Config domain tests
│   ├── coverage_module/      # Coverage domain tests
│   ├── instrumentation/      # Instrumentation domain tests
│   ├── operators/            # Operator domain tests
│   ├── parallel/             # Parallel domain tests
│   ├── plugin/               # Plugin integration tests
│   └── reporting/            # Reporting domain tests
├── features/                 # Gherkin scenarios
├── docs/
│   └── design/               # Design documents
├── .github/workflows/        # CI/CD
├── pyproject.toml            # Project config (uv, ruff, mypy, pytest)
├── tox.ini                   # Multi-version testing
└── .pre-commit-config.yaml   # Pre-commit hooks
```

## Build Commands

```bash
# Install dependencies
uv sync --dev

# Run small tests only (fast, always safe)
uv run pytest tests -m small

# Run small + medium tests (PR checks)
uv run pytest tests -m "small or medium"

# Run all tests
uv run pytest

# Type checking (strict)
uv run mypy src/pytest_gremlins

# Linting
uv run ruff check src tests

# Formatting
uv run ruff format src tests

# All checks (what pre-commit runs)
uv run pre-commit run --all-files

# Multi-version testing
uv run tox

# Build docs
uv run mkdocs build --strict

# Run doctests
# Filesystem isolation checks are disabled: doctests can't carry pytest markers,
# so pytest-test-categories flags pdb reading its config file as a violation.
uv run pytest --doctest-modules src/pytest_gremlins --override-ini="test_categories_enforcement=disabled"
```

## CI Caching

pytest-gremlins uses a two-layer cache in CI:

1. **CI platform cache** (outer) — stores `.gremlins_cache/` between jobs
2. **IncrementalCache** (inner) — per-gremlin results by content hash

**Critical rules for CI cache configuration:**

- Use `hashFiles` on source + test files + `pyproject.toml` (NOT commit SHA)
- Always use `restore-keys` prefix fallback (so a file change gets a warm cache)
- Save the cache with `if: always()` — threshold check failures must NOT discard the cache
- Use split restore/save steps (not combined `actions/cache`) so `if: always()` works

**Why `if: always()` matters:** A failing threshold check exits the job non-zero. CI
skips subsequent steps by default, so the cache save never runs and the next job starts
cold. `if: always()` overrides that — the save runs even when the score gate fails, so
the next run only re-tests what changed.

## TDD Laws (STRICTLY ENFORCED)

1. **No production code without a failing test**
2. **Only enough test code to fail**
3. **Only enough production code to pass**
4. **Refactor only when green**

## Code Style

- **Quotes:** Single quotes
- **Line length:** 120 characters
- **Type hints:** Required (strict mypy)
- **Docstrings:** Google style with doctests
- **Test names:** No "should" - use declarative statements

## Key Files

- `pyproject.toml` - All tool configuration (ruff, mypy, pytest, coverage, commitizen)
- `tox.ini` - Multi-Python version testing (3.11-3.14)
- `.pre-commit-config.yaml` - Pre-commit hooks
- `.github/workflows/ci.yml` - CI pipeline
- `.github/workflows/release.yml` - Release pipeline with Test PyPI
- `.github/workflows/cut-release.yml` - One-click version bump + tag (triggers release.yml)
- `scripts/release.sh` - Local release script (same thing, from your terminal)

## Docs Freshness

A PR whose diff changes user-facing behavior and touches nothing under `docs/` is a review finding of
**MEDIUM** severity, unless the PR description says why no docs change is needed. User-facing behavior means:
options or defaults, verdicts, exit codes, console, report or warning output, or what gets mutated. The PR
template asks the author to state which case applies in its required Docs section. Reviewers, including
pr-reviewer agents, check that section against the diff.

## Release Process

**Step 1 -- Update CHANGELOG.md.** The workflow guard fails if there are no commits since
the last tag -- the changelog commit is what satisfies it. Add a `## vX.Y.Z (date)` entry
above the most recent section, in the format below. Merge the CHANGELOG PR to main before proceeding.
The PR fails CI until the entry passes the release docs gate.

**Changelog format and the docs gate.** Every release entry in `CHANGELOG.md` is gated. Each bullet under
`### Upgrade notes`, `### Feature` and `### Fix` must end with either a docs reference or an exemption:

- A docs reference is a link to the page, with the anchor when the change has a section:
  `[docs](https://pytest-gremlins.readthedocs.io/en/latest/<page>/#<anchor>)`. A path relative to `docs/`
  (`guide/configuration.md#<anchor>`) also works. A bullet may carry several. The page and the anchor must exist
  in the built site. A link to the home page (`index.md`, `.`, or the bare `/en/latest/`) does not count.
- An exemption is `(no docs: <reason>)`, for example a bug fix that only restores documented behavior. The
  reason must not be empty, and it is reviewed in the changelog PR.
- `### Internal` and `### Documentation` bullets are not gated.
- Use only these `###` headings: `Upgrade notes`, `Feature`, `Fix`, `Internal` and `Documentation`, spelled
  exactly like that. Any other heading (`Feat`, `Fixes`, `Upgrade Notes`) fails the check, and so does a bullet
  that sits under no `###` heading.
- Every list item is a bullet: `-`, `*`, `+`, `1.` and `1)` markers all count, and a nested sub-bullet needs its
  own reference or exemption. A reference or exemption inside an HTML comment, a code span, an image
  (`![x](...)`) or an escaped link (`\[x](...)`) does not count.
- Under `### Upgrade notes`, `### Feature` and `### Fix` the only accepted lines are blank lines, list items and
  their indented continuation lines. Prose paragraphs, `•` pseudo-bullets, block quotes (`>`), code fences,
  HTML comments (`<!--` anywhere, even in a code span), other headings (`####`, indented or tab-indented `#`),
  thematic breaks and underlined headings fail the check, and the failure names the line. Put prose before the
  first `###` heading.
- A code fence or HTML comment is allowed in `### Internal`, `### Documentation` and before the first `###`
  heading, but it must be closed and must not hide a `###` heading. An unclosed one fails the check.
- An entry runs to the next `## vX.Y.Z` heading. Any other `##` line inside it
  (`## Highlights`, or one inside a `<details>` block) fails the check, and so does a heading hidden behind a
  same-line comment (`<!-- x --> ### Fix`). Under the three gated headings, U+2028, U+2029, U+0085 and the form
  feed, vertical tab and `\x1c`-`\x1e` characters fail it too: Markdown does not break lines at them.
- A carriage return that is not part of a CRLF line ending fails the check, and so does a copy of the version
  heading being released inside an HTML comment or code fence (it confuses readers and other tools). Only ASCII
  digits make a `##` line a version heading.
- A `###` heading may have up to 3 leading spaces, a tab after the `###` and a closing `###`
  (`### Internal ###`). It is read like any other heading, so it must be one of the five names above.

Put a long link on its own indented line so the bullet still passes markdownlint:

```markdown
## vX.Y.Z (YYYY-MM-DD)

**One sentence on what changes for users.**

### Upgrade notes

- **The default batch size is now 10.** Runs with many small tests get faster. Pass `--gremlin-batch-size 1` to
  keep the old behavior. (#701)
  [docs](https://pytest-gremlins.readthedocs.io/en/latest/guide/configuration/#batch-execution)

### Fix

- **A crash on an oversized `PYTHONOPTIMIZE` value.** (#709)
  (no docs: fixes a crash and changes no documented behavior)

### Internal

- Bumped a dev dependency. (#715)
```

`scripts/check_release_docs.py` enforces this. It takes the version and a `mkdocs build --strict` output
directory (`uv run mkdocs build --strict --site-dir site`, then
`uv run python scripts/check_release_docs.py X.Y.Z --site-dir site`). It exits 1 and names the bullet or link when
the entry is missing, a bullet has neither a reference nor a non-empty exemption, or a reference points to a page
or anchor that is not in the site. It exits 2 when it could not run. It runs in three places:

1. `ci.yml`, whenever a PR changes `CHANGELOG.md`, against the topmost entry, so the changelog PR fails
   first. `--newest` picks that entry by the same heading rule the check uses, where the `v` is optional. If the
   topmost `##` heading is not a version entry (`## Unreleased`), it exits 2 rather than checking an older entry.
2. `cut-release.yml`, before the tag is created, against the version `cz bump --get-next` reports.
3. The `verify-tag` job of `release.yml`, against the tagged commit. Every other job in that workflow depends on
   `verify-tag`, so a failing check blocks the publish however the release was started.

The GitHub release notes are not extracted separately: `github-release` in `release.yml` runs the same script with
`--notes-out release_notes.md`, which writes the exact text of the entry that passed (its heading line up to the next
`## vX.Y.Z` heading) and writes nothing when the check fails. The published notes are always the text the gate checked,
and the job fails if the file is empty.

**There is no bypass.** No workflow input, environment variable or flag skips the check, and `skip_test_pypi` does
not affect it. To ship a change without docs, write a `(no docs: <reason>)` exemption in the changelog PR, where the
reason is public and gets reviewed.

**Cache markers at release time.** `scripts/check_cache_kept.py` compares the guarded code (the cache-version guard's
own file set) at the newest `v*` tag reachable from the release, not counting the tag being released, with the code
being released. If it changed and neither `CACHE_VERSION` nor `RUNNER_FIDELITY_VERSION` differs from its value at that
tag, the release fails unless the entry has a `(cache kept: <reason>)` line with a non-empty reason. Put the line in the
entry's prose before its first `###` heading; it is accepted nowhere else, because the docs gate allows only list items
under the gated headings. The reason is public and is reviewed in the changelog PR. It runs in the same three places as
the docs gate (`ci.yml` on a `CHANGELOG.md` change with `--newest`, `cut-release.yml`, and `verify-tag`), exits 1 naming
the changed files, exits 2 when it could not run, and has no bypass.

**Step 2 -- Dispatch the workflow.** Never run `cz bump` locally -- the `no-commit-to-branch`
pre-commit hook blocks commits to `main` and leaves a dirty version bump to revert.

```bash
gh workflow run cut-release.yml --repo mikelane/pytest-gremlins
```

This runs `cz bump` on the GitHub Actions runner (no local hooks), commits the version,
creates an annotated tag, and pushes -- which triggers `release.yml`.

**Step 3 -- Verify the tag landed:**

```bash
git fetch --tags
git ls-remote --tags origin | tail -5
```

If the tag is missing, `--follow-tags` silently skipped a lightweight tag. Root cause:
`[tool.commitizen]` must have `annotated_tag = true`. Without it, commitizen creates
lightweight tags that `--follow-tags` ignores.

**Escape hatch -- Test PyPI is down.** `release.yml` normally runs on the tag push and gates
PyPI on a Test PyPI publish and install check. If test.pypi.org is unavailable (it returned
503 to GitHub runners for v1.11.1), re-run the release against the existing tag with the Test
PyPI steps skipped:

1. If the tag-push run is still in progress (stuck retrying Test PyPI), cancel it first --
   otherwise the dispatch waits behind it in the concurrency group. Skip this if it already failed.

   ```bash
   gh run list --workflow release.yml --repo mikelane/pytest-gremlins --limit 5
   gh run cancel <run-id> --repo mikelane/pytest-gremlins
   ```

2. Dispatch the workflow from `main` (it refuses any other ref):

   ```bash
   gh workflow run release.yml --repo mikelane/pytest-gremlins -f tag=vX.Y.Z -f skip_test_pypi=true
   ```

- The `verify-tag` job runs on every release (tag push and dispatch). It refuses dispatches not
  from `main`, checks the tag name before fetching anything, and then refuses the run unless
  the tag exists, is annotated, points at a commit, and equals `v` + the `[project].version` in
  `pyproject.toml` at that tag. The tag must already exist (step 3 above).
- A `concurrency` group keyed on the release tag never cancels a running release for that tag,
  so two runs cannot race to PyPI. A new run waits as pending; the group holds one pending run,
  so dispatching again cancels the earlier pending run. Cancel a stuck run yourself (step 1).
- Safe to re-dispatch: the PyPI publish uses `skip-existing`, so a run that already uploaded but
  failed later (for example at the GitHub Release) can be re-run to finish. PyPI keeps the files
  from the first upload; the rebuilt files are not re-uploaded there.
- The dispatched run re-runs the full gate (tests, benchmarks, attrs compatibility) on the
  tagged commit, so it takes as long as a normal release.
- With `skip_test_pypi=true`, `publish-test-pypi` and `verify-test-pypi` are skipped. The
  `verify-wheel` job runs in every release and replaces the install check by installing the
  built wheel into a fresh venv and comparing its `__version__` to the tag.
- Omit `skip_test_pypi` (or pass `false`) to re-run the full chain, Test PyPI included.
- The GitHub Release is created for `tag`, not for the branch the workflow was dispatched from.

**RELEASE_PAT secret**: The workflow requires a `RELEASE_PAT` repo secret with
`contents: write` and `workflows: write` scopes. Set it to never expire — an expired
PAT causes a silent checkout failure with no useful error message.

## Demo Videos

Narrated MP4 demos live on YouTube (not committed to git). The `.gitignore` excludes `*.mp4` and `*.webm`.

Demo project files live under `/tmp/gremlin-demo-<epic>` (or similar per-epic dirs).
Each demo project's `pyproject.toml` must include `pytest-xdist` as a dependency —
the dev plugin registers a `pytest_configure_node` hook that pluggy rejects at
`check_pending()` if xdist is absent, causing silent `pytest_sessionfinish` failure
(the HTML report never writes).
