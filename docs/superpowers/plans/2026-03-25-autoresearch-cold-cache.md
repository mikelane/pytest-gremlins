# Autoresearch Cold Cache Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Autoresearch-style loop that lets Claude Code autonomously optimize pytest-gremlins cold cache
runtime on attrs overnight, producing a branch of verified speed improvements.

**Architecture:** A shell script outer loop launches fresh Claude Code sessions (via `claude -p`), each given 15
minutes to propose and implement one optimization. After each session, an immutable benchmark script measures cold
cache wall time and gremlin count on attrs. Improvements are committed; regressions are reverted. A
`program.md.template` carries instructions, constraints, and experiment history to each session.

**Tech Stack:** Bash (shell loop), Claude Code CLI (`claude -p`), pytest-gremlins, attrs (benchmark target),
jq (JSON processing), git, gtimeout (coreutils)

**Prerequisites:** `brew install coreutils` (provides `gtimeout` for session timeout enforcement)

**Issue:** #336

**Worktree:** `.worktrees/issue-336-autoresearch`

---

## File Structure

```text
autoresearch/
├── program.md.template       ← Agent instruction template with placeholders
├── prepare_benchmark.sh      ← Immutable evaluation harness (cold cache on attrs)
├── run_autoresearch.sh       ← Outer loop controller
├── baseline_metrics.json     ← Written once at start (by run_autoresearch.sh)
├── best_metrics.json         ← Updated on each improvement
└── experiment_log.json       ← Append-only history of all experiments
```

No test files — these are shell scripts verified manually per issue #336 out-of-scope decision.

---

## Task 1: `prepare_benchmark.sh` — The Immutable Evaluation Harness

This is the `prepare.py` equivalent. It creates a clean environment, installs the current gremlins source, runs
`pytest --gremlins` on a pinned attrs version with no cache, and outputs JSON metrics to stdout.

**Files:**

- Create: `autoresearch/prepare_benchmark.sh`

- [ ] **Step 1: Create the benchmark script with argument parsing**

```bash
#!/usr/bin/env bash
# prepare_benchmark.sh — Immutable evaluation harness for autoresearch.
# Measures cold-cache pytest-gremlins runtime on attrs.
# Outputs JSON to stdout: {"wall_time_seconds": <float>, "gremlins_found": <int>}
#
# Usage: ./autoresearch/prepare_benchmark.sh /path/to/pytest-gremlins-source
#
# This script is IMMUTABLE during autoresearch runs.
# The agent must NEVER edit this file.

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

# Parse gremlin count from output
# The gremlins report line looks like: "X gremlins released, Y zapped, Z survived"
GREMLINS_FOUND=$(grep -oE '[0-9]+ gremlins released' "$GREMLINS_OUTPUT_FILE" | grep -oE '[0-9]+' || echo "0")

# Output JSON to stdout (this is what the outer loop reads)
python3 -c "
import json, sys
print(json.dumps({
    'wall_time_seconds': round(float('${WALL_TIME}'), 3),
    'gremlins_found': int('${GREMLINS_FOUND}'),
}))
"
```

- [ ] **Step 2: Make it executable and test manually**

```bash
chmod +x autoresearch/prepare_benchmark.sh
# Run it once to verify it works and see baseline numbers
./autoresearch/prepare_benchmark.sh /Users/mikelane/dev/pytest-gremlins/.worktrees/issue-336-autoresearch
```

Expect: JSON output to stdout with `wall_time_seconds` and `gremlins_found`.
This will take a minute or two — it's installing deps and running gremlins on attrs.

- [ ] **Step 3: Debug and fix any issues**

Common problems to watch for:

- attrs source download format (tar.gz vs zip vs wheel)
- `uv run pytest` may need `--gremlins` flag adjustments based on current CLI
- Gremlin count regex may need adjustment based on actual output format

Run `./autoresearch/prepare_benchmark.sh <src>` repeatedly until it produces clean JSON.

- [ ] **Step 4: Commit**

```bash
git add autoresearch/prepare_benchmark.sh
git commit -m "feat(autoresearch): add prepare_benchmark.sh evaluation harness

Immutable script that measures cold-cache gremlins runtime on attrs.
Outputs JSON with wall_time_seconds and gremlins_found.
Part of #336.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: `program.md.template` — The Agent's Instructions

This is what Claude reads at the start of each experiment. Contains instructions, constraints, and placeholders
for metrics/history that the shell templates.

**Files:**

- Create: `autoresearch/program.md.template`

- [ ] **Step 1: Create the template**

```markdown
# Autoresearch: Optimize pytest-gremlins Cold Cache Runtime

