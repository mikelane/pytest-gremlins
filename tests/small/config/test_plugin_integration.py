"""Tests for plugin integration with pyproject.toml configuration.

These tests verify that pytest_configure properly loads and uses
pyproject.toml configuration, with CLI arguments taking precedence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path

from pytest_gremlins import plugin


@pytest.mark.small
class TestPytestConfigureWithFileConfig:
    """Tests for pytest_configure loading file config."""

    def test_loads_config_from_pyproject_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """pytest_configure loads [tool.pytest-gremlins] from pyproject.toml."""
        # Create a pyproject.toml with gremlins config
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\n'
            'operators = ["comparison"]\n'
            'paths = ["src/mypackage"]\n'
        )

        # Create a minimal src directory
        src_dir = tmp_path / 'src' / 'mypackage'
        src_dir.mkdir(parents=True)
        (src_dir / '__init__.py').write_text('')

        # Mock pytest config - uses class attributes to match pytest.Config structure
        class _MockOption:
            gremlins = True
            gremlin_operators: str | None = None
            gremlin_report = 'console'
            gremlin_targets: str | None = None
            gremlin_cache = False
            gremlin_clear_cache = False

        class _MockConfig:
            option = _MockOption()
            rootdir = tmp_path

        # Reset session state
        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        # Run pytest_configure - cast to satisfy type checker
        # The mock provides the subset of pytest.Config that pytest_configure uses
        plugin.pytest_configure(_MockConfig())  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.enabled is True
        # Verify operators were loaded from config
        operator_names = [op.name for op in session.operators]
        assert 'comparison' in operator_names
        # Verify paths were loaded
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'mypackage'

    def test_cli_operators_override_file_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI --gremlin-operators takes precedence over pyproject.toml."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\n'
            'operators = ["comparison", "arithmetic"]\n'
        )

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        class _MockOption:
            gremlins = True
            gremlin_operators = 'boolean'  # CLI overrides file
            gremlin_report = 'console'
            gremlin_targets: str | None = None
            gremlin_cache = False
            gremlin_clear_cache = False

        class _MockConfig:
            option = _MockOption()
            rootdir = tmp_path

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_MockConfig())  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        operator_names = [op.name for op in session.operators]
        # Only boolean should be loaded, not comparison or arithmetic
        assert 'boolean' in operator_names
        assert 'comparison' not in operator_names
        assert 'arithmetic' not in operator_names

    def test_cli_targets_override_file_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI --gremlin-targets takes precedence over pyproject.toml paths."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\n'
            'paths = ["src/original"]\n'
        )

        # Create both directories
        original_dir = tmp_path / 'src' / 'original'
        original_dir.mkdir(parents=True)
        (original_dir / '__init__.py').write_text('')

        override_dir = tmp_path / 'lib'
        override_dir.mkdir()
        (override_dir / 'module.py').write_text('x = 1')

        class _MockOption:
            gremlins = True
            gremlin_operators: str | None = None
            gremlin_report = 'console'
            gremlin_targets = 'lib'  # CLI overrides file
            gremlin_cache = False
            gremlin_clear_cache = False

        class _MockConfig:
            option = _MockOption()
            rootdir = tmp_path

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_MockConfig())  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'lib'

    def test_falls_back_to_src_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to src/ when neither CLI nor pyproject.toml specifies paths."""
        # No pyproject.toml config
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "test"\n')

        src_dir = tmp_path / 'src'
        src_dir.mkdir()
        (src_dir / 'module.py').write_text('x = 1')

        class _MockOption:
            gremlins = True
            gremlin_operators: str | None = None
            gremlin_report = 'console'
            gremlin_targets: str | None = None
            gremlin_cache = False
            gremlin_clear_cache = False

        class _MockConfig:
            option = _MockOption()
            rootdir = tmp_path

        plugin._set_session(None)
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        plugin.pytest_configure(_MockConfig())  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert len(session.target_paths) == 1
        assert session.target_paths[0].name == 'src'
