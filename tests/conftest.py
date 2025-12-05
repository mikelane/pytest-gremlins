"""Shared pytest configuration and fixtures for pytest-gremlins tests."""

from __future__ import annotations

from pathlib import Path

import pytest


# Register markers for test categories
def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for test categorization."""
    config.addinivalue_line('markers', 'small: Fast, isolated unit tests (< 100ms)')
    config.addinivalue_line('markers', 'medium: Integration tests with real resources (< 10s)')
    config.addinivalue_line('markers', 'large: End-to-end system tests (< 60s)')


# Auto-mark tests based on directory
def pytest_collection_modifyitems(
    config: pytest.Config,  # noqa: ARG001
    items: list[pytest.Item],
) -> None:
    """Automatically apply markers based on test directory."""
    for item in items:
        # Get the path parts from the item's path
        item_path = Path(str(item.fspath))
        path_parts = item_path.parts

        if 'small' in path_parts:
            item.add_marker(pytest.mark.small)
        elif 'medium' in path_parts:
            item.add_marker(pytest.mark.medium)
        elif 'large' in path_parts:
            item.add_marker(pytest.mark.large)
