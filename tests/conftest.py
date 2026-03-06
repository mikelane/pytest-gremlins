"""Shared pytest configuration and fixtures for pytest-gremlins tests.

Note: Marker application is handled by the root conftest.py.
This file is for test-specific fixtures only.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from pytest_gremlins.plugin import _set_session

# Enable pytester fixture for plugin testing
pytest_plugins = ['pytester']


# Register markers for test categories
def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for test categorization."""
    config.addinivalue_line('markers', 'small: Fast, isolated unit tests (< 100ms)')
    config.addinivalue_line('markers', 'medium: Integration tests with real resources (< 10s)')
    config.addinivalue_line('markers', 'large: End-to-end system tests (< 60s)')


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Sort small tests before medium tests to preserve coverage tracing.

    In-process pytester (used by medium tests) resets sys.settrace when the
    inner session ends, stopping coverage.py from tracking subsequent tests.
    Running all small tests first ensures their coverage is captured before
    any in-process pytester session can clear the trace function.

    This restores the execution order that existed when tests lived in
    separate tests/small/ and tests/medium/ directories.
    """

    def _size_priority(item: pytest.Item) -> int:
        markers = {m.name for m in item.iter_markers()}
        if 'large' in markers:
            return 4
        if 'medium' in markers:
            # Pytester-based medium tests reset sys.settrace when their inner
            # pytest session ends, killing coverage for subsequent tests.
            # Run non-pytester medium tests first so they get coverage tracked.
            uses_pytester = bool({'pytester', 'pytester_with_markers'} & set(getattr(item, 'fixturenames', [])))
            return 3 if uses_pytester else 2
        return 1  # small or unmarked runs first

    items.sort(key=_size_priority)


@pytest.fixture(autouse=True)
def reset_gremlin_session() -> Generator[None, None, None]:
    """Reset the global gremlin session after each test to prevent state leakage.

    Tests that call _set_session() with enabled=True must not bleed state into
    the outer pytest process's pytest_sessionfinish hook.
    """
    yield
    _set_session(None)


@pytest.fixture
def pytester_with_markers(pytester: pytest.Pytester) -> pytest.Pytester:
    """Create a pytester instance that auto-applies small marker to tests.

    The pytest-test-categories plugin requires tests to have size markers.
    Tests created via pytester.makepyfile() don't have markers by default,
    which causes INTERNALERROR on Python 3.14 due to stricter warning handling.

    This fixture creates a conftest.py that registers the small marker and
    auto-applies it to any test that doesn't already have a size marker.
    """
    pytester.makeconftest(
        """
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers', 'small: marks tests as small (fast unit tests)')

@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if not any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers()):
            item.add_marker(pytest.mark.small)
""",
    )
    return pytester
