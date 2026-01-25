"""Root pytest configuration for pytest-gremlins.

This conftest.py handles marker application for ALL tests including doctests.
The tests/conftest.py handles test-specific fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _has_size_marker(item: pytest.Item) -> bool:
    """Check if an item already has a size marker."""
    return any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers())


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config,  # noqa: ARG001
    items: list[pytest.Item],
) -> None:
    """Automatically apply size markers based on test location.

    This hook runs before pytest-test-categories checks for markers.
    Tests that already have a size marker are not modified.
    """
    for item in items:
        # Skip if test already has an explicit size marker
        if _has_size_marker(item):
            continue

        # Get the path parts from the item's path
        item_path = Path(str(item.fspath))
        path_parts = item_path.parts

        if 'small' in path_parts:
            item.add_marker(pytest.mark.small)
        elif 'medium' in path_parts:
            item.add_marker(pytest.mark.medium)
        elif 'large' in path_parts:
            item.add_marker(pytest.mark.large)
        elif 'src' in path_parts:
            # Doctests from source code default to small
            item.add_marker(pytest.mark.small)
