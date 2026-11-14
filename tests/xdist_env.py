"""The scrub of the outer xdist worker identity, in one importable place for the tests that prove it works."""

from __future__ import annotations

import pytest

XDIST_WORKER_ENV_NAMES = ('PYTEST_XDIST_WORKER', 'PYTEST_XDIST_WORKER_COUNT', 'PYTEST_XDIST_TESTRUNUID')


@pytest.fixture(autouse=True)
def hide_outer_xdist_worker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the outer xdist worker's identity out of the test and of every child it starts.

    pytest-test-categories decides "this process is an xdist worker" from ``PYTEST_XDIST_WORKER`` alone, so a
    pytester or subprocess run started inside an outer ``-n`` worker would take the worker path. Scrubbing per test
    leaves the outer worker's own session hooks, which run between tests, untouched.
    """
    for name in XDIST_WORKER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
