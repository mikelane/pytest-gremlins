"""Full compatibility test: pytest-gremlins against all of attrs.

Release gate -- runs all gremlins against attrs with parallel workers.
Asserts error rate < 10% and at least some gremlins are zapped/survived.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest

MAX_ERROR_RATE_PERCENT = 10.0


@pytest.mark.large
class DescribeAttrsFullCompatibility:
    """Full gremlins run against all attrs source."""

    def it_has_acceptable_error_rate(self, attrs_venv: Path, attrs_checkout: Path) -> None:
        python = str(attrs_venv / 'bin' / 'python')

        result = subprocess.run(
            [
                python,
                '-m',
                'pytest',
                '--gremlins',
                '--gremlin-targets',
                'src/attr',
                '--gremlin-workers=auto',
                '-q',
                '--no-header',
                '--tb=short',
            ],
            cwd=str(attrs_checkout),
            capture_output=True,
            text=True,
            timeout=1200,  # suffix-match fallback (#359) adds overhead; optimize later
            check=False,
        )

        output = result.stdout + result.stderr

        # Parse counts
        total_match = re.search(r'(\d+)\s+gremlins', output)
        error_match = re.search(r'Error:\s+(\d+)\s+gremlins', output)
        zapped_match = re.search(r'Zapped:\s+(\d+)\s+gremlins', output)
        survived_match = re.search(r'Survived:\s+(\d+)\s+gremlins', output)

        total = int(total_match.group(1)) if total_match else 0
        error_count = int(error_match.group(1)) if error_match else 0
        zapped_count = int(zapped_match.group(1)) if zapped_match else 0
        survived_count = int(survived_match.group(1)) if survived_match else 0

        # Assertions
        assert total > 0, f'No gremlins found at all. Output:\n{output}'
        assert zapped_count + survived_count > 0, f'No gremlins zapped or survived. Output:\n{output}'

        if total > 0:
            error_rate = (error_count / total) * 100
            assert error_rate < MAX_ERROR_RATE_PERCENT, (
                f'Error rate {error_rate:.1f}% exceeds {MAX_ERROR_RATE_PERCENT}%. '
                f'Errors: {error_count}/{total}. Output:\n{output}'
            )
