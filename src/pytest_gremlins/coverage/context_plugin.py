"""GremlinContextPlugin - per-test coverage context switching.

Attaches to a ``coverage.Coverage`` instance and switches the active dynamic
context before each test phase so that coverage data is tagged with the test
that exercised each line.

Context format: ``{nodeid}|{when}``

Example:
    >>> from unittest.mock import MagicMock
    >>> cov = MagicMock()
    >>> plugin = GremlinContextPlugin(cov)
    >>> plugin.cov is cov
    True
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import coverage as coverage_module


class GremlinContextPlugin:
    """Switches coverage dynamic context for each test phase.

    Registers hookwrappers for setup, call, and teardown so that every line
    executed during a test is attributed to ``{nodeid}|{when}``.

    Attributes:
        cov: The ``coverage.Coverage`` instance to switch contexts on.
    """

    def __init__(self, cov: coverage_module.Coverage) -> None:
        """Create a context plugin bound to the given coverage instance.

        Args:
            cov: The coverage instance whose dynamic context will be switched.
        """
        self.cov = cov

    def _safe_switch(self, context: str) -> None:
        """Switch coverage context only if coverage is still running.

        Guards against ``CoverageException`` when called after
        ``Coverage.stop()`` -- e.g. during mutation-testing phase 2.

        Args:
            context: The context string to switch to.
        """
        if getattr(self.cov, '_started', False):
            self.cov.switch_context(context)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> Generator[None, None, None]:
        """Switch coverage context to ``{nodeid}|setup`` before test setup.

        Args:
            item: The test item being set up.

        Yields:
            Control to the next hook implementation.
        """
        self._safe_switch(f'{item.nodeid}|setup')
        yield

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item: pytest.Item) -> Generator[None, None, None]:
        """Switch coverage context to ``{nodeid}|run`` before the test call.

        Args:
            item: The test item being called.

        Yields:
            Control to the next hook implementation.
        """
        self._safe_switch(f'{item.nodeid}|run')
        yield

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_teardown(self, item: pytest.Item) -> Generator[None, None, None]:
        """Switch coverage context to ``{nodeid}|teardown`` before teardown.

        Args:
            item: The test item being torn down.

        Yields:
            Control to the next hook implementation.
        """
        self._safe_switch(f'{item.nodeid}|teardown')
        yield
