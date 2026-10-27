"""The ``[[tool.mypy.overrides]]`` block for ``tests.*`` must match real module names (issue #478).

Without ``explicit_package_bases``, mypy names test modules after their subpackage (``plugin.test_x``), so the
override never matched and mypy reported ``unused section(s): module = ['tests.*']``.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.medium
class DescribeMypyTestsOverride:
    def it_is_applied_to_test_modules_instead_of_reported_unused(self) -> None:
        result = subprocess.run(
            [sys.executable, '-m', 'mypy', '--no-incremental', 'tests/config/test_ruff_floor.py'],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert 'unused section' not in result.stdout + result.stderr
