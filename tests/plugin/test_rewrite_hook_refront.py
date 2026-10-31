"""The finder re-front hook leaves a plain pytest session alone when sys.meta_path holds an odd entry (#615)."""

from __future__ import annotations

import sys

import pytest

from pytest_gremlins import plugin


class _LazyProxyFinder:
    """A meta_path entry whose attribute lookup raises something other than AttributeError."""

    def __getattr__(self, name: str) -> object:
        msg = f'lazy proxy not ready: {name}'
        raise RuntimeError(msg)


@pytest.mark.small
def it_survives_a_meta_path_entry_whose_attribute_lookup_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy = _LazyProxyFinder()
    monkeypatch.setattr(sys, 'meta_path', [proxy, *sys.meta_path])
    hook = plugin.pytest_load_initial_conftests()

    next(hook)

    assert sys.meta_path[0] is proxy
