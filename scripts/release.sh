#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/release.sh [--patch|--minor|--major]
# Default: auto-detect from conventional commits

INCREMENT_ARGS=()
case "${1:-auto}" in
  --patch) INCREMENT_ARGS=(--increment PATCH) ;;
  --minor) INCREMENT_ARGS=(--increment MINOR) ;;
  --major) INCREMENT_ARGS=(--increment MAJOR) ;;
  auto)    INCREMENT_ARGS=() ;;
  *)       echo "Usage: $0 [--patch|--minor|--major]"; exit 1 ;;
esac

# Show what's about to be released
echo "Unreleased commits:"
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [[ -n "$LAST_TAG" ]]; then
  git log --oneline "${LAST_TAG}..HEAD"
else
  echo "(no previous tag — this will be the first release)"
  git log --oneline
fi
echo ""

# Bump version (updates pyproject.toml, __init__.py, CHANGELOG.md, creates commit + tag)
uv run cz bump --yes "${INCREMENT_ARGS[@]}"

# Push the bump commit and tag — triggers release.yml
git push origin HEAD --follow-tags

echo ""
echo "Release triggered. Watch progress:"
echo "  https://github.com/mikelane/pytest-gremlins/actions/workflows/release.yml"
