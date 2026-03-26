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
