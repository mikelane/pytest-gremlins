"""Shared pytest configuration and fixtures for pytest-gremlins tests.

Note: Marker application is handled by the root conftest.py.
This file is for test-specific fixtures only.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import (
    TYPE_CHECKING,
    Any,
)
from unittest.mock import MagicMock

import pytest
from secret_env_scrub import scrub_secret_env  # type: ignore[import-not-found]

from pytest_gremlins.instrumentation.transformer import get_default_registry
from pytest_gremlins.operators import entry_points as loader
from pytest_gremlins.plugin import _set_session

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Generator,
    )

# Enable pytester fixture for plugin testing
pytest_plugins = ['pytester']

_SCRUBBED_SECRET_ENV: dict[str, str] = {}


def pytest_unconfigure() -> None:
    """Restore the secret variables that ``pytest_configure`` scrubbed."""
    os.environ.update(_SCRUBBED_SECRET_ENV)
    _SCRUBBED_SECRET_ENV.clear()


# Scrub in pytest_configure, not at import: pytest calls pytest_unconfigure only for a configured session, so a
# session that fails before then (a usage error) would leave an in-process caller without its secrets.
@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Scrub secret-shaped variables and register custom markers for test categorization."""
    _SCRUBBED_SECRET_ENV.update(scrub_secret_env(os.environ))
    config.addinivalue_line('markers', 'small: Fast, isolated unit tests (< 100ms)')
    config.addinivalue_line('markers', 'medium: Integration tests with real resources (< 10s)')
    config.addinivalue_line('markers', 'large: End-to-end system tests (< 60s)')


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Sort small tests before medium tests to preserve coverage tracing.

    In-process pytester (used by medium tests) resets sys.settrace when the
    inner session ends, stopping coverage.py from tracking subsequent tests.
    Running all small tests first ensures their coverage is captured before
    any in-process pytester session can clear the trace function.

    This restores the execution order that existed when tests lived in
    separate tests/small/ and tests/medium/ directories.
    """

    def _size_priority(item: pytest.Item) -> int:
        markers = {m.name for m in item.iter_markers()}
        if 'large' in markers:
            return 4
        if 'medium' in markers:
            # Pytester-based medium tests reset sys.settrace when their inner
            # pytest session ends, killing coverage for subsequent tests.
            # Run non-pytester medium tests first so they get coverage tracked.
            uses_pytester = bool({'pytester', 'pytester_with_markers'} & set(getattr(item, 'fixturenames', [])))
            return 3 if uses_pytester else 2
        return 1  # small or unmarked runs first

    items.sort(key=_size_priority)


@pytest.fixture(autouse=True)
def reset_gremlin_session() -> Generator[None, None, None]:
    """Reset the global gremlin session after each test to prevent state leakage.

    Tests that call _set_session() with enabled=True must not bleed state into
    the outer pytest process's pytest_sessionfinish hook.
    """
    yield
    _set_session(None)


@pytest.fixture
def make_pytest_config() -> Callable[..., Any]:
    """Factory fixture for building minimal mock pytest.Config objects.

    Covers the full union of option attributes used across plugin integration
    and config tests. All options default to falsy/None so TOML values flow
    through unobstructed; pass explicit kwargs to override for a specific test.

    Example::

        def it_something(self, tmp_path, make_pytest_config):
            cfg = make_pytest_config(tmp_path, gremlin_operators='boolean')
            plugin.pytest_configure(cfg)  # type: ignore[arg-type]
    """

    def _factory(
        rootdir: Path,
        *,
        gremlins: bool = True,
        gremlin_operators: str | None = None,
        gremlin_targets: str | None = None,
        gremlin_report: str | None = None,
        gremlin_cache: bool = False,
        gremlin_clear_cache: bool = False,
        gremlin_parallel: bool = False,
        gremlin_workers: int | None = None,
        gremlin_batch: bool = False,
        gremlin_batch_size: int | None = None,
        strict_pardons: bool = False,
        gremlin_audit_pardons: bool = False,
        gremlin_max_pardons_pct: float | None = None,
        max_pardons: int | None = None,
        pluginmanager: MagicMock | None = None,
        addopts: list[str] | None = None,
    ) -> object:
        class _Option:
            pass

        option = _Option()
        option.gremlins = gremlins  # type: ignore[attr-defined]
        option.gremlin_operators = gremlin_operators  # type: ignore[attr-defined]
        option.gremlin_targets = gremlin_targets  # type: ignore[attr-defined]
        option.gremlin_report = gremlin_report  # type: ignore[attr-defined]
        option.gremlin_cache = gremlin_cache  # type: ignore[attr-defined]
        option.gremlin_clear_cache = gremlin_clear_cache  # type: ignore[attr-defined]
        option.gremlin_parallel = gremlin_parallel  # type: ignore[attr-defined]
        option.gremlin_workers = gremlin_workers  # type: ignore[attr-defined]
        option.gremlin_batch = gremlin_batch  # type: ignore[attr-defined]
        option.gremlin_batch_size = gremlin_batch_size  # type: ignore[attr-defined]
        option.strict_pardons = strict_pardons  # type: ignore[attr-defined]
        option.gremlin_audit_pardons = gremlin_audit_pardons  # type: ignore[attr-defined]
        option.gremlin_max_pardons_pct = gremlin_max_pardons_pct  # type: ignore[attr-defined]
        option.max_pardons = max_pardons  # type: ignore[attr-defined]
        option.gremlin_exclude = None  # type: ignore[attr-defined]

        if pluginmanager is None:
            pm: MagicMock = MagicMock()  # PytestPluginManager: sets attrs dynamically; bare-mock: ok
            pm.hasplugin.return_value = False
            pm.get_plugin.return_value = None
        else:
            pm = pluginmanager

        ini_values = {'addopts': addopts if addopts is not None else []}

        class _InvocationParams:
            args: tuple[str, ...] = ()
            dir = Path()

        class _Config:
            invocation_params = _InvocationParams()

            def getini(self, name: str) -> object:
                # Mirror real pytest: an unregistered ini name raises rather than
                # silently returning a falsy default that could mask a config read.
                if name not in ini_values:
                    raise ValueError(f'unknown ini option: {name!r}')
                return ini_values[name]

        cfg = _Config()
        cfg.option = option  # type: ignore[attr-defined]
        cfg.rootdir = rootdir  # type: ignore[attr-defined]
        cfg.pluginmanager = pm  # type: ignore[attr-defined]
        cfg.stash = pytest.Stash()  # type: ignore[attr-defined]
        return cfg

    return _factory


@pytest.fixture
def pytester_with_markers(pytester: pytest.Pytester) -> pytest.Pytester:
    """Create a pytester instance that auto-applies small marker to tests.

    The pytest-test-categories plugin requires tests to have size markers.
    Tests created via pytester.makepyfile() don't have markers by default,
    which causes INTERNALERROR on Python 3.14 due to stricter warning handling.

    This fixture creates a conftest.py that registers the small marker and
    auto-applies it to any test that doesn't already have a size marker.
    """
    pytester.makeconftest(
        """