You are optimizing pytest-gremlins for cold-cache runtime performance on the attrs library.

## Your Goal

Make `pytest --gremlins` run faster on attrs (cold cache — no `.gremlins_cache/` present)
while finding the same number (or more) gremlins.

You have 15 minutes. Propose ONE hypothesis, implement it, and verify gremlins' own tests
still pass.

## Current Metrics

- **Baseline wall time**: {{BASELINE_TIME}}s
- **Current best wall time**: {{BEST_TIME}}s
- **Improvement so far**: {{IMPROVEMENT_PCT}}%
- **Baseline gremlin count (floor)**: {{BASELINE_GREMLINS}} gremlins
- **Experiment number**: {{EXPERIMENT_NUMBER}}

## Focus Areas (rough priority order)

- AST traversal and instrumentation speed
- Coverage collection overhead
- Mutation switching dispatch
- Import/module loading time
- Parallel worker startup cost
- Cache serialization (the cache WRITE on first run is part of cold-cache wall time)
- Data structure choices (dicts vs dataclasses vs slots)
- Unnecessary work during the critical path

## Constraints (violations = auto-reject)

- Gremlin count MUST be >= {{BASELINE_GREMLINS}}
- All tests in `uv run pytest tests -m small` MUST pass
- Do NOT edit anything outside src/pytest_gremlins/
- Do NOT change the public plugin API (pytest flags, config keys)
- Do NOT remove mutation operators — you may optimize them
- Do NOT add external dependencies without strong justification
- Do NOT modify files in the autoresearch/ directory

## Your Workflow

1. Read the experiment history below to learn what has been tried
2. Read the relevant source files in src/pytest_gremlins/
3. Form a hypothesis — write a one-line summary to `autoresearch/.hypothesis`
4. Implement the change (keep it focused — ONE idea per experiment)
5. Run: `uv run pytest tests -m small --tb=short -q`
6. If tests pass, you're done — exit cleanly
7. If tests fail, write `true` to `autoresearch/.test_failed`, revert your changes, and exit

## Important

- The benchmark will be run AFTER you exit, by the outer loop — not by you
- Focus on implementation quality, not measurement
- Small, focused changes are better than sweeping rewrites
- If your idea requires touching many files, that's fine — but the change should be cohesive

## Experiment History (last 20)

{{EXPERIMENT_HISTORY}}
```

- [ ] **Step 2: Commit**

```bash
git add autoresearch/program.md.template
git commit -m "feat(autoresearch): add program.md.template agent instructions

Template with placeholders for metrics and experiment history.
Carries instructions, constraints, and focus areas for each Claude session.
Part of #336.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: `run_autoresearch.sh` — The Outer Loop

The main orchestrator. Establishes baseline, creates experiment branch, loops through Claude sessions,
benchmarks, commits or reverts, and stops on time/plateau.

**Files:**

- Create: `autoresearch/run_autoresearch.sh`

- [ ] **Step 1: Create the script with configuration section**

The script header with configurable parameters and helper functions:

