"""pytest plugin for gremlin mutation testing.

This module provides the pytest plugin hooks that integrate mutation testing
into the pytest test runner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add command-line options for pytest-gremlins."""
    group = parser.getgroup('gremlins', 'mutation testing with gremlins')
    group.addoption(
        '--gremlins',
        action='store_true',
        default=False,
        dest='gremlins',
        help='Enable mutation testing (feed the gremlins after midnight)',
    )
    group.addoption(
        '--gremlin-operators',
        action='store',
        default=None,
        dest='gremlin_operators',
        help='Comma-separated list of mutation operators to use',
    )
    group.addoption(
        '--gremlin-report',
        action='store',
        default='console',
        dest='gremlin_report',
        help='Report format: console, html, json (default: console)',
    )


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-gremlins based on command-line options."""
    if config.option.gremlins:
        # TODO: Initialize mutation testing infrastructure
        pass
