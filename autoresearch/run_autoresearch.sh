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
    files_changed=$(git diff --name-only HEAD 2>/dev/null | python3 -c "import json,sys; print(json.dumps(sys.stdin.read().strip().split('\n')))" 2>/dev/null || echo '[]')

    python3 -c "
import json, sys
entry = {
    'experiment_number': $num,
    'timestamp': '$(now_iso)',
    'hypothesis': '''$hypothesis''',
    'wall_time_seconds': $wall_time,
    'gremlins_found': $gremlins,
    'accepted': '$accepted' == 'true',
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
    # Use HEAD explicitly: `git checkout --` restores from INDEX, which fails
    # if the agent ran `git add` (index has agent's changes, not HEAD's).
    # `git checkout HEAD --` resets both index AND working tree to last commit.
    git checkout HEAD -- src/pytest_gremlins/ 2>/dev/null || true
    git clean -fd src/pytest_gremlins/ 2>/dev/null || true
}

# --- Main ---
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
            --append-system-prompt "Working directory: $PROJECT_ROOT. Only edit files under src/pytest_gremlins/. Write your one-line hypothesis to autoresearch/.hypothesis before editing. If tests fail, write 'true' to autoresearch/.test_failed before reverting." \
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
