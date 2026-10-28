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


@pytest.mark.medium
class DescribeXdistHookGuard:
    """xdist hooks are only defined when xdist is importable.

    Medium because ``_load_plugin_fresh`` executes ``plugin.py`` from disk, which reads
    the source (and pytest's cached bytecode) from the installed package directory.
    """

    def it_defines_pytest_xdist_node_collection_finished_when_xdist_available(self) -> None:
        """With xdist installed (our dev env), the hook exists."""
        mod = _load_plugin_fresh(block_xdist=False)
        assert hasattr(mod, 'pytest_xdist_node_collection_finished')

    @pytest.mark.parametrize('block_xdist', [False, True], ids=['xdist-available', 'xdist-unavailable'])
    def it_never_defines_pytest_configure_node(self, block_xdist: bool) -> None:
        """No worker input is injected: workers need nothing from the controller (#533)."""
        mod = _load_plugin_fresh(block_xdist=block_xdist)
        assert not hasattr(mod, 'pytest_configure_node')

    def it_omits_pytest_xdist_node_collection_finished_when_xdist_unavailable(self) -> None:
        """Without xdist, pytest_xdist_node_collection_finished is not defined on the module."""
        mod = _load_plugin_fresh(block_xdist=True)
        assert not hasattr(mod, 'pytest_xdist_node_collection_finished')


@pytest.mark.medium
class DescribeXdistDisabledRuns:
    """xdist hooks are safe when pytest disables the xdist plugin."""

    def it_allows_pytest_to_disable_xdist_when_xdist_is_installed(self, pytester_with_markers: pytest.Pytester) -> None:
        """When xdist is installed but disabled, gremlins' xdist hooks are optional."""
        pytester_with_markers.makepyfile(
            test_sample="""
            def test_pass():
                assert True
            """,
        )

        result = pytester_with_markers.runpytest('-p', 'no:xdist', '-q')

        assert result.ret == 0
        result.stdout.fnmatch_lines(['*1 passed*'])

    def it_allows_gremlins_to_run_when_xdist_is_disabled(self, pytester_with_markers: pytest.Pytester) -> None:
        """The mutation phase still runs sequentially with ``--gremlins -p no:xdist``."""
        pytester_with_markers.makepyfile(
            src_module="""
            def answer():
                return 42
            """,
            test_sample="""
            from src_module import answer

            def test_answer():
                assert answer() == 42
            """,
        )

        result = pytester_with_markers.runpytest('-p', 'no:xdist', '--gremlins', '-q')

        assert result.ret == 0
        result.stdout.fnmatch_lines(['*1 passed*'])
