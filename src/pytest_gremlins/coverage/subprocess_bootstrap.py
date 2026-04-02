"""Self-bootstrapping coverage context plugin for subprocess collection.

When loaded via ``-p pytest_gremlins.coverage.subprocess_bootstrap`` inside a
``coverage run -m pytest`` subprocess, this module grabs the running
``Coverage`` instance and registers context-switching hooks so that coverage
contexts contain full pytest node IDs instead of bare function names.

Context format: ``{nodeid}|{when}``

Without this, ``dynamic_context = test_function`` records bare names like
``test_eq``, which are ambiguous when multiple files define functions with the
same name.  Full node IDs (``tests/test_cmp.py::test_eq``) eliminate that
ambiguity and avoid the expensive bare-name expansion in
``_populate_coverage_from_line_bits``.

Example:
    >>> from unittest.mock import MagicMock
    >>> cov = MagicMock()
    >>> plugin = _SubprocessContextPlugin(cov)
    >>> plugin.cov is cov
    True
"""

from __future__ import annotations

from collections.abc import Generator

import coverage
import pytest


def _strip_nodeid_markers(nodeid: str) -> str:
    """Strip pytest plugin markers (e.g. `` [SMALL]``) from a node ID.

    Plugins like ``pytest-test-categories`` append markers such as
    ``[SMALL]`` to node IDs during collection.  The main gremlins session
    stores node IDs *without* these markers, so contexts recorded in the
    coverage subprocess must match.

    Example:
        >>> _strip_nodeid_markers('test_module.py::test_add [SMALL]')
        'test_module.py::test_add'
        >>> _strip_nodeid_markers('test_module.py::test_add')
        'test_module.py::test_add'
    """
    idx = nodeid.find(' [')
    return nodeid[:idx] if idx != -1 else nodeid


class _SubprocessContextPlugin:
    """Switches coverage dynamic context for each test phase.

    Identical in behavior to ``GremlinContextPlugin`` but designed to be
    registered automatically via ``pytest_sessionstart`` using
    ``Coverage.current()`` — no external ``cov`` wiring required.

    Attributes:
        cov: The ``coverage.Coverage`` instance to switch contexts on.
    """

    def __init__(self, cov: coverage.Coverage) -> None:
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
        """Switch coverage context to ``{nodeid}|setup`` before test setup."""
        self._safe_switch(f'{_strip_nodeid_markers(item.nodeid)}|setup')
        yield

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item: pytest.Item) -> Generator[None, None, None]:
        """Switch coverage context to ``{nodeid}|run`` before the test call."""
        self._safe_switch(f'{_strip_nodeid_markers(item.nodeid)}|run')
        yield

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_teardown(self, item: pytest.Item) -> Generator[None, None, None]:
        """Switch coverage context to ``{nodeid}|teardown`` before teardown."""
        self._safe_switch(f'{_strip_nodeid_markers(item.nodeid)}|teardown')
        yield


def pytest_sessionstart(session: pytest.Session) -> None:
    """Register context-switching hooks if running under ``coverage run``.

    Checks ``Coverage.current()`` for a running instance.  When found,
    registers ``_SubprocessContextPlugin`` so every test phase gets a
    full-node-ID context label.  When ``None`` (not under ``coverage run``),
    does nothing — the #365 bare-name expansion handles that case.
    """
    cov = coverage.Coverage.current()
    if cov is not None:
        plugin = _SubprocessContextPlugin(cov)
        session.config.pluginmanager.register(plugin, name='gremlin-subprocess-context')
