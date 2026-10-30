# Contributing

See the [CONTRIBUTING.md](https://github.com/mikelane/pytest-gremlins/blob/main/CONTRIBUTING.md) file in
the repository for detailed contribution guidelines.

## Quick Summary

1. Fork the repository
2. Create a feature branch in a git worktree
3. Follow TDD (write tests first!)
4. Use conventional commits
5. Submit a pull request

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/pytest-gremlins.git
cd pytest-gremlins
uv sync --dev
uv run pre-commit install
```

## Running Tests

```bash
uv run pytest tests/small  # Fast unit tests
uv run pytest              # All tests
```

## Verdict Change Check

The incremental cache keeps each gremlin's verdict until `CACHE_VERSION`
(`src/pytest_gremlins/cache/versions.py`) or `RUNNER_FIDELITY_VERSION`
(`src/pytest_gremlins/cache/incremental.py`) changes. A PR that changes a verdict without raising
one of them leaves every user with a warm cache on the old verdict.

**When it runs.** The `Verdict Change Check` CI job runs on a PR or merge group that changes a
file the cache-version guard covers: every `.py` file under `src/pytest_gremlins/` except the
ones listed in `EXCLUDED_FROM_GUARD` in `tests/cache/test_cache_version_guard.py`. Deleting a
package module counts too, and so does editing the guard test itself. For any other change the job
is skipped, and `All Checks Passed` does not wait for it.

The job runs pytest-gremlins, with the cache off, on the fixed sample project in
`tests/fixtures/verdict_sample/`, once with the base branch's package and once with the PR's,
and compares the verdict of every gremlin. The sample has at least one gremlin per built-in
operator and covers the zapped, survived, timeout, collection-kill and rerun paths. It only
catches verdict changes the sample exercises.

**When it fails.** The log names each gremlin that was added, removed or changed verdict, and
the marker to raise:

- Gremlins were added or removed: your change alters what gets mutated. Raise `CACHE_VERSION`.
- Only verdicts changed: your change alters test execution or how an outcome becomes a verdict.
  Raise `RUNNER_FIDELITY_VERSION`, or `CACHE_VERSION` if it alters what gets mutated instead.

Raise the marker, update `RECORDED_CACHE_VERSION` or `RECORDED_RUNNER_FIDELITY_VERSION` and
`RECORDED_DIGESTS` in the guard test, and push. The job passes once a marker is raised above the
base branch's. Markers only go up: lowering one fails the job, with one exception. A marker that landed after
the latest release was never written to a user's cache, so it may go back down to the value at the newest release tag
reachable from the base, as long as no sample verdict changed. Lowering below the released value always fails, and
so does lowering when no release tag can be found. If the verdict change is a bug,
fix the code instead. A change that alters no verdict, such as a refactor or a docstring edit,
passes without a bump, so users keep a warm cache.

To run the check locally against `main`:

```bash
uv run python scripts/check_verdict_change.py guarded-changes "$(git merge-base origin/main HEAD)"
uv run python scripts/check_verdict_change.py run --out head.json
# Install the base package (uv pip install --no-deps --reinstall <checkout of main>), then:
uv run --no-sync python scripts/check_verdict_change.py run --out base.json
uv run --no-sync python scripts/check_verdict_change.py compare base.json head.json \
  --released-ref "$(git merge-base origin/main HEAD)"
```

## Release Cache Check

The per-PR check above only sees verdict changes that its sample project exercises. At release time a second check
covers the rest: `scripts/check_cache_kept.py` compares the guarded code (the same file set as above, computed by the
guard test's own function) at the previous release with the code being released. The previous release is the newest
`v*` tag reachable from the commit being released, not counting the tag being released.

The release passes when any of these holds:

- No guarded file changed since the previous release.
- `CACHE_VERSION` or `RUNNER_FIDELITY_VERSION` differs from its value at the previous release.
- The release's `CHANGELOG.md` entry has a `(cache kept: <reason>)` line.

Otherwise the check exits 1 and names the changed files. Use the line when guarded code changed but no cached verdict
can be wrong, for example `(cache kept: only log wording and type hints changed)`. The reason must not be empty. It is
public and is reviewed in the changelog PR, so keeping the cache across a change to verdict code is one visible
decision per release. If a verdict could change, raise a marker instead.

Put the line in the entry's prose, before its first `###` heading. It counts nowhere else, because the release docs
gate allows only list items under `### Upgrade notes`, `### Feature` and `### Fix`. A line in an HTML comment,
a code fence or a code span does not count.

```markdown
## vX.Y.Z (YYYY-MM-DD)

**One sentence on what changes for users.**

(cache kept: only log wording and type hints changed)

### Fix
```

The check runs in the same three places as the release docs gate: the `CHANGELOG.md` check in `ci.yml`, `cut-release.yml`
before the tag is created, and the `verify-tag` job of `release.yml`. There is no bypass: no flag, environment
variable or workflow input skips it. To run it locally, fetch the tags and run
`uv run python scripts/check_cache_kept.py --newest`. A lowered marker is rejected by the per-PR check, not by this one.

## Code of Conduct

Please read and follow our [Code of Conduct](https://github.com/mikelane/pytest-gremlins/blob/main/CODE_OF_CONDUCT.md).
