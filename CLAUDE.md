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

# What CI runs for the Test jobs: the suite in parallel across xdist workers.
# Never put -n in pyproject addopts: it would leak into pytester and user-like child runs.
uv run pytest tests -m "small or medium and not wip" -n auto --dist loadgroup

# Type checking (strict; pyproject.toml points it at src and tests)
uv run mypy

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

## CI Test Parallelism

The `Test` and `Test (pytest ...)` jobs in `ci.yml` run the suite with `-n auto --dist loadgroup`. A test that cannot
share a process with others takes `@pytest.mark.xdist_group(name=...)`, so it runs serially inside one worker; it is
never skipped. `tests/conftest.py` scrubs `PYTEST_XDIST_WORKER`, `PYTEST_XDIST_WORKER_COUNT` and
`PYTEST_XDIST_TESTRUNUID` per test, because pytest-test-categories treats `PYTEST_XDIST_WORKER` as proof that a
process is a worker, and pytester or subprocess children would otherwise take the worker path.

## CI Python Versions

`uv sync` and `uv run` follow `.python-version` unless `UV_PYTHON` is set, so `uv python install 3.11` alone still
tests the `.python-version` interpreter (#1000, #715). Every workflow job that runs `uv python install <version>` sets
`UV_PYTHON` to that version at job level, and the `ci.yml` `test` matrix sets it to `${{ matrix.python-version }}`. Its
`Verify the matrix Python` step fails the leg before the tests run when the venv interpreter differs from the matrix
version. `tests/config/test_workflow_python_pinning.py` checks every job that runs `uv python install <version>`, so a
new installing job without the pin fails the suite. Jobs with no install step follow `.python-version` and are not
checked.

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
- `.github/workflows/tag-release.yml` - Tags a merged release commit and dispatches release.yml (primary path)
- `scripts/tag_release.py` - The state table and gates behind `tag-release.yml`
- `.github/workflows/cut-release.yml` - Fallback one-click version bump + tag (triggers release.yml; #1047 deletes it)

## Docs Freshness

A PR whose diff changes user-facing behavior and touches nothing under `docs/` is a review finding of
**MEDIUM** severity, unless the PR description says why no docs change is needed. User-facing behavior means:
options or defaults, verdicts, exit codes, console, report or warning output, or what gets mutated. The PR
template asks the author to state which case applies in its required Docs section. Reviewers, including
pr-reviewer agents, check that section against the diff.

## Release Process

**Update CHANGELOG.md in the release PR.** `scripts/prepare_release.py` writes the `## vX.Y.Z (date)` entry above
the most recent section, in the format below; fill it in before the release PR merges. The PR fails CI until the entry
passes the release docs gate. (On the `cut-release.yml` fallback the entry goes in an earlier PR, merged before the
dispatch, because that workflow's guard fails when there are no commits since the last tag.)

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
  (`![x](...)`) or an escaped link (`\[x](...)`) does not count, and neither does one inside a raw HTML tag,
  attributes included (`<a title="(no docs: r)">`, or a docs link in an attribute), because the page does not show
  it. A tag is what the renderer keeps as raw inline HTML. One that leaves a quoted attribute value open hides the rest
  of the bullet, because a browser keeps reading the value. Text between tags (`<b>(no docs: r)</b>`), text after a
  `<` the renderer escapes (`<a@b (no docs: r)>`) and a link written as `[docs](<page.md>)` still count.
- Under `### Upgrade notes`, `### Feature` and `### Fix` the only accepted lines are blank lines, list items and
  their indented continuation lines. Prose paragraphs, `•` pseudo-bullets, block quotes (`>`), code fences,
  HTML comments (a `<!--` anywhere, and an unclosed one even in a code span), other headings (`####`, indented or
  tab-indented `#`), thematic breaks and underlined headings fail the check, and the failure names the line. Put prose
  before the first `###` heading.
- The entry is a **strict format**, checked across the whole selected entry (the preamble, `### Internal`,
  `### Documentation` and the gated sections alike). It is not a Markdown renderer, so a line outside a closed
  outer code fence or HTML comment must be prose, a list line, a version heading or one of the five `###` headings.
  Every other line that starts with `#` fails, including `#Feature`, `####Detail`, `###Feature`, `#Feature ###`,
  `#\tFeature` and `##v2.0.0`; a wrapped bullet continuation is the one exception. Any indented line directly
  under an open list item (no blank line between) is paragraph text to the renderer, so it may start with a `#` that
  is not an ATX heading: `#989-#994)`, `#964) Thanks. (no docs: r)` and `#964 for details` all pass. It still fails
  when it is heading-shaped (`#` to `######` followed by a space or the end of the line), and a `#720)` after a blank
  line renders as a heading and fails.
- A heading must start at column 0. The docs renderer makes a heading only from a `#` at column 0, so a
  heading-shaped line indented by any spaces or a tab (`### Internal` after two spaces, `\t### Fix`) renders as text
  (or, 4 columns in under a loose list item, as a heading inside that item). Such a line fails wherever it is visible
  with `an indented heading at line N (...); start the heading at column 0`, even when it names a known section, and it
  never switches the section: the bullets after it stay gated by the heading above it.
- A line that starts with an HTML tag fails, after any indentation, list marker or `>` prefix: `<div>`, `</div>`,
  `<details>`, `<pre>`, `<custom-tag>`, `<br/>`, `<?php` and `<![CDATA[`. The renderer reads it as a raw HTML block and
  leaves a `###` line inside as literal text, which would hide a section switch from readers while the gate acted on it.
  A tag in the middle of a line, a tag in a code span, an autolink (`<https://example.com>`) and a bare `<` stay
  accepted.
- A raw `<h1>`-`<h6>` tag fails wherever it is visible, in any case and with attributes (`<H2 class="x">`), including
  inside a block quote or a list item, because the renderer makes a real heading of it. A tag written as a code span
  (`<h1>` in backticks) stays literal text.
- Every thematic-break and underline-style heading line fails anywhere in the entry: `=`, `===`, `-`, `--`, `---`,
  `***`, `___`, `* * *` and `- - -`. The check does not guess from the previous line; a delimiter under `A | B` or
  `<em>Feature</em>` fails for being a delimiter. The same heading and delimiter rules apply after list and `>`
  prefixes are stripped, so `> #Feature`, `- #### Detail`, `> <em>Feature</em>` + `> ---` and `- ---` fail too.
- A code fence must open at the outer level, indented by at most 3 spaces. A fence inside a list item or block
  quote, a fence indented 4 or more columns (a tab counts as 4), and an indented fence after a list item (even after a
  blank line) are rejected with an explicit unsupported-construct message; none is read as code, so the lines after
  them are checked like any other line. The message for an indented fence says which case applies: indented 4 or more
  columns, or under the list item above it (put the fence at column 0 after a non-list line).
- Each problem with a line names it and quotes it in parentheses, shortened to 70 characters. A rejected heading,
  raw HTML tag or delimiter line also says how to fix it, for example `use one of the five "###" section names, or keep
  an issue-number line directly under its bullet with no blank line, or escape it as "\#720)"`. A rejected line gets
  only its own problems: it is not reported again as a paragraph or as a bullet with no docs reference. Inside an
  unsupported fence, a bullet or a `###` heading is still read, so a bullet there is still gated.
- A code fence closes only on a closer of exactly the opener's length, as the docs renderer (pymdownx.superfences)
  reads it. A longer closer fails (a four-backtick fence, a five-backtick line, then a four-backtick line): CommonMark
  closes there and the docs renderer does not, so they disagree on what follows. A shorter closer does not close.
- Code spans pair as the docs renderer (Python-Markdown with the pymdownx extensions in `mkdocs.yml`) pairs
  them, using its own backtick pattern: an opener closes at the next run of its own length, and without one at
  the first of the longest later runs, so ``` ``x` ``` is one span. A backtick after an odd number of backslashes
  opens no span, so
  ``\`<h2>Feature</h2>`` still fails as a raw heading. Because the renderer pairs across the lines of a paragraph,
  every visible line must pair its own backticks exactly: a run that closes at a run of another length, or not at
  all, fails with `an unpaired backtick run at line N`; escape a literal backtick as `` \` ``. A run of more than 8
  backticks fails anywhere in the entry, before anything pairs it, on the opener, body and closer lines of a code
  fence and inside a comment too. A backtick on a line that also shows text beside an
  HTML comment fails, because the renderer pairs backticks before it reads the comment; only a comment that starts a
  line may hold unpaired backticks on lines that show nothing else. A `<!--` in a
  code span is literal text and hides nothing, but an unclosed one is reported on its own line because a reader may
  take it for a comment.
- An HTML comment hides the lines after its own only where the docs renderer stores it as an HTML block: its `<!--`
  starts the line, indented by at most 3 spaces (under a list item too), and the first `-->` or `--!>` after it is
  `-->`. Only such a comment may span lines, blank lines included. Every other `<!--` must close with `-->` on its own
  line: one after `>` or `> >`, after a list marker (`- <!--`, `1. <!--`), after a backslash (`\<!--`, `\\<!--`) or
  other text, indented 4 or more columns or by a tab, or after a comment that starts the line. One that does not close
  there fails with `HTML comment at line N (...) does not close on its line and does not start it`, and it hides
  nothing: the lines after it are checked as visible lines, so a `> ### Feature` or `# Big` under it fails too. A
  comment that meets `--!>` before its `-->` fails and hides nothing, because the renderer then opens no comment. A
  line with a tag that the renderer's raw HTML pass ends with `>` on a later line (`x <a title="` followed by `y">`,
  or `x <a` followed by `<!-- y -->`) fails with `an HTML tag at line N (...) does not end on its line`, because that
  tag swallows a `<!--` between. The pass runs before code spans exist, so a tag in a code span counts. A `<` whose
  tag stops before any `>` is escaped as text and passes: `a<b comparisons` with no later `>`, and `` `a<b` `` or
  `` `List<int` ``, where the backtick after the tag name stops it. Fenced code is stored first, so a tag can run past
  a fence.
- A second visible `##` heading for the version being released fails wherever it appears, including `##v2.0.0`,
  an indented, quoted or listed copy, and one with a date or closing hashes.
- A line longer than 1000 characters fails anywhere in the entry, inside a fence or comment too, with
  `line N is longer than 1000 characters`. The check reports it before reading it and then treats it as a blank line.
  Wrap a long line instead. With `--newest`, a long line above the topmost version heading exits 2, because it could
  be that heading. With runs capped at 8 backticks, code spans are found in time linear in the text times 8, so
  backtick runs cannot make the check slow, but the line cap does not bound a gated bullet, which joins its
  continuation lines: the docs-link and `(no docs:` patterns are still quadratic in the length of one bullet (100
  lines of `[` take seconds).
- A code fence or HTML comment is allowed in `### Internal`, `### Documentation` and before the first `###`
  heading, but it must be closed and must not hide a `###` heading. An unclosed one fails the check.
- An entry runs to the next `## vX.Y.Z` heading. Any other `##` line inside it
  (`## Highlights`, or one inside a `<details>` block) fails the check, and so does a heading hidden behind a
  same-line comment (`<!-- x --> ### Fix`). Under the three gated headings, U+2028, U+2029, U+0085 and the form
  feed, vertical tab and `\x1c`-`\x1e` characters fail it too: Markdown does not break lines at them.
- A carriage return that is not part of a CRLF line ending fails the check, and so does a copy of the version
  heading being released inside an HTML comment or code fence (it confuses readers and other tools). Only ASCII
  digits make a `##` line a version heading.
- A `###` heading starts at column 0 and may have a tab after the `###` and a closing `###` (`### Internal ###`).
  It is read like any other heading, so it must be one of the five names above.

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
the changed files, exits 2 when it could not run, and has no bypass. With `--newest`, a topmost entry that is already
tagged passes; the changes after it are checked once the next entry is added.

**Cache marker changes need a minor release.** Raising `CACHE_VERSION` or `RUNNER_FIDELITY_VERSION` throws away every
user's warm cache, so the first run after upgrading is cold, and a patch release must not do that.
`scripts/check_cache_bump.py` compares both markers with their values at the same previous release tag as the cache
gate above. When either differs, the release fails unless (a) the version is at least a minor bump over that tag (a
higher `major.minor`; or the tag is a prerelease of `X.Y.0`, such as `1.15.0b0`, and the version stays on `X.Y`), and
(b) the entry has a bullet under `### Upgrade notes` whose visible text, in any letter case, contains both `cache` and
`rebuil` ("The first run after upgrading rebuilds the cache once."). Raw HTML tags with their attributes are not
visible, so wording there does not count. An image fails closed: from the first `![` outside a code span (a backslash
before it does not matter, and a reference-style image counts too) to the end of the bullet nothing counts, so put the
sentence before the image. Wording after a `{` outside a code span (an attribute list) does not count either, and
reference or abbreviation definition lines (`[label]: url`, `*[label]: text`) render nothing, so they do not count, and
a definition line ends the bullet: it and everything after it in the bullet do not count (the renderer also takes the
line after a `[label]:` definition when that line holds the title or the URL). Text
between tags, text inside a code span (even one that holds a tag or `![`) and an
autolink (`<https://...>`) are visible and count. A prerelease of `X.Y.0` means a version that sorts before `X.Y.0`
under PEP 440 (`1.15.0b0`, `rc`, `.devN`, `1.15.0rc1.post1`), and the version must stay on `X.Y` and not be lower than
the tag; `1.15.0.post1` and `1.15.0+local` are not prereleases, and a version that is not valid PEP 440 exits 2. Nothing
else about the wording is checked; the docs gate still wants a docs link or a `(no docs: <reason>)` exemption on
that bullet. It runs in the `Release PR Gates` job right after the cache gate (only when the version changed) and in
`verify-tag` after it, takes the version like the cache gate does (and `--newest` is supported, with the same
already-tagged pass), exits 1 naming each problem, exits 2 when it could not run, and has no bypass. `cut-release.yml`
does not run it, because #1047 retires that workflow. The hotfix case, a patch release cut from an older tag that
changes a marker, is tracked in #1015.
<!-- cspell:ignore rebuil -->

**Release CI gate and wip gate.** `release.yml` does not rerun the OS x Python test matrix. Its `ci-gate` job runs
`scripts/check_ci_passed.py` for the tagged commit: it looks up the `ci.yml` `push` run by SHA (not by branch) and
passes only when the run concluded `success` and every `Test (Python ..., ...)` and `Test (pytest ...)` job concluded
`success`. A skipped or missing test job fails it, because `ci.yml` skips the matrix when no source changed and the run
stays green. A queued or in-progress run is waited for (up to four hours). If no run exists at all, it waits 10
minutes, then fails saying the SHA has no main CI run (a tag on a branch other than main); with no passing run it
fails and names the SHA. Exit 2 means it could not query GitHub, never a pass. There is no bypass, and `build` needs
`ci-gate`, so every publish job sits behind it. `EXPECTED_TEST_JOBS` in the script is pinned to the `ci.yml` matrices
by a test: when you change a matrix, update it in the same PR. `verify-tag`, `large-tests`, `benchmark` and
`attrs-compat` still run in the release.

A release also fails if any `wip` test exists. `scripts/check_no_wip_tests.py` runs in `verify-tag` on the tagged
commit, before the docs build, and runs `pytest -m wip --collect-only -q` (seconds, runs nothing). Any collected test
carrying a `wip` marker fails the release, and so does a `@wip` tag found by reading `features/**/*.feature`. That
direct scan is what catches `@wip` scenarios (no pytest-bdd needed, and it does not depend on pytest collecting them).
Findings are listed. There is no bypass: an urgent fix that cannot wait for an unfinished feature is released from a
branch off the previous release tag, not from main. That path depends on #1015 (`ci.yml` must run for that branch);
until then the CI gate fails such a tag after the 10-minute grace. Re-dispatching `release.yml` for a tag whose commit
predates these gate scripts fails closed, because the gate scripts do not exist at that tag.

**Release blocker gate.** An open issue (or pull request) labeled `release-blocker` fails the release.
`scripts/check_no_release_blockers.py` looks the label up, then lists the open items that carry it. It runs in
`cut-release.yml` before the tag is created and in the `verify-tag` job of `release.yml`, so it also fails a
re-dispatch of `release.yml` that would finish a half-published release; the fix is the same. It prints each blocker as
`#N title` and exits 1. Exit 2 means it could not run (no token, API error, malformed answer), never a pass, and a
deleted or renamed label is exit 2 too, because an empty listing would otherwise pass without checking anything. There
is no bypass: no flag, environment variable or workflow input skips it. To clear it, remove the `release-blocker`
label from the issue, which leaves a visible record on the issue. `ci.yml` does not run it, so it never blocks an
ordinary pull request.

**Release PR gates.** The `Release PR Gates` job (`release-pr` in `ci.yml`) runs on every pull request and is part of
`All Checks Passed`. Its first step, `scripts/check_version_change.py`, runs from the default branch's copy: the step
exports it, and `scripts/check_release_docs.py` which it imports, from `origin/<default branch>` (the repository's
`default_branch`, not the pull request's base) into a fresh directory under `$RUNNER_TEMP` and runs that copy with the
runner's fixed system Python (`/usr/bin/python3 -E -s`, no uv, no checkout venv) against the pull request checkout. The
merge base is taken with the default branch too, so a stacked pull request, whose base is the lower layer's branch, can
supply neither the guard nor the base of the comparison. The guard is the job's first step after checkout, so no PR-head
code has run before it (setup-uv, `uv python install` and `uv sync` run later). So a pull request cannot weaken the
guard it is checked by. A missing default-branch copy exits 2, and so does a runner Python older than 3.11 (the guard
needs `tomllib`). The guard reads `pyproject.toml`, `__init__.py` and `CHANGELOG.md` as git blobs, at `HEAD` and at the
merge base alike, and exits 2 when one is not a regular file there (a symlink or submodule), so a symlink cannot make
the two sides read different content. It also exits 2 when a checked-out version file or the changelog differs from
its committed blob (a `.gitattributes` transform) or sits behind a symlink. The guard compares
`[project].version` with the merge base (a branch cut before main released reads as unchanged). The version counts as
changed when either `[project].version` or `__version__` in `src/pytest_gremlins/__init__.py` differs, and then the two
must be equal at `HEAD`. A pull request that changes the version must come from `release/v<version>` (the exact string,
prerelease included, e.g. `release/v1.15.0b0`), change only `pyproject.toml`, `uv.lock`,
`src/pytest_gremlins/__init__.py` and `CHANGELOG.md`, and have a topmost changelog entry for that version. Only then
does the job run the docs gate, the cache gate, the cache-bump gate and the wip gate, so this is the place where the
release PR gets checked, and a `wip` test never blocks an ordinary pull request. A version that is not PEP 440 shaped,
or a missing or non-literal `__version__`, exits 2. Exit 2 is never a pass, and there is no bypass. The
`cut-release.yml` path above is unchanged for now.

**Preparing the release branch.** `uv run python scripts/prepare_release.py [--increment PATCH|MINOR|MAJOR]
[--prerelease alpha|beta|rc]` builds the release branch locally. It refuses on `main`, with a dirty tree, when HEAD is
not `origin/main` (run `git fetch origin main && git switch --detach origin/main` first; a detached HEAD there is fine,
a work branch with its own commits is not, because the release PR guard rejects extra files), or when
`release/v<version>` already exists locally or on `origin`. It computes the version with
`cz bump --get-next`, switches to `release/v<version>`, runs `cz bump --files-only --yes` (`pyproject.toml`, `uv.lock`,
`__init__.py`; no commit or tag), checks that the computed version, `[project].version` and `__version__` agree, and
inserts a `## v<version> (date)` entry above the newest one. The entry has one placeholder bullet per commit since the
last tag that commitizen counts toward the bump (the commit subject sits on its own unwrapped line, cut at 90 characters
so the line fits in 120 columns, so its code span closes on its line), judged by commitizen's own configured
`bump_pattern` and `bump_map` over the whole message (so a `BREAKING CHANGE:` footer or a `fix:` body line counts; a
commit takes its highest increment: MAJOR under `### Upgrade notes`, MINOR under `### Feature`, PATCH under `### Fix`).
A conventional commit commitizen does not bump on (`chore:`, `docs:`) also gets a bullet, under `### Fix`; `bump:`
subjects and non-conventional subjects get none unless their body bumps. Every bullet sits under a gated heading, so the
docs gate fails until each is rewritten and given a docs link or `(no docs: <reason>)` (or moved to Internal or
Documentation). A major release (a forced `--increment MAJOR` or a breaking change) always has at least one placeholder
under `### Upgrade notes`; when no commit is conventional (a forced `--increment` over `Revert ...` commits, say) it
adds one generic placeholder under `### Fix`, so an untouched entry never passes the gate. When a cache marker differs
from its value at the newest `v*` tag, it computes at least the next minor version: it behaves as `--increment MINOR`
when commitizen would only patch, keeps a computed minor or major and `--prerelease`, and refuses `--increment PATCH`
with a message naming the marker. It also adds a placeholder under `### Upgrade notes` about the one-time cache
rebuild. The placeholder does not contain the words the cache-bump gate looks for, so the entry fails until a person
writes the sentence. If the markers cannot be compared (no reachable `v*` tag, or an unreadable marker file), it warns
on stderr and continues without the minor bump or the placeholder, and the cache-bump gate still checks the release PR.
It never commits, tags or pushes: fill in the entry, add a `(cache kept: <reason>)` line if the cache gate needs one,
commit signed, push and open the PR. Merging it starts the primary release path: `tag-release.yml` tags the merge
commit and dispatches `release.yml` (next paragraph). `cut-release.yml` remains the fallback (#1047 deletes it).

**Tag release.** `.github/workflows/tag-release.yml` runs on every push to `main` and is the primary way a release
starts: `scripts/prepare_release.py` -> `release/v<version>` PR (the `Release PR Gates` job checks it) -> merge ->
`tag-release.yml` tags the merge commit and dispatches `release.yml` -> the `pypi` environment approval. The YAML is thin:
it checks out two commits (`fetch-depth: 2`, `persist-credentials: false`), exports `tag_release.py` and the scripts it
runs from the commit before the push (`git show "$BEFORE:scripts/<name>"`, `BEFORE` being `github.event.before`, into a
fresh directory under `$RUNNER_TEMP`) and runs that copy with `/usr/bin/python3 -I` from outside the workspace. An empty,
all-zero or missing `BEFORE` (with `fetch-depth: 2` it is present only when the push added one commit) or a missing script
exits 2. A version-changing commit is released only when its parent equals `BEFORE`, so a push of several commits is never
released. So a release commit cannot edit `tag_release.py`, the blocker gate or the version guard to skip a check.
`scripts/tag_release.py` decides
what to do from the version at the pushed commit and at its parent, and from the commit `refs/tags/v<version>`
peels to on origin (`git ls-remote`, because the checkout has no tags; an annotated tag has an object of its own, so
the peeled commit is what is compared):

| Version changed vs parent | Tag on origin | Action |
| --- | --- | --- |
| No | exists | Nothing; logs `v<version> already tagged`. |
| No | missing | Fails (exit 1), tags nothing: a later commit holds changes the gates never saw. |
| Yes | missing | Version guard, release-blocker gate, annotated tag, dispatch. |
| Yes | peels to this commit | Dispatch only (a re-run). |
| Yes | peels elsewhere | Fails (exit 1), dispatches nothing. |

For the version-changing rows the script first looks up the release pull request (`GET /commits/{sha}/pulls`). With
exactly one merged pull request from this repository, the rows above apply. With none and the tag peeling to this commit,
the `cut-release.yml` fallback made it (its own tag push runs `release.yml`): a no-op, exit 0. With none and no tag, it
fails (exit 1). A merged pull request from a fork, or more than one, always fails.

Any failed lookup or API call exits 2 and tags nothing. Only the version-changing commit is tagged. Before tagging, the
script runs the version guard on the pushed commit against its parent, with `--base-ref "$SHA^"` and the release pull
request's branch, using the before-push copy of `check_version_change.py` and `check_release_docs.py`, like the
`release-pr` job does. It then runs `check_no_release_blockers.py`. The docs, cache and wip gates are not repeated:
`verify-tag` in `release.yml` runs them before anything is published. The tag is created through the REST API
(`git/tags`, then `git/refs`) as `github-actions[bot]` with the job's `GITHUB_TOKEN` (`contents: write`, `actions: write`,
`issues: read`, `pull-requests: read`); no personal access token is used. A tag created that way does not fire
`release.yml`'s tag-push trigger, so the `gh workflow run release.yml --ref main -f tag=v<version>` the script makes
is the only release run.

Limit, plainly: GitHub runs a push workflow from the file at the pushed commit. The script refuses a version-changing
commit that edits `tag-release.yml`, but a commit that rewrites the workflow runs its own YAML, so only review of changes
to `tag-release.yml` stands between that and a tag made without the checks. The guard-before-tag does not make the
workflow tamper-proof. Bootstrap: the first push after this lands has no before-push copy of `tag_release.py`, so that
one run fails closed at the export step (exit 2) once; it is not a release commit (the version is unchanged and
already tagged), and the next push works.

Recovery: the concurrency group holds one pending run, so a quick third push cancels a pending one, and a run can fail
for a transient reason. If the release commit's own run did not finish, the next push (version unchanged, tag missing)
fails with "not tagged". If the tag was created and only the dispatch failed, the next push is green ("already
tagged"), so only the release commit's own red run shows it. Either way, re-run the release commit's own
`tag-release.yml` run (`gh run rerun <run-id>`): it re-evaluates that same SHA and `BEFORE`, and tags or dispatches as
the table says. Cut a new release only if that cannot work.

**Fallback -- cut a release with `cut-release.yml`.** Use it only when `tag-release.yml` cannot (until #1047 deletes it).
`cz bump` runs only through `scripts/prepare_release.py` (`--files-only`, no commit or tag) or on the Actions runner in
this workflow; never run a full `cz bump` by hand: the `no-commit-to-branch` pre-commit hook blocks commits to `main`
and leaves a dirty version bump to revert.

```bash
gh workflow run cut-release.yml --repo mikelane/pytest-gremlins
```

This runs `cz bump` on the GitHub Actions runner (no local hooks), commits the version,
creates an annotated tag, and pushes -- which triggers `release.yml`.

**Verify the tag landed** (either path):

```bash
git fetch --tags
git ls-remote --tags origin | tail -5
```

If the tag is missing, `--follow-tags` silently skipped a lightweight tag. Root cause:
`[tool.commitizen]` must have `annotated_tag = true`. Without it, commitizen creates
lightweight tags that `--follow-tags` ignores.

**Escape hatch -- Test PyPI is down.** `release.yml` normally runs from the dispatch `tag-release.yml` makes (or from
the tag push on the `cut-release.yml` fallback path) and gates
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
  `pyproject.toml` at that tag. The tag must already exist (see "Verify the tag landed" above).
- A `concurrency` group keyed on the release tag never cancels a running release for that tag,
  so two runs cannot race to PyPI. A new run waits as pending; the group holds one pending run,
  so dispatching again cancels the earlier pending run. Cancel a stuck run yourself (step 1).
- Safe to re-dispatch: the PyPI publish uses `skip-existing`, so a run that already uploaded but
  failed later (for example at the GitHub Release) can be re-run to finish. PyPI keeps the files
  from the first upload; the rebuilt files are not re-uploaded there.
- The dispatched run re-runs the release-only gates (large tier, benchmarks, attrs compatibility) on the
  tagged commit and re-checks that main CI passed for it. It does not rerun the OS x Python matrix, so it
  takes about as long as the large tier and the benchmarks.
- With `skip_test_pypi=true`, `publish-test-pypi` and `verify-test-pypi` are skipped. The
  `verify-wheel` job runs in every release and replaces the install check by installing the
  built wheel into a fresh venv and comparing its `__version__` to the tag.
- Omit `skip_test_pypi` (or pass `false`) to re-run the full chain, Test PyPI included.
- The GitHub Release is created for `tag`, not for the branch the workflow was dispatched from.

**RELEASE_PAT secret**: Only the fallback `cut-release.yml` needs it; `tag-release.yml` uses no personal access
token. It requires a `RELEASE_PAT` repo secret with
`contents: write` and `workflows: write` scopes. Set it to never expire — an expired
PAT causes a silent checkout failure with no useful error message.

## Demo Videos

Narrated MP4 demos live on YouTube (not committed to git). The `.gitignore` excludes `*.mp4` and `*.webm`.

Demo project files live under `/tmp/gremlin-demo-<epic>` (or similar per-epic dirs).
Each demo project's `pyproject.toml` must include `pytest-xdist` as a dependency —
the dev plugin registers a `pytest_configure_node` hook that pluggy rejects at
`check_pending()` if xdist is absent, causing silent `pytest_sessionfinish` failure
(the HTML report never writes).