```bash
#!/usr/bin/env bash
# run_autoresearch.sh — Outer loop for autoresearch optimization.
#
# Usage: ./autoresearch/run_autoresearch.sh [OPTIONS]
#   --max-hours N      Maximum hours to run (default: 8)
#   --max-plateau N    Stop after N consecutive non-improvements (default: 10)
#   --timeout N        Seconds per Claude session (default: 900)
#   --threshold N      Minimum improvement % to accept (default: 2)
#   --model MODEL      Claude model to use (default: sonnet)
#   --dry-run          Run one cycle and exit
#
# This script is IMMUTABLE during autoresearch runs.

set -euo pipefail

# --- Configuration ---
MAX_HOURS="${MAX_HOURS:-8}"
MAX_PLATEAU="${MAX_PLATEAU:-10}"
SESSION_TIMEOUT="${SESSION_TIMEOUT:-900}"
IMPROVEMENT_THRESHOLD="${IMPROVEMENT_THRESHOLD:-2}"
MODEL="${MODEL:-sonnet}"
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-hours) MAX_HOURS="$2"; shift 2 ;;
        --max-plateau) MAX_PLATEAU="$2"; shift 2 ;;
        --timeout) SESSION_TIMEOUT="$2"; shift 2 ;;
        --threshold) IMPROVEMENT_THRESHOLD="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# --- Paths ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BENCHMARK_SCRIPT="$SCRIPT_DIR/prepare_benchmark.sh"
TEMPLATE="$SCRIPT_DIR/program.md.template"
BASELINE_FILE="$SCRIPT_DIR/baseline_metrics.json"
BEST_FILE="$SCRIPT_DIR/best_metrics.json"
LOG_FILE="$SCRIPT_DIR/experiment_log.json"

# --- Helpers ---
now_epoch() { python3 -c "import time; print(time.time())"; }
now_iso() { python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).isoformat())"; }
json_get() { python3 -c "import json,sys; print(json.load(open('$1'))['$2'])"; }

# Requires: brew install coreutils (provides gtimeout on macOS)
if ! command -v gtimeout &>/dev/null; then
    echo "Error: gtimeout not found. Install with: brew install coreutils" >&2
    exit 1
fi

log_experiment() {
    local num="$1" hypothesis="$2" wall_time="$3" gremlins="$4" accepted="$5" reason="$6"
    local files_changed
    files_changed=$(git diff --name-only HEAD 2>/dev/null \
        | python3 -c "import json,sys; print(json.dumps(sys.stdin.read().strip().split('\n')))" \
        2>/dev/null || echo '[]')

    python3 -c "
import json, sys
entry = {
    'experiment_number': $num,
    'timestamp': '$(now_iso)',
    'hypothesis': '''$hypothesis''',
    'wall_time_seconds': $wall_time,
    'gremlins_found': $gremlins,
    'accepted': $accepted,
    'reason': '$reason',
    'files_changed': json.loads('$files_changed')
}
log = json.loads(open('$LOG_FILE').read()) if __import__('os').path.exists('$LOG_FILE') else []
log.append(entry)
json.dump(log, open('$LOG_FILE', 'w'), indent=2)
"
}

template_prompt() {
    local experiment_num="$1"
    local baseline_time baseline_gremlins best_time improvement_pct history

    baseline_time=$(json_get "$BASELINE_FILE" wall_time_seconds)
    baseline_gremlins=$(json_get "$BASELINE_FILE" gremlins_found)
    best_time=$(json_get "$BEST_FILE" wall_time_seconds)
    improvement_pct=$(python3 -c "print(round((1 - $best_time / $baseline_time) * 100, 1))")

    # Get last 20 experiments as formatted history
    if [[ -f "$LOG_FILE" ]]; then
        history=$(python3 -c "
import json
log = json.load(open('$LOG_FILE'))
for e in log[-20:]:
    status = 'ACCEPTED' if e['accepted'] else f\"REJECTED ({e['reason']})\"
    print(f\"Experiment {e['experiment_number']}: {e['hypothesis']}\")
    print(f\"  Wall time: {e['wall_time_seconds']}s | Gremlins: {e['gremlins_found']} | {status}\")
    print()
")
    else
        history="No experiments yet. You are the first."
    fi

    # Template the prompt
    sed \
        -e "s|{{BASELINE_TIME}}|$baseline_time|g" \
        -e "s|{{BEST_TIME}}|$best_time|g" \
        -e "s|{{IMPROVEMENT_PCT}}|$improvement_pct|g" \
        -e "s|{{BASELINE_GREMLINS}}|$baseline_gremlins|g" \
        -e "s|{{EXPERIMENT_NUMBER}}|$experiment_num|g" \
        "$TEMPLATE" | python3 -c "
import sys
template = sys.stdin.read()
history = '''$history'''
print(template.replace('{{EXPERIMENT_HISTORY}}', history))
"
}

revert_changes() {
    cd "$PROJECT_ROOT"
    git checkout -- src/pytest_gremlins/ 2>/dev/null || true
    git clean -fd src/pytest_gremlins/ 2>/dev/null || true
}
```

- [ ] **Step 2: Add the main loop (append to the same file from Step 1)**

