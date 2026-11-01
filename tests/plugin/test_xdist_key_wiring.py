"""Probe: pytest_configure wires the #668 key part into the cache a real session opens."""

from __future__ import annotations

from cov_samples import (  # type: ignore[import-not-found]
    SESSION_ARGS,
    write_project,
)
import pytest

from pytest_gremlins.cache.incremental import XDIST_KEY_PART
from pytest_gremlins.cache.store import ResultStore


@pytest.fixture
def autoload_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
    monkeypatch.delenv('PYTEST_PLUGINS', raising=False)


def _stored_keys(pytester: pytest.Pytester) -> list[str]:
    store = ResultStore(pytester.path / '.gremlins_cache' / 'results.db')
    try:
        return store.keys()
    finally:
        store.close()


@pytest.mark.medium
@pytest.mark.usefixtures('autoload_disabled')
class DescribeXdistKeyPartWiring:
    def it_keys_verdicts_with_the_xdist_part_when_gremlin_runs_load_xdist(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)

        pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '-p', 'xdist.plugin', '--gremlin-cache')

        keys = _stored_keys(pytester_with_markers)
        assert keys
        assert all(f':{XDIST_KEY_PART}:' in key for key in keys)

    def it_keys_verdicts_without_the_xdist_part_when_xdist_is_not_loaded(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        write_project(pytester_with_markers)

        pytester_with_markers.runpytest_subprocess(*SESSION_ARGS, '--gremlin-cache')

        keys = _stored_keys(pytester_with_markers)
        assert keys
        assert not any(XDIST_KEY_PART in key for key in keys)
