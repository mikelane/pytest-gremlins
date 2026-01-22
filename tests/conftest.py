"""Shared pytest configuration and fixtures for pytest-gremlins tests.

Note: Marker application is handled by the root conftest.py.
This file is for test-specific fixtures only.
"""

from __future__ import annotations

import pytest  # noqa: TC002 - used at runtime for pytest_configure hook


# Enable pytester fixture for plugin testing
pytest_plugins = ['pytester']


# Register markers for test categories
def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for test categorization."""
    config.addinivalue_line('markers', 'small: Fast, isolated unit tests (< 100ms)')
    config.addinivalue_line('markers', 'medium: Integration tests with real resources (< 10s)')
    config.addinivalue_line('markers', 'large: End-to-end system tests (< 60s)')
