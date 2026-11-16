"""Smoke test: pytest-gremlins against attrs (small target).

Verifies gremlins can instrument and test a real-world library without
errors. Targets a single small file for fast execution (<60s).
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest

# Hang guard in seconds: the subprocess is killed past this, far above a normal run.
HANG_GUARD_SECONDS = 180


@pytest.mark.medium
class DescribeAttrsSmokeTest:
    """Smoke test running gremlins against attrs/_config.py."""

    def it_finds_gremlins_with_zero_errors(self, attrs_venv: Path, attrs_checkout: Path) -> None:
        python = str(attrs_venv / 'bin' / 'python')
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
            timeout=HANG_GUARD_SECONDS,  # a hang guard, not a speed assertion
            check=False,
        )

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