import pytest

def pytest_configure(config):
    config.addinivalue_line('markers', 'small: marks tests as small (fast unit tests)')

@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if not any(marker.name in ('small', 'medium', 'large') for marker in item.iter_markers()):
            item.add_marker(pytest.mark.small)
""",
    )
    return pytester


@pytest.fixture
def install_entry_point_dist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Callable[..., Path], None, None]:
    """Install a real ``.dist-info`` distribution that declares operator entry points.

    The distribution lands on ``sys.path`` and ``PYTHONPATH`` so in-process and
    child-process pytest runs both discover it through ``importlib.metadata``.
    The default operator registry and the entry-point loader's record of what it
    registered are restored at teardown, because both are process-global.
    """
    registry = get_default_registry()
    saved_operators = dict(registry._operators)
    saved_loader_record = dict(loader._registered_by_loader)
    site = tmp_path / 'ep_site'
    site.mkdir()
    installed_modules: list[str] = []

    def _install(
        entry_points: dict[str, str],
        modules: dict[str, str],
        dist_name: str = 'gremlin_ep_dist',
    ) -> Path:
        dist_info = site / f'{dist_name}-1.0.dist-info'
        dist_info.mkdir(exist_ok=True)
        (dist_info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {dist_name}\nVersion: 1.0\n')
        lines = ['[pytest_gremlins.operators]', *(f'{name} = {target}' for name, target in entry_points.items())]
        (dist_info / 'entry_points.txt').write_text('\n'.join(lines) + '\n')
        for module_name, source in modules.items():
            (site / f'{module_name}.py').write_text(source)
            installed_modules.append(module_name)
        return site

    monkeypatch.syspath_prepend(str(site))
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(filter(None, [str(site), os.environ.get('PYTHONPATH', '')])))
    try:
        yield _install
    finally:
        for module_name in installed_modules:
            sys.modules.pop(module_name, None)
        registry._operators.clear()
        registry._operators.update(saved_operators)
        loader._registered_by_loader.clear()
        loader._registered_by_loader.update(saved_loader_record)
