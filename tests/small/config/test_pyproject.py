"""Tests for pyproject.toml configuration loading.

The config module reads [tool.pytest-gremlins] from pyproject.toml and
provides defaults when configuration is absent.
"""

import pytest

from pytest_gremlins.config import GremlinConfig, load_config


@pytest.mark.small
class TestLoadConfig:
    """Tests for load_config function."""

    def test_returns_gremlin_config_instance(self, tmp_path):
        """load_config returns a GremlinConfig object."""
        result = load_config(tmp_path)

        assert isinstance(result, GremlinConfig)

    def test_returns_defaults_when_no_pyproject_toml(self, tmp_path):
        """Returns default config when pyproject.toml does not exist."""
        result = load_config(tmp_path)

        assert result.operators is None
        assert result.paths is None
        assert result.exclude is None

    def test_returns_defaults_when_no_tool_section(self, tmp_path):
        """Returns default config when [tool.pytest-gremlins] is absent."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "test"\n')

        result = load_config(tmp_path)

        assert result.operators is None
        assert result.paths is None
        assert result.exclude is None

    def test_reads_operators_list(self, tmp_path):
        """Reads operators list from config."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\n'
            'operators = ["comparison", "arithmetic"]\n'
        )

        result = load_config(tmp_path)

        assert result.operators == ['comparison', 'arithmetic']

    def test_reads_paths_list(self, tmp_path):
        """Reads paths list from config."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\n'
            'paths = ["src", "lib"]\n'
        )

        result = load_config(tmp_path)

        assert result.paths == ['src', 'lib']

    def test_reads_exclude_list(self, tmp_path):
        """Reads exclude patterns list from config."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\n'
            'exclude = ["**/migrations/*", "**/test_*"]\n'
        )

        result = load_config(tmp_path)

        assert result.exclude == ['**/migrations/*', '**/test_*']

    def test_reads_all_config_options(self, tmp_path):
        """Reads all config options together."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\n'
            'operators = ["boolean"]\n'
            'paths = ["src/mypackage"]\n'
            'exclude = ["**/conftest.py"]\n'
        )

        result = load_config(tmp_path)

        assert result.operators == ['boolean']
        assert result.paths == ['src/mypackage']
        assert result.exclude == ['**/conftest.py']

    def test_ignores_unknown_config_keys(self, tmp_path):
        """Unknown config keys are ignored."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\n'
            'unknown_key = "value"\n'
            'operators = ["comparison"]\n'
        )

        result = load_config(tmp_path)

        assert result.operators == ['comparison']
        assert not hasattr(result, 'unknown_key')

    def test_handles_empty_tool_section(self, tmp_path):
        """Handles empty [tool.pytest-gremlins] section."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\n')

        result = load_config(tmp_path)

        assert result.operators is None
        assert result.paths is None
        assert result.exclude is None


@pytest.mark.small
class TestGremlinConfig:
    """Tests for GremlinConfig dataclass."""

    def test_default_values_are_none(self):
        """Default values are None (meaning use CLI defaults)."""
        config = GremlinConfig()

        assert config.operators is None
        assert config.paths is None
        assert config.exclude is None

    def test_accepts_all_fields(self):
        """Accepts all configuration fields."""
        config = GremlinConfig(
            operators=['comparison'],
            paths=['src'],
            exclude=['**/test_*'],
        )

        assert config.operators == ['comparison']
        assert config.paths == ['src']
        assert config.exclude == ['**/test_*']
