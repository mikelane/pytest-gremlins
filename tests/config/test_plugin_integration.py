"""Tests for plugin integration with pyproject.toml configuration.

These tests verify that pytest_configure properly loads and uses
pyproject.toml configuration, with CLI arguments taking precedence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pytest_gremlins import plugin
from pytest_gremlins.plugin import CoverageMode


def _make_pluginmanager(*, has_pytest_cov: bool = False) -> MagicMock:
    """Return a minimal pluginmanager mock for pytest_configure tests."""
    pm = MagicMock()
    pm.hasplugin.return_value = has_pytest_cov
    return pm


def _make_gremlins_config(
    tmp_path: Path,
    *,
    gremlin_operators: str | None = None,
    gremlin_targets: str | None = None,
    pluginmanager: MagicMock | None = None,
) -> object:
    """Build a minimal mock pytest.Config for pytest_configure tests.

    Only the fields that vary across tests are parameters; all other
    option fields use the standard defaults.
    """

    class _MockOption:
        gremlins = True
        gremlin_report = 'console'
        gremlin_cache = False
        gremlin_clear_cache = False
        gremlin_parallel = False
        gremlin_workers: int | None = None
        gremlin_batch = False
        gremlin_batch_size = 10
        strict_pardons = False
        gremlin_audit_pardons = False
        gremlin_max_pardons_pct: float | None = None

    option = _MockOption()
    option.gremlin_operators = gremlin_operators  # type: ignore[attr-defined]
    option.gremlin_targets = gremlin_targets  # type: ignore[attr-defined]

    class _MockConfig:
        pass

    cfg = _MockConfig()
    cfg.option = option  # type: ignore[attr-defined]
    cfg.rootdir = tmp_path  # type: ignore[attr-defined]
    cfg.pluginmanager = pluginmanager or _make_pluginmanager()  # type: ignore[attr-defined]
    return cfg


@pytest.mark.small
class DescribePytestConfigureWithFileConfig:
    """Tests for pytest_configure loading file config."""

    def it_loads_config_from_pyproject_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pytest_configure loads [tool.pytest-gremlins] from pyproject.toml."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\noperators = ["comparison"]\npaths = ["src/mypackage"]\n')

        src_dir = tmp_path / 'src' / 'mypackage'
        src_dir.mkdir(parents=True)
        (src_dir / '__init__.py').write_text('')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.enabled is True
        operator_names = [op.name for op in session.operators]
        assert 'comparison' in operator_names
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'mypackage'

    def it_cli_operators_override_file_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI --gremlin-operators takes precedence over pyproject.toml."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\noperators = ["comparison", "arithmetic"]\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(  # type: ignore[arg-type]
            _make_gremlins_config(tmp_path, gremlin_operators='boolean'),
        )

        session = plugin._get_session()
        assert session is not None
        operator_names = [op.name for op in session.operators]
        assert 'boolean' in operator_names
        assert 'comparison' not in operator_names
        assert 'arithmetic' not in operator_names

    def it_cli_targets_override_file_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI --gremlin-targets takes precedence over pyproject.toml paths."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\npaths = ["src/original"]\n')

        original_dir = tmp_path / 'src' / 'original'
        original_dir.mkdir(parents=True)
        (original_dir / '__init__.py').write_text('')

        override_dir = tmp_path / 'lib'
        override_dir.mkdir()
        (override_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(  # type: ignore[arg-type]
            _make_gremlins_config(tmp_path, gremlin_targets='lib'),
        )

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'lib'

    def it_falls_back_to_src_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to src/ when neither CLI nor pyproject.toml specifies paths."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "test"\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'src'

    def it_discovers_paths_from_setuptools_packages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to setuptools packages when no explicit paths and no src/."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\npackages = ["cogapp"]\n')

        pkg_dir = tmp_path / 'cogapp'
        pkg_dir.mkdir()
        (pkg_dir / '__init__.py').write_text('')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'cogapp'

    def it_explicit_config_takes_precedence_over_discovery(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Explicit [tool.pytest-gremlins].paths beats setuptools discovery."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\npaths = ["mylib"]\n\n[tool.setuptools]\npackages = ["cogapp"]\n')

        (tmp_path / 'mylib').mkdir()
        (tmp_path / 'cogapp').mkdir()

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'mylib'

    def it_discovery_preferred_over_src_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setuptools discovery is tried before falling back to src/."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\npackages = ["cogapp"]\n')

        (tmp_path / 'src').mkdir()
        (tmp_path / 'cogapp').mkdir()

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_make_gremlins_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'cogapp'


@pytest.mark.small
class DescribePytestConfigureCoverageMode:
    """pytest_configure sets coverage_mode from _detect_coverage_mode."""

    def _make_mock_config(self, tmp_path: Path, cov_plugin: object) -> object:
        """Build a minimal _MockConfig with pluginmanager returning cov_plugin."""
        pm = MagicMock()
        pm.get_plugin.return_value = cov_plugin
        return _make_gremlins_config(tmp_path, pluginmanager=pm)

    def it_uses_piggyback_coverage_when_cov_plugin_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """pytest_configure sets coverage_mode=PIGGYBACK when _cov plugin is registered."""
        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        config = self._make_mock_config(tmp_path, cov_plugin=MagicMock())
        plugin.pytest_configure(config)  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.coverage_mode == CoverageMode.PIGGYBACK

    def it_uses_private_coverage_when_cov_plugin_absent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """pytest_configure sets coverage_mode=PRIVATE when _cov plugin is not registered."""
        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        config = self._make_mock_config(tmp_path, cov_plugin=None)
        plugin.pytest_configure(config)  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.coverage_mode == CoverageMode.PRIVATE
