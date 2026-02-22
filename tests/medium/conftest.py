"""Shared fixtures for medium integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture()
def pytester_with_conftest(pytester: pytest.Pytester) -> pytest.Pytester:
    """Create a pytester instance with conftest that registers small marker for nested tests."""
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
