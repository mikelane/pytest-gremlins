#!/usr/bin/env bash
set -euo pipefail

# Cut a release: bump version, update CHANGELOG.md, push commit + tag.
# The tag push triggers the release.yml pipeline (tests, PyPI publish, GitHub Release).
#
# Usage: ./scripts/release.sh [--patch|--minor|--major]
# Default: auto-detect bump type from conventional commits

# ---------------------------------------------------------------------------
# Observability: structured failure reporting via trap
# ---------------------------------------------------------------------------
release_step="init"

cleanup() {
  local exit_code=$?
  if [[ $exit_code -ne 0 ]]; then
    echo "" >&2
    echo "RELEASE FAILED at step '${release_step}' (exit code: ${exit_code})" >&2
    echo "  Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
    echo "" >&2
    echo "Troubleshooting:" >&2
    case "${release_step}" in
      resolve-tag)
        echo "  - git describe failed. Is this a shallow clone? Try: git fetch --unshallow" >&2
        ;;
      bump)
        echo "  - commitizen bump failed." >&2
        echo "  - Are there conventional commits since the last tag?" >&2
        echo "  - Run: uv run cz log --unreleased" >&2
        echo "  - Check pyproject.toml [tool.commitizen] configuration." >&2
        ;;
      push)
        echo "  - git push failed." >&2
        echo "  - Check authentication (SSH key, token, credential helper)." >&2
        echo "  - Check branch protection rules on the target branch." >&2
        echo "  - Check network connectivity." >&2
        ;;
      *)
        echo "  - Unexpected failure during step '${release_step}'." >&2
        ;;
    esac
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
release_step="parse-args"

increment_args=()
case "${1:-auto}" in
  --patch) increment_args=(--increment PATCH) ;;
  --minor) increment_args=(--increment MINOR) ;;
  --major) increment_args=(--increment MAJOR) ;;
  auto)    increment_args=() ;;
  *)       echo "Usage: $0 [--patch|--minor|--major]" >&2; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
release_step="preflight"

branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$branch" != "main" ]]; then
  echo "Error: You're on branch '${branch}'. Switch to 'main' before releasing." >&2
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: You have uncommitted changes. Commit or stash them first." >&2
  git status --short >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Show unreleased commits
# ---------------------------------------------------------------------------
release_step="resolve-tag"

echo "Commits since last release:"
last_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [[ -n "$last_tag" ]]; then
  commit_count=$(git rev-list --count "${last_tag}..HEAD")
  if [[ "$commit_count" -eq 0 ]]; then
    echo "Error: No commits since ${last_tag}. Merge new changes to main before releasing." >&2
    exit 1
  fi
  echo "  (${commit_count} commits since ${last_tag})"
  git log --oneline "${last_tag}..HEAD"
else
  echo "(No previous tag found -- this will be the first release.)"
  git log --oneline
fi
echo ""

# ---------------------------------------------------------------------------
# Bump version (updates pyproject.toml, __init__.py, CHANGELOG.md, creates commit + tag)
# ---------------------------------------------------------------------------
release_step="bump"
echo "Bumping version..."
uv run cz bump --yes "${increment_args[@]}"

new_tag=$(git describe --tags --abbrev=0)
echo "Version bumped to ${new_tag}."

# ---------------------------------------------------------------------------
# Push the bump commit and tag -- this triggers the release.yml pipeline
# ---------------------------------------------------------------------------
release_step="push"
echo "Pushing commit and tag..."
git push origin HEAD --follow-tags

release_step="done"
echo ""
echo "Release ${new_tag} pushed successfully."
echo "  Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  Monitor: https://github.com/mikelane/pytest-gremlins/actions/workflows/release.yml"
