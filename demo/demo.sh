#!/usr/bin/env bash
# epic-a-demo.sh — asciinema demo script for Epic A: Report Location & Output Structure
#
# Shows:
#   1. A clean project directory
#   2. Running pytest (normal, no mutation testing)
#   3. Running pytest --gremlins --gremlin-report=html (default output path)
#   4. Confirming coverage/gremlins/index.html exists
#   5. Running again with --gremlins-html-dir=reports/mutations (custom path)
#   6. Confirming reports/mutations/index.html exists
#
# Driven by asciinema rec --command="bash demo/demo.sh" docs/demo/epic-a-output-location.cast

set -euo pipefail

PYTEST=/Users/mikelane/dev/pytest-gremlins/.worktrees/issue-158-demo-epic-a/.venv/bin/pytest
PROJECT=/tmp/gremlin-demo-epica

# ── helpers ──────────────────────────────────────────────────────────────────

# Print a prompt line and then the command, then run it
run_cmd() {
    echo -e "\033[1;32m\$\033[0m \033[1m$*\033[0m"
    sleep 0.5
    eval "$@"
}

# Print a section header
header() {
    echo ""
    echo -e "\033[1;36m══════════════════════════════════════════════════════════\033[0m"
    echo -e "\033[1;36m  $1\033[0m"
    echo -e "\033[1;36m══════════════════════════════════════════════════════════\033[0m"
    echo ""
    sleep 0.8
}

# ── 0. Title ─────────────────────────────────────────────────────────────────

clear
echo ""
echo -e "\033[1;35m  pytest-gremlins\033[0m"
echo -e "\033[0;35m  Mutation testing fast enough for every commit\033[0m"
echo ""
echo -e "\033[1m  Epic A Demo: Report Location & Output Structure\033[0m"
echo -e "\033[2m  Proving: HTML report lands where you expect it\033[0m"
echo ""
sleep 2

# ── 1. Show the sample project ────────────────────────────────────────────────

header "The sample project"

run_cmd "cd $PROJECT"
sleep 0.3
run_cmd "ls -1"
echo ""
sleep 0.5
run_cmd "cat calculator.py"
sleep 1.5

# ── 2. Normal pytest run (baseline) ──────────────────────────────────────────

header "Step 1: Normal pytest — tests pass, no HTML report"

run_cmd "$PYTEST tests/ -q 2>&1 | tail -5"
sleep 1

echo ""
echo -e "\033[2m  (no coverage/gremlins/ directory yet)\033[0m"
run_cmd "ls coverage/ 2>/dev/null || echo 'coverage/  →  does not exist yet'"
sleep 1.5

# ── 3. Mutation run — default output path ────────────────────────────────────

header "Step 2: pytest --gremlins  →  default report path"

echo -e "\033[2m  Default: coverage/gremlins/index.html\033[0m"
echo ""
sleep 0.8

run_cmd "$PYTEST --gremlins --gremlin-report=html tests/ 2>&1"
sleep 1

# ── 4. Confirm default path ───────────────────────────────────────────────────

header "Step 3: Confirm the report landed at the default path"

run_cmd "ls -lh coverage/gremlins/"
sleep 0.8
echo ""
echo -e "\033[1;32m  coverage/gremlins/index.html  ✓\033[0m"
sleep 2

# ── 5. Mutation run — custom output path ──────────────────────────────────────

header "Step 4: --gremlins-html-dir  →  custom report path"

echo -e "\033[2m  Custom: reports/mutations/index.html\033[0m"
echo ""
sleep 0.8

run_cmd "$PYTEST --gremlins --gremlin-report=html --gremlins-html-dir=reports/mutations tests/ 2>&1"
sleep 1

# ── 6. Confirm custom path ────────────────────────────────────────────────────

header "Step 5: Confirm the report landed at the custom path"

run_cmd "ls -lh reports/mutations/"
sleep 0.8
echo ""
echo -e "\033[1;32m  reports/mutations/index.html  ✓\033[0m"
sleep 2

# ── 7. Closing ────────────────────────────────────────────────────────────────

echo ""
echo -e "\033[1;35m══════════════════════════════════════════════════════════\033[0m"
echo -e "\033[1;35m  Epic A  ✓  Report location and output structure proven\033[0m"
echo -e "\033[1;35m══════════════════════════════════════════════════════════\033[0m"
echo ""
echo -e "  \033[1mDefault:\033[0m  coverage/gremlins/index.html"
echo -e "  \033[1mCustom:\033[0m   --gremlins-html-dir=<path>/index.html"
echo ""
echo -e "\033[2m  pytest-gremlins — mutation testing fast enough to run on every commit\033[0m"
echo ""
sleep 4
