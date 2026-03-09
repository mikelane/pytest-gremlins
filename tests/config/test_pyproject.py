"""Tests for pyproject.toml configuration loading.

The config module reads [tool.pytest-gremlins] from pyproject.toml and
provides defaults when configuration is absent.
"""

import pytest

from pytest_gremlins.config import (
    GremlinConfig,
    load_config,
)


@pytest.mark.medium
class DescribeLoadConfig:
    """Tests for load_config function."""

    def it_returns_gremlin_config_instance(self, tmp_path):
        """load_config returns a GremlinConfig object."""
        result = load_config(tmp_path)

        assert isinstance(result, GremlinConfig)

    def it_returns_defaults_when_no_pyproject_toml(self, tmp_path):
        """Returns default config when pyproject.toml does not exist."""
        result = load_config(tmp_path)

        assert result.operators is None
        assert result.paths is None
        assert result.exclude is None

    def it_returns_defaults_when_no_tool_section(self, tmp_path):
        """Returns default config when [tool.pytest-gremlins] is absent."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[project]\nname = "test"\n')

        result = load_config(tmp_path)

        assert result.operators is None
        assert result.paths is None
        assert result.exclude is None

    def it_reads_operators_list(self, tmp_path):
        """Reads operators list from config."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\noperators = ["comparison", "arithmetic"]\n')

        result = load_config(tmp_path)

        assert result.operators == ['comparison', 'arithmetic']

    def it_reads_paths_list(self, tmp_path):
        """Reads paths list from config."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\npaths = ["src", "lib"]\n')

        result = load_config(tmp_path)

        assert result.paths == ['src', 'lib']

    def it_reads_exclude_list(self, tmp_path):
        """Reads exclude patterns list from config."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nexclude = ["**/migrations/*", "**/test_*"]\n')

        result = load_config(tmp_path)

        assert result.exclude == ['**/migrations/*', '**/test_*']

    def it_reads_all_config_options(self, tmp_path):
        """Reads all config options together."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(
            '[tool.pytest-gremlins]\noperators = ["boolean"]'
            '\npaths = ["src/mypackage"]\nexclude = ["**/conftest.py"]\n',
        )

        result = load_config(tmp_path)

        assert result.operators == ['boolean']
        assert result.paths == ['src/mypackage']
        assert result.exclude == ['**/conftest.py']

    def it_ignores_unknown_config_keys(self, tmp_path):
        """Unknown config keys are ignored."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nunknown_key = "value"\noperators = ["comparison"]\n')

        result = load_config(tmp_path)

        assert result.operators == ['comparison']
        assert not hasattr(result, 'unknown_key')

    def it_returns_defaults_for_empty_tool_section(self, tmp_path):
        """Handles empty [tool.pytest-gremlins] section."""
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\n')

        result = load_config(tmp_path)

        assert result.operators is None
        assert result.paths is None
        assert result.exclude is None


@pytest.mark.small
class DescribeGremlinConfig:
    """Tests for GremlinConfig dataclass."""

    def it_defaults_all_values_to_none(self):
        """Default values are None (meaning use CLI defaults)."""
        config = GremlinConfig()

        assert config.operators is None
        assert config.paths is None
        assert config.exclude is None

    def it_accepts_all_fields(self):
        """Accepts all configuration fields."""
        config = GremlinConfig(
            operators=['comparison'],
            paths=['src'],
            exclude=['**/test_*'],
        )

        assert config.operators == ['comparison']
        assert config.paths == ['src']
        assert config.exclude == ['**/test_*']