```bash
# --- Main --- (continues in run_autoresearch.sh after the helpers above)
main() {
    echo "=== Autoresearch: Cold Cache Optimization ==="
    echo "Model: $MODEL | Timeout: ${SESSION_TIMEOUT}s | Max hours: $MAX_HOURS"
    echo "Improvement threshold: ${IMPROVEMENT_THRESHOLD}% | Plateau limit: $MAX_PLATEAU"
    echo ""

    cd "$PROJECT_ROOT"

    # Step 1: Establish baseline
    echo "--- Establishing baseline on attrs (cold cache) ---"
    local baseline_json
    baseline_json=$("$BENCHMARK_SCRIPT" "$PROJECT_ROOT")
    echo "$baseline_json" > "$BASELINE_FILE"
    cp "$BASELINE_FILE" "$BEST_FILE"
    echo "Baseline: $baseline_json"
    echo ""

    # Step 2: Create experiment branch
    local branch="autoresearch/$(date +%Y%m%d)"
    git checkout -b "$branch" 2>/dev/null || git checkout "$branch"
    echo "Branch: $branch"

    # Step 3: Initialize log
    if [[ ! -f "$LOG_FILE" ]]; then
        echo "[]" > "$LOG_FILE"
    fi

    # Step 4: Loop
    local experiment_num=1
    local consecutive_failures=0
    local start_epoch
    start_epoch=$(now_epoch)
    local max_seconds=$((MAX_HOURS * 3600))

    local MIN_EXPERIMENTS=2

    while true; do
        # Check time limit (only after minimum experiments)
        local elapsed
        elapsed=$(python3 -c "print($(now_epoch) - $start_epoch)")
        if [[ $experiment_num -gt $MIN_EXPERIMENTS ]] && python3 -c "exit(0 if $elapsed >= $max_seconds else 1)"; then
            echo "=== Time limit reached ($MAX_HOURS hours) ==="
            break
        fi

        # Check plateau (only after minimum experiments)
        if [[ $experiment_num -gt $MIN_EXPERIMENTS && $consecutive_failures -ge $MAX_PLATEAU ]]; then
            echo "=== Plateau reached ($MAX_PLATEAU consecutive non-improvements) ==="
            break
        fi

        echo ""
        echo "=== Experiment $experiment_num ($(python3 -c "print(f'{$elapsed/3600:.1f}')") hours elapsed) ==="

        # Template the prompt
        local prompt
        prompt=$(template_prompt "$experiment_num")

        # Clean signal files from prior iteration
        rm -f "$SCRIPT_DIR/.hypothesis" "$SCRIPT_DIR/.test_failed"

        # Run Claude session with timeout (prompt via stdin for long content)
        echo "Launching Claude Code session (${SESSION_TIMEOUT}s timeout)..."
        echo "$prompt" | gtimeout "$SESSION_TIMEOUT" \
            claude -p \
            --model "$MODEL" \
            --permission-mode bypassPermissions \
            --allowedTools "Edit Read Grep Glob Bash Write" \
            --append-system-prompt "Working directory: $PROJECT_ROOT. Only edit files under \
src/pytest_gremlins/. Write your one-line hypothesis to autoresearch/.hypothesis before \
editing. If tests fail, write 'true' to autoresearch/.test_failed before reverting." \
            > /dev/null 2>&1 || true

        # Read hypothesis signal file (agent writes this before editing)
        local hypothesis="unknown"
        if [[ -f "$SCRIPT_DIR/.hypothesis" ]]; then
            hypothesis=$(head -1 "$SCRIPT_DIR/.hypothesis")
        fi

        # Check for test failure signal
        if [[ -f "$SCRIPT_DIR/.test_failed" ]]; then
            echo "Agent reported test failure. Reverting."
            revert_changes
            log_experiment "$experiment_num" "$hypothesis" "0" "0" "false" "tests_failed"
            consecutive_failures=$((consecutive_failures + 1))
            experiment_num=$((experiment_num + 1))
            if "$DRY_RUN"; then break; fi
            continue
        fi

        # Check if anything changed
        if [[ -z "$(git status --porcelain src/pytest_gremlins/ 2>/dev/null)" ]]; then
            echo "No changes made. Logging and continuing."
            log_experiment "$experiment_num" "$hypothesis" "0" "0" "false" "no_changes"
            consecutive_failures=$((consecutive_failures + 1))
            experiment_num=$((experiment_num + 1))

            if "$DRY_RUN"; then break; fi
            continue
        fi

        # Run benchmark OUTSIDE Claude session
        echo "Running benchmark (cold cache on attrs)..."
        local result_json
        result_json=$("$BENCHMARK_SCRIPT" "$PROJECT_ROOT") || {
            echo "Benchmark failed. Reverting."
            revert_changes
            log_experiment "$experiment_num" "benchmark error" "0" "0" "false" "benchmark_error"
            consecutive_failures=$((consecutive_failures + 1))
            experiment_num=$((experiment_num + 1))
            if "$DRY_RUN"; then break; fi
            continue
        }

        local wall_time gremlins_found
        wall_time=$(echo "$result_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['wall_time_seconds'])")
        gremlins_found=$(echo "$result_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['gremlins_found'])")

        local best_time baseline_gremlins
        best_time=$(json_get "$BEST_FILE" wall_time_seconds)
        baseline_gremlins=$(json_get "$BASELINE_FILE" gremlins_found)

        # Evaluate: improved enough AND gremlins maintained?
        local improvement_pct
        improvement_pct=$(python3 -c "print(round((1 - $wall_time / $best_time) * 100, 1))")

        local gremlins_ok time_ok
        gremlins_ok=$(python3 -c "print('true' if $gremlins_found >= $baseline_gremlins else 'false')")
        time_ok=$(python3 -c "print('true' if $improvement_pct >= $IMPROVEMENT_THRESHOLD else 'false')")

        echo "Result: ${wall_time}s (${improvement_pct}% vs best) | ${gremlins_found} gremlins (floor: ${baseline_gremlins})"

        if [[ "$gremlins_ok" == "true" && "$time_ok" == "true" ]]; then
            echo "ACCEPTED: ${improvement_pct}% improvement!"

            git add src/pytest_gremlins/
            git commit -m "experiment $experiment_num: $hypothesis

Cold cache wall time: ${best_time}s -> ${wall_time}s (${improvement_pct}% faster)
Gremlins found: ${gremlins_found} (floor: ${baseline_gremlins})
Autoresearch experiment from #336.

Co-Authored-By: Claude <noreply@anthropic.com>"

            # Update best
            echo "$result_json" > "$BEST_FILE"
            log_experiment "$experiment_num" "$hypothesis" "$wall_time" "$gremlins_found" "true" ""
            consecutive_failures=0
        else
            local reason=""
            if [[ "$gremlins_ok" == "false" ]]; then
                reason="gremlins_dropped (${gremlins_found} < ${baseline_gremlins})"
            else
                reason="insufficient_improvement (${improvement_pct}% < ${IMPROVEMENT_THRESHOLD}%)"
            fi
            echo "REJECTED: $reason"
            revert_changes
            log_experiment "$experiment_num" "$hypothesis" "$wall_time" "$gremlins_found" "false" "$reason"
            consecutive_failures=$((consecutive_failures + 1))
        fi

        experiment_num=$((experiment_num + 1))
        if "$DRY_RUN"; then break; fi
    done

    # Summary
    echo ""
    echo "=== Autoresearch Summary ==="
    local total_experiments=$((experiment_num - 1))
    local accepted
    accepted=$(python3 -c "import json; log=json.load(open('$LOG_FILE')); print(sum(1 for e in log if e['accepted']))")
    local final_best
    final_best=$(json_get "$BEST_FILE" wall_time_seconds)
    local baseline_time
    baseline_time=$(json_get "$BASELINE_FILE" wall_time_seconds)
    local total_improvement
    total_improvement=$(python3 -c "print(round((1 - $final_best / $baseline_time) * 100, 1))")

    echo "Total experiments: $total_experiments"
    echo "Accepted: $accepted"
    echo "Baseline: ${baseline_time}s"
    echo "Best: ${final_best}s"
    echo "Total improvement: ${total_improvement}%"
    echo "Branch: $(git branch --show-current)"
    echo ""
    echo "Review the branch with: git log --oneline $branch"
}

main "$@"
```

