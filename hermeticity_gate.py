"""Fail tests that pytest-test-categories flagged for a hermeticity violation.

Under ``test_categories_enforcement = "strict"`` the plugin records a violation and only fails the
test when the violation's exception reaches pytest. When the code under test swallows that
exception the test passes, the summary prints ``1 test failed due to violations`` and pytest
exits 0 (#474). This plugin turns such a pass into a failure, so CI goes red.

Remove this stopgap once https://github.com/mikelane/pytest-test-categories/issues/267 is fixed upstream.

The check runs in each test's own report, so it also works on pytest-xdist workers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

try:
    from pytest_test_categories.violation_tracking import (
        ViolationTracker,
        ViolationType,
    )
except ImportError:  # older pytest-test-categories releases (CI compat jobs) lack the tracker
    ViolationTracker = ViolationType = None  # type: ignore[assignment,misc]


if TYPE_CHECKING:
    from collections.abc import Generator


def _enforcement_is_strict(config: pytest.Config) -> bool:
    cli_value = config.getoption('--test-categories-enforcement', default=None)
    return (cli_value or config.getini('test_categories_enforcement')) == 'strict'


def _violating_nodeids(config: pytest.Config) -> set[str]:
    if ViolationTracker is None or ViolationType is None:
        return set()
    state = getattr(config, '_test_categories_state', None)
    tracker = getattr(state, 'violation_tracker', None)
    if not isinstance(tracker, ViolationTracker) or not _enforcement_is_strict(config):
        return set()
    return {nodeid for kind in ViolationType for nodeid in tracker.get_test_nodeids_by_type(kind)}


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Turn a passing or skipped call phase into a failure when its test was flagged for a violation."""
    report = yield
    if call.when == 'call' and not report.failed and item.nodeid in _violating_nodeids(item.config):
        report.outcome = 'failed'
        if hasattr(report, 'wasxfail'):
            del report.wasxfail  # pytest does not count a report carrying wasxfail toward the exit status
        report.longrepr = 'Hermeticity violation recorded by pytest-test-categories (enforcement: strict).'
    return report
