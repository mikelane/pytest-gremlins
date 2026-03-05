"""Tests for xdist hook availability guard.

When pytest-xdist is not installed, plugin.py must NOT define
``pytest_configure_node`` or ``pytest_xdist_node_collection_finished``
at module scope.  If these hooks exist without a matching hook spec,
pluggy's ``check_pending()`` rejects the plugin at load time.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from unittest.mock import patch

import pytest


def _load_plugin_fresh(*, block_xdist: bool) -> object:
    """Load pytest_gremlins.plugin into a *fresh* module namespace.

    ``importlib.reload`` preserves the old ``__dict__``, so names defined
    in a previous load survive even when the guarded ``if`` block is
    skipped.  Using ``module_from_spec`` + ``exec_module`` gives us a
    truly clean namespace.
    """
    spec = importlib.util.find_spec('pytest_gremlins.plugin')
    assert spec is not None
    assert spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)

    if block_xdist:
        with patch.dict(sys.modules, {'xdist': None}):
            spec.loader.exec_module(fresh)
    else:
        spec.loader.exec_module(fresh)
    return fresh


@pytest.mark.small
class DescribeXdistHookGuard:
    """xdist hooks are only defined when xdist is importable."""

    def it_defines_pytest_configure_node_when_xdist_available(self) -> None:
        """With xdist installed (our dev env), the hook exists."""
        mod = _load_plugin_fresh(block_xdist=False)
        assert hasattr(mod, 'pytest_configure_node')

    def it_defines_pytest_xdist_node_collection_finished_when_xdist_available(self) -> None:
        """With xdist installed (our dev env), the hook exists."""
        mod = _load_plugin_fresh(block_xdist=False)
        assert hasattr(mod, 'pytest_xdist_node_collection_finished')

    def it_omits_pytest_configure_node_when_xdist_unavailable(self) -> None:
        """Without xdist, pytest_configure_node is not defined on the module."""
        mod = _load_plugin_fresh(block_xdist=True)
        assert not hasattr(mod, 'pytest_configure_node')

    def it_omits_pytest_xdist_node_collection_finished_when_xdist_unavailable(self) -> None:
        """Without xdist, pytest_xdist_node_collection_finished is not defined on the module."""
        mod = _load_plugin_fresh(block_xdist=True)
        assert not hasattr(mod, 'pytest_xdist_node_collection_finished')
