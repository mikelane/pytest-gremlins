"""Tests for plugin integration with pyproject.toml configuration.

These tests verify that pytest_configure properly loads and uses
pyproject.toml configuration, with CLI arguments taking precedence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Any

from pytest_gremlins import plugin
from pytest_gremlins.plugin import CoverageMode


@pytest.mark.medium
class DescribePytestConfigureWithFileConfig:
    """Tests for pytest_configure loading file config."""

    def it_loads_config_from_pyproject_toml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_pytest_config: Callable[..., Any]
    ) -> None:
        """pytest_configure loads [tool.pytest-gremlins] from pyproject.toml."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\noperators = ["comparison"]\npaths = ["src/mypackage"]\n')

        src_dir = tmp_path / 'src' / 'mypackage'
        src_dir.mkdir(parents=True)
        (src_dir / '__init__.py').write_text('')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(make_pytest_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.enabled is True
        operator_names = [op.name for op in session.operators]
        assert 'comparison' in operator_names
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'mypackage'

    def it_cli_operators_override_file_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_pytest_config: Callable[..., Any]
    ) -> None:
        """CLI --gremlin-operators takes precedence over pyproject.toml."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\noperators = ["comparison", "arithmetic"]\npaths = ["src"]\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(  # type: ignore[arg-type]
            make_pytest_config(tmp_path, gremlin_operators='boolean'),
        )

        session = plugin._get_session()
        assert session is not None
        operator_names = [op.name for op in session.operators]
        assert 'boolean' in operator_names
        assert 'comparison' not in operator_names
        assert 'arithmetic' not in operator_names

    def it_cli_targets_override_file_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_pytest_config: Callable[..., Any]
    ) -> None:
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
            make_pytest_config(tmp_path, gremlin_targets='lib'),
        )

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'lib'

    def it_falls_back_to_src_when_no_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_pytest_config: Callable[..., Any]
    ) -> None:
        """Falls back to src/ when neither CLI nor pyproject.toml specifies paths."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "test"\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)
        monkeypatch.setattr('pytest_gremlins.config._packages_distributions', dict)

        plugin.pytest_configure(make_pytest_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'src'

    def it_discovers_paths_from_setuptools_packages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_pytest_config: Callable[..., Any]
    ) -> None:
        """Falls back to setuptools packages when no explicit paths and no src/."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\npackages = ["cogapp"]\n')

        pkg_dir = tmp_path / 'cogapp'
        pkg_dir.mkdir()
        (pkg_dir / '__init__.py').write_text('')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(make_pytest_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'cogapp'

    def it_explicit_config_takes_precedence_over_discovery(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_pytest_config: Callable[..., Any],
    ) -> None:
        """Explicit [tool.pytest-gremlins].paths beats setuptools discovery."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\npaths = ["mylib"]\n\n[tool.setuptools]\npackages = ["cogapp"]\n')

        (tmp_path / 'mylib').mkdir()
        (tmp_path / 'cogapp').mkdir()

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(make_pytest_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'mylib'

    def it_discovery_preferred_over_src_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_pytest_config: Callable[..., Any]
    ) -> None:
        """Setuptools discovery is tried before falling back to src/."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.setuptools]\npackages = ["cogapp"]\n')

        (tmp_path / 'src').mkdir()
        (tmp_path / 'cogapp').mkdir()

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(make_pytest_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'cogapp'


@pytest.mark.medium
class DescribePytestConfigureCoverageMode:
    """pytest_configure sets coverage_mode from _detect_coverage_mode."""

    def it_uses_piggyback_coverage_when_cov_plugin_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_pytest_config: Callable[..., Any],
    ) -> None:
        """pytest_configure sets coverage_mode=PIGGYBACK when _cov plugin is registered."""
        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)
        monkeypatch.setattr('pytest_gremlins.config._packages_distributions', dict)

        pm = MagicMock()  # PytestPluginManager: sets attrs dynamically; bare-mock: ok
        pm.get_plugin.return_value = MagicMock()  # pytest-cov plugin: internal type, no public spec; bare-mock: ok
        plugin.pytest_configure(make_pytest_config(tmp_path, pluginmanager=pm))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.coverage_mode == CoverageMode.PIGGYBACK

    def it_uses_private_coverage_when_cov_plugin_absent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_pytest_config: Callable[..., Any],
    ) -> None:
        """pytest_configure sets coverage_mode=PRIVATE when _cov plugin is not registered."""
        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)
        monkeypatch.setattr('pytest_gremlins.config._packages_distributions', dict)

        pm = MagicMock()  # PytestPluginManager: sets attrs dynamically; bare-mock: ok
        pm.get_plugin.return_value = None
        plugin.pytest_configure(make_pytest_config(tmp_path, pluginmanager=pm))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.coverage_mode == CoverageMode.PRIVATE
