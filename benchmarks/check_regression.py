#!/usr/bin/env python
"""Check for performance regressions in benchmark results.

This script compares current benchmark results against a baseline and
exits non-zero if any configuration regressed beyond the threshold.

Usage:
    python benchmarks/check_regression.py \\
        --baseline benchmarks/baseline.json \\
        --current benchmarks/results/benchmark_YYYYMMDD.json \\
        --threshold 10

Exit Codes:
    0: No regressions detected (or improvements)
    1: Performance regressions detected
    2: Invalid input (missing files, bad JSON)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys


@dataclass
class RegressionDetail:
    """Details about a single regression or improvement.

    Attributes:
        config: Configuration name (e.g., 'gremlins_sequential').
        baseline_time: Time from baseline in seconds.
        current_time: Time from current run in seconds.
        change_percent: Percentage change (positive = regression, negative = improvement).
    """

    config: str
    baseline_time: float
    current_time: float
    change_percent: float

    def __str__(self) -> str:
        """Format for human-readable output."""
        sign = '+' if self.change_percent >= 0 else ''
        return (
            f'{self.config}: {self.baseline_time:.2f}s -> {self.current_time:.2f}s ({sign}{self.change_percent:.1f}%)'
        )


@dataclass
class RegressionCheckResult:
    """Result of comparing benchmark results against baseline.

    Attributes:
        has_regressions: True if any config regressed beyond threshold.
        regressions: List of configs that regressed.
        improvements: List of configs that improved significantly.
        threshold_percent: The threshold used for regression detection.
    """

    has_regressions: bool
    regressions: list[RegressionDetail]
    improvements: list[RegressionDetail]
    threshold_percent: float


def load_benchmark_results(path: Path) -> dict[str, float]:
    """Load benchmark results from a JSON file.

    Supports two formats:
    1. Simple format: {"config_name": time_seconds, ...}
    2. Full format: {"summaries": [{"tool": "...", "config": "...", "mean_time": ...}, ...]}

    Args:
        path: Path to the JSON file.

    Returns:
        Dictionary mapping config names to times in seconds.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the JSON is invalid or malformed.
    """
    if not path.exists():
        raise FileNotFoundError(f'Benchmark file not found: {path}')

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f'Invalid JSON in {path}: {e}') from e

    # Check for full benchmark format with summaries
    if isinstance(data, dict) and 'summaries' in data:
        results = {}
        for summary in data['summaries']:
            tool = summary.get('tool', 'unknown')
            config = summary.get('config', 'unknown')
            mean_time = summary.get('mean_time', 0.0)
            # Create key like "gremlins_sequential" or "mutmut_default"
            key = f'{tool}_{config}'
            results[key] = mean_time
        return results

    # Simple format: direct key-value pairs
    if isinstance(data, dict):
        return {k: float(v) for k, v in data.items()}

    raise ValueError(f'Unexpected format in {path}')


def check_regression(
    baseline: dict[str, float],
    current: dict[str, float],
    threshold_percent: float = 10.0,
) -> RegressionCheckResult:
    """Compare current results against baseline for regressions.

    A regression is detected when current time exceeds baseline by more than
    the threshold percentage. Improvements (negative change) are also tracked
    but don't trigger failure.

    Args:
        baseline: Baseline times by config name.
        current: Current times by config name.
        threshold_percent: Percentage threshold for regression (default 10%).

    Returns:
        RegressionCheckResult with details about any regressions/improvements.
    """
    regressions = []
    improvements = []

    for config, baseline_time in baseline.items():
        if config not in current:
            continue

        current_time = current[config]
        if baseline_time == 0:
            continue

        change_percent = (current_time - baseline_time) / baseline_time * 100

        detail = RegressionDetail(
            config=config,
            baseline_time=baseline_time,
            current_time=current_time,
            change_percent=change_percent,
        )

        # Check for significant regression (> threshold)
        if change_percent > threshold_percent:
            regressions.append(detail)
        # Check for significant improvement (< -threshold)
        elif change_percent < -threshold_percent:
            improvements.append(detail)

    return RegressionCheckResult(
        has_regressions=len(regressions) > 0,
        regressions=regressions,
        improvements=improvements,
        threshold_percent=threshold_percent,
    )


def format_report(result: RegressionCheckResult) -> str:
    """Format the regression check result as a human-readable report.

    Args:
        result: The regression check result.

    Returns:
        Formatted string report.
    """
    lines = []

    if result.has_regressions:
        lines.append(f'Performance regressions detected (threshold: {result.threshold_percent}%):')
        lines.append('')
        lines.extend(f'  {regression}' for regression in result.regressions)
    else:
        lines.append(f'No regressions detected (threshold: {result.threshold_percent}%)')

    if result.improvements:
        lines.append('')
        lines.append('Performance improvements:')
        lines.extend(f'  {improvement}' for improvement in result.improvements)

    return '\n'.join(lines)


def main() -> int:
    """Run regression check from command line.

    Returns:
        Exit code (0 = success, 1 = regressions, 2 = error).
    """
    parser = argparse.ArgumentParser(
        description='Check for performance regressions in benchmark results.',
    )
    parser.add_argument(
        '--baseline',
        type=Path,
        required=True,
        help='Path to baseline benchmark results JSON',
    )
    parser.add_argument(
        '--current',
        type=Path,
        required=True,
        help='Path to current benchmark results JSON',
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=10.0,
        help='Regression threshold percentage (default: 10)',
    )

    args = parser.parse_args()

    try:
        baseline = load_benchmark_results(args.baseline)
        current = load_benchmark_results(args.current)
    except (FileNotFoundError, ValueError) as e:
        print(f'Error: {e}', file=sys.stderr)
        return 2

    result = check_regression(baseline, current, args.threshold)
    print(format_report(result))

    return 1 if result.has_regressions else 0


if __name__ == '__main__':
    sys.exit(main())
