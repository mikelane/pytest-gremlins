"""Shared pytest configuration and fixtures for pytest-gremlins tests.

Note: Marker application is handled by the root conftest.py.
This file is for test-specific fixtures only.
"""

from __future__ import annotations

import pytest


# Enable pytester fixture for plugin testing
pytest_plugins = ['pytester']


# Register markers for test categories
def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for test categorization."""
    config.addinivalue_line('markers', 'small: Fast, isolated unit tests (< 100ms)')
    config.addinivalue_line('markers', 'medium: Integration tests with real resources (< 10s)')
    config.addinivalue_line('markers', 'large: End-to-end system tests (< 60s)')


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
"""
    )
    return pytester