- [ ] **Step 3: Make executable and verify syntax**

```bash
chmod +x autoresearch/run_autoresearch.sh
bash -n autoresearch/run_autoresearch.sh  # syntax check only
```

- [ ] **Step 4: Commit**

```bash
git add autoresearch/run_autoresearch.sh
git commit -m "feat(autoresearch): add run_autoresearch.sh outer loop

Shell loop that orchestrates Claude Code sessions, benchmarks, and
commits/reverts. Uses gtimeout (coreutils) for session enforcement.
Configurable via CLI flags and env vars.
Part of #336.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Dry Run — End-to-End Verification

Run a single experiment cycle to verify the whole pipeline works.

**Files:**

- No new files — testing existing scripts

- [ ] **Step 1: Run dry-run mode**

```bash
cd /Users/mikelane/dev/pytest-gremlins/.worktrees/issue-336-autoresearch
./autoresearch/run_autoresearch.sh --dry-run --model sonnet
```

Expect:

1. Baseline measurement runs and produces JSON
2. Experiment branch is created
3. One Claude session launches, makes (or doesn't make) changes
4. Benchmark runs on the result
5. Result is committed or reverted
6. Summary prints

- [ ] **Step 2: Inspect the experiment log**

```bash
cat autoresearch/experiment_log.json | python3 -m json.tool
```

Verify the schema matches what issue #336 specifies:

- `experiment_number`, `timestamp`, `hypothesis`, `wall_time_seconds`, `gremlins_found`, `accepted`, `reason`, `files_changed`

- [ ] **Step 3: Fix any issues found during dry run**

Common problems:

- `claude -p` permission issues — may need `--permission-mode bypassPermissions`
- Benchmark script path resolution when run from different directories
- JSON parsing errors in the log function (quote escaping in hypothesis strings)
- `uv` not available inside Claude's shell context

- [ ] **Step 4: Run dry-run again to confirm fixes**

```bash
./autoresearch/run_autoresearch.sh --dry-run --model sonnet
```

Should complete cleanly with proper log output.

- [ ] **Step 5: Commit any fixes**

```bash
git add autoresearch/
git commit -m "fix(autoresearch): fixes from dry-run verification

