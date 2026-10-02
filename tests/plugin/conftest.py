"""Shared fixtures for the plugin tests."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

SUBPROCESS_TIMEOUT_SECONDS = 300

RunPytestIsolated = Callable[..., pytest.RunResult]


def _run_pytest_isolated(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    """Run pytest in the project directory with neither the cwd nor ``PYTHONPATH`` on ``sys.path``.

    Plain ``python -m pytest`` puts the cwd on ``sys.path`` and ``Pytester.run`` exports the
    cwd as ``PYTHONPATH``; either makes a root-level module importable and hides import
    errors under test. ``-P`` (Python 3.11+) drops the cwd entry, and invoking the current
    interpreter avoids locating a platform-specific ``pytest`` console script.

    Output is decoded as UTF-8 with replacement and the child is told to write UTF-8, so
    non-ASCII characters in pytest's summary (such as the test-categories bullets) cannot
    raise ``UnicodeDecodeError`` on platforms whose locale encoding is not UTF-8.
    """
    environment = {name: value for name, value in os.environ.items() if name != 'PYTHONPATH'}
    environment['PYTHONIOENCODING'] = 'utf-8'
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, '-P', '-m', 'pytest', '-p', 'no:cacheprovider', *args],
        cwd=Path(pytester.path),
        env=environment,
        capture_output=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    return pytest.RunResult(
        completed.returncode,
        completed.stdout.splitlines(),
        completed.stderr.splitlines(),
        time.perf_counter() - started,
    )


@pytest.fixture
def run_pytest_isolated() -> RunPytestIsolated:
    """Return a runner executing pytest in a pytester project with an import-isolated child."""
    return _run_pytest_isolated
