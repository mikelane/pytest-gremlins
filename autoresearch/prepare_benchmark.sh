#!/usr/bin/env bash
# prepare_benchmark.sh — Immutable evaluation harness for autoresearch.
# Measures cold-cache pytest-gremlins runtime on attrs.
# Outputs JSON to stdout: {"wall_time_seconds": <float>, "gremlins_found": <int>}
#
# Usage: ./autoresearch/prepare_benchmark.sh /path/to/pytest-gremlins-source
#
# This script is IMMUTABLE during autoresearch runs.
# The agent must NEVER edit this file.
#
# Output format note: pytest-gremlins terminal summary prints:
#   Zapped: N gremlins (XX%)
#   Survived: N gremlins (XX%)
# gremlins_found = zapped + survived (total gremlins exercised).

set -euo pipefail

GREMLINS_SRC="${1:?Usage: prepare_benchmark.sh /path/to/pytest-gremlins-source}"
ATTRS_VERSION="25.3.0"
BENCHMARK_DIR=""

cleanup() {
    if [[ -n "$BENCHMARK_DIR" && -d "$BENCHMARK_DIR" ]]; then
        rm -rf "$BENCHMARK_DIR"
    fi
}
trap cleanup EXIT

# Create isolated temp directory — guarantees cold cache
BENCHMARK_DIR="$(mktemp -d /tmp/gremlins-bench-XXXXXX)"

# Create a minimal virtual environment
uv venv "$BENCHMARK_DIR/.venv" --quiet
source "$BENCHMARK_DIR/.venv/bin/activate"

# Install pinned attrs + pytest
uv pip install "attrs==$ATTRS_VERSION" pytest --quiet

# Install pytest-gremlins from current source (editable so changes take effect)
uv pip install -e "$GREMLINS_SRC" --quiet

# Clone attrs test suite into the benchmark dir
# We use pip download + extract to get the source with tests
uv pip download "attrs==$ATTRS_VERSION" --no-binary :all: --dest "$BENCHMARK_DIR/downloads" --quiet
tar xzf "$BENCHMARK_DIR/downloads"/attrs-*.tar.gz -C "$BENCHMARK_DIR" --strip-components=1 2>/dev/null \
    || unzip -qo "$BENCHMARK_DIR/downloads"/attrs-*.zip -d "$BENCHMARK_DIR/attrs-src" 2>/dev/null

# Find the attrs source directory (handles both tar.gz and zip layouts)
ATTRS_DIR="$(find "$BENCHMARK_DIR" -name "pyproject.toml" -path "*/attrs*" -exec dirname {} \; | head -1)"
if [[ -z "$ATTRS_DIR" ]]; then
    # Fallback: find any pyproject.toml that isn't from gremlins itself
    ATTRS_DIR="$(find "$BENCHMARK_DIR" -name "pyproject.toml" -not -path "$GREMLINS_SRC/*" -exec dirname {} \; | head -1)"
fi
if [[ -z "$ATTRS_DIR" ]]; then
    echo '{"error": "Could not find attrs source directory"}' >&2
    exit 1
fi

# Ensure no gremlins cache exists (cold cache guarantee)
rm -rf "$ATTRS_DIR/.gremlins_cache"

# Run gremlins benchmark with wall-clock timing
# Capture both timing and output
GREMLINS_OUTPUT_FILE="$BENCHMARK_DIR/gremlins_output.txt"
START_TIME=$(python3 -c "import time; print(time.monotonic())")

cd "$ATTRS_DIR"
# Run pytest-gremlins, capturing output for gremlin count parsing
# Note: venv is already activated, so call pytest directly (not uv run)
pytest --gremlins -x --no-header -q src/ 2>&1 | tee "$GREMLINS_OUTPUT_FILE" >&2 || true

END_TIME=$(python3 -c "import time; print(time.monotonic())")

# Calculate wall time
WALL_TIME=$(python3 -c "print(${END_TIME} - ${START_TIME})")

# Parse gremlin count from output.
# The gremlins report lines look like:
#   Zapped: N gremlins (XX%)
#   Survived: N gremlins (XX%)
# Sum zapped + survived to get total gremlins exercised.
ZAPPED=$(grep -oE 'Zapped: [0-9]+' "$GREMLINS_OUTPUT_FILE" | grep -oE '[0-9]+' || echo "0")
SURVIVED=$(grep -oE 'Survived: [0-9]+' "$GREMLINS_OUTPUT_FILE" | grep -oE '[0-9]+' || echo "0")

# Output JSON to stdout (this is what the outer loop reads)
python3 -c "
import json, sys
zapped = int('${ZAPPED}') if '${ZAPPED}' else 0
survived = int('${SURVIVED}') if '${SURVIVED}' else 0
print(json.dumps({
    'wall_time_seconds': round(float('${WALL_TIME}'), 3),
    'gremlins_found': zapped + survived,
}))
"