Part of #336.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Documentation and Gitignore

Add a README for the autoresearch directory and ensure generated files are properly ignored.

**Files:**

- Create: `autoresearch/README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Create autoresearch README**

````markdown
# Autoresearch: Cold Cache Optimization

Autonomous optimization loop for pytest-gremlins cold cache runtime,
inspired by [Andrej Karpathy's Autoresearch](https://github.com/karpathy/autoresearch).

## Quick Start

```bash
# Single experiment (verification)
./autoresearch/run_autoresearch.sh --dry-run

# Overnight run
./autoresearch/run_autoresearch.sh --max-hours 8 --model sonnet

# Review results
git log --oneline autoresearch/$(date +%Y%m%d)
cat autoresearch/experiment_log.json | python3 -m json.tool
```

## How It Works

1. **Baseline**: Measures cold cache wall time + gremlin count on attrs
2. **Loop**: Launches 15-min Claude Code sessions, each proposing one optimization
3. **Evaluate**: Runs benchmark OUTSIDE Claude (prevents metric gaming)
4. **Keep/Revert**: Commits improvements, reverts regressions
5. **Stop**: After max hours or plateau (10 consecutive non-improvements)

## Files

| File | Role | Mutable? |
|------|------|----------|
| `program.md.template` | Agent instructions | No (during run) |
| `prepare_benchmark.sh` | Evaluation harness | No |
| `run_autoresearch.sh` | Outer loop | No |
| `baseline_metrics.json` | Starting metrics | Written once |
| `best_metrics.json` | Current best | Updated on improvement |
| `experiment_log.json` | Full history | Append-only |

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--max-hours` | 8 | Maximum run duration |
| `--max-plateau` | 10 | Stop after N consecutive failures |
| `--timeout` | 900 | Seconds per Claude session |
| `--threshold` | 2 | Minimum improvement % to accept |
| `--model` | sonnet | Claude model to use |
| `--dry-run` | false | Run one cycle and exit |
````

- [ ] **Step 2: Add generated files to .gitignore**

Append to `.gitignore`:

```text
# Autoresearch generated files
autoresearch/baseline_metrics.json
autoresearch/best_metrics.json
autoresearch/experiment_log.json
autoresearch/.hypothesis
autoresearch/.test_failed
```

- [ ] **Step 3: Commit**

```bash
git add autoresearch/README.md .gitignore
git commit -m "docs(autoresearch): add README and gitignore generated files

Part of #336.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Push Branch

- [ ] **Step 1: Push the branch**

```bash
git push -u origin issue-336-autoresearch
```

- [ ] **Step 2: Verify all commits are present**

```bash
git log --oneline main..issue-336-autoresearch
```

Expect 4-5 commits covering: prepare_benchmark.sh, program.md.template, run_autoresearch.sh, dry-run fixes, docs.
