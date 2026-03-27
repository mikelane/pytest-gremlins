"""Smoke test: pytest-gremlins against attrs (small target).

Verifies gremlins can instrument and test a real-world library without
errors. Targets a single small file for fast execution (<60s).
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import time

import pytest

# Performance baseline in seconds. Fail if >3x this value.
# Set conservatively high initially; tighten after observing CI runs.
PERF_BASELINE_SECONDS = 60.0
PERF_THRESHOLD_MULTIPLIER = 3.0


@pytest.mark.medium
class DescribeAttrsSmokeTest:
    """Smoke test running gremlins against attrs/_config.py."""

    def it_finds_gremlins_with_zero_errors(self, attrs_venv: Path, attrs_checkout: Path) -> None:
        python = str(attrs_venv / 'bin' / 'python')
        start = time.monotonic()

        result = subprocess.run(
            [
                python,
                '-m',
                'pytest',
                '--gremlins',
                '--gremlin-targets',
                'src/attr/_config.py',
                '--gremlin-workers=1',
                '-q',
                '--no-header',
                '--tb=short',
            ],
            cwd=str(attrs_checkout),
            capture_output=True,
            text=True,
            timeout=int(PERF_BASELINE_SECONDS * PERF_THRESHOLD_MULTIPLIER),
            check=False,
        )

        elapsed = time.monotonic() - start
        output = result.stdout + result.stderr

        # Parse gremlin results from output
        error_match = re.search(r'Error:\s+(\d+)\s+gremlins', output)
        zapped_match = re.search(r'Zapped:\s+(\d+)\s+gremlins', output)
        survived_match = re.search(r'Survived:\s+(\d+)\s+gremlins', output)

        error_count = int(error_match.group(1)) if error_match else 0
        zapped_count = int(zapped_match.group(1)) if zapped_match else 0
        survived_count = int(survived_match.group(1)) if survived_match else 0

        # Assertions
        assert error_count == 0, f'Expected 0 errors, got {error_count}. Output:\n{output}'
        assert zapped_count + survived_count > 0, f'No gremlins found. Output:\n{output}'

        # Performance gate
        assert elapsed < PERF_BASELINE_SECONDS * PERF_THRESHOLD_MULTIPLIER, (
            f'Smoke test took {elapsed:.1f}s, exceeding {PERF_THRESHOLD_MULTIPLIER}x '
            f'baseline of {PERF_BASELINE_SECONDS}s'
        )
