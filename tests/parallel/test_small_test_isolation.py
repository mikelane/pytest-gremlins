"""Small tests must not leave pytest-test-categories' subprocess guard installed for later tests (#975).

pytest-test-categories wraps ``subprocess.run`` for each small test and restores the original afterwards. A small test
that monkeypatches the global ``subprocess.run`` makes monkeypatch record that wrapper as the value to restore, so the
guard outlives the test and every later medium test that spawns a process fails with a TC003 violation.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
VICTIM = (
    'tests/parallel/test_lightweight_runner_script.py::DescribeLightweightRunnerExitCodes::'
    'it_exits_zero_when_the_test_passes'
)
PORTABLE = 'tests/parallel/test_process_tree_portable.py'


@pytest.mark.medium
class DescribeSmallTestSubprocessGuard:
    def it_leaves_a_later_medium_test_free_to_spawn_a_process(self) -> None:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', PORTABLE, VICTIM, '-q', '-p', 'no:cacheprovider'],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        assert result.returncode == 0, result.stdout[-2000:]
