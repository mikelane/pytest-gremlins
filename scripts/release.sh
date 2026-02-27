#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/release.sh [--patch|--minor|--major]
# Default: auto-detect from conventional commits

INCREMENT_FLAG=""
case "${1:-auto}" in
  --patch) INCREMENT_FLAG="--increment PATCH" ;;
  --minor) INCREMENT_FLAG="--increment MINOR" ;;
  --major) INCREMENT_FLAG="--increment MAJOR" ;;
  auto)    INCREMENT_FLAG="" ;;
  *)       echo "Usage: $0 [--patch|--minor|--major]"; exit 1 ;;
esac

# Show what's about to be released
echo "Unreleased commits:"
git log --oneline "$(git describe --tags --abbrev=0)"..HEAD
echo ""

# Bump version (updates pyproject.toml, __init__.py, CHANGELOG.md, creates commit + tag)
uv run cz bump --yes $INCREMENT_FLAG

# Push the bump commit and tag — triggers release.yml
git push origin main --follow-tags

echo ""
echo "Release triggered. Watch progress:"
echo "  https://github.com/mikelane/pytest-gremlins/actions/workflows/release.yml"
