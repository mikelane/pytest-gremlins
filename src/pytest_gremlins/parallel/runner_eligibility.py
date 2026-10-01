"""Decide which collected tests the lightweight runner can judge faithfully.

The lightweight runner imports a test module and calls the test callable with
no arguments. That matches what pytest does only for a plain, synchronous,
fixture-free, unparametrized test. Anything else must go through the full
pytest bootstrap, so the runner is used only when every selected test passes
:func:`is_lightweight_safe`.
"""

from __future__ import annotations

import inspect

import pytest

MAX_NODE_ID_SEGMENTS = 3
"""``file::func`` and ``file::Class::method`` are the only shapes the runner resolves."""

_RUNTEST_HOOKS = (
    'pytest_runtest_setup',
    'pytest_runtest_call',
    'pytest_runtest_teardown',
    'pytest_pyfunc_call',
    'pytest_runtest_protocol',
)

_TRUSTED_TOP_LEVEL_PACKAGES = frozenset(
    {'_pytest', 'pytest', 'pytest_gremlins', 'pytest_test_categories', 'pytest_cov', 'xdist'}
)
"""Packages whose runtest hooks never change what a test body sees or whether it passes."""

_MARKERS_PYTEST_ACTS_ON_AROUND_THE_CALL = ('skip', 'skipif', 'xfail', 'filterwarnings')


def is_lightweight_safe(item: pytest.Item) -> bool:
    """Return whether the lightweight runner can run ``item`` as pytest would.

    ``fixturenames`` already includes autouse, conftest and xunit ``setup_*``
    fixtures, so an empty list means nothing runs around the bare call.

    Args:
        item: A collected pytest item.

    Returns:
        True only for a plain ``pytest.Function`` with no fixtures, no
        parametrization, no coroutine body, and no skip/xfail/filterwarnings markers, and no
        conftest or third-party ``pytest_runtest_*`` / ``pytest_pyfunc_call`` hook around it.
    """
    if type(item) is not pytest.Function:
        return False
    if len(item.nodeid.split('::')) > MAX_NODE_ID_SEGMENTS:
        return False
    if item.fixturenames or getattr(item, 'callspec', None) is not None:
        return False
    if inspect.iscoroutinefunction(item.obj) or inspect.isasyncgenfunction(item.obj):
        return False
    if _has_marker_pytest_acts_on(item):
        return False
    return not _has_untrusted_runtest_hook(item)


def is_trusted_plugin_module(module_name: str) -> bool:
    """Return whether runtest hooks defined in ``module_name`` leave a bare call faithful.

    Args:
        module_name: Dotted module name of the plugin or conftest that owns a hook.

    Returns:
        True for pytest itself and for plugins known not to alter the test environment.
    """
    return module_name.split('.', maxsplit=1)[0] in _TRUSTED_TOP_LEVEL_PACKAGES


def _has_untrusted_runtest_hook(item: pytest.Item) -> bool:
    """Whether a conftest or third-party plugin runs code around this test, invisibly to ``fixturenames``."""
    for hook_name in _RUNTEST_HOOKS:
        for hook_impl in getattr(item.ihook, hook_name).get_hookimpls():
            owner = hook_impl.plugin
            owner_module = getattr(owner, '__name__', None) or type(owner).__module__
            if not is_trusted_plugin_module(owner_module):
                return True
    return False


def _has_marker_pytest_acts_on(item: pytest.Item) -> bool:
    return any(item.get_closest_marker(name) is not None for name in _MARKERS_PYTEST_ACTS_ON_AROUND_THE_CALL)
