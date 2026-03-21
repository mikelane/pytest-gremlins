"""Tests for plugin configuration integration.

These tests verify that pyproject.toml configuration is loaded in
pytest_configure and that CLI arguments properly override file config.
"""

import pytest

from pytest_gremlins.config import (
    GremlinConfig,
    merge_configs,
)


@pytest.mark.small
class DescribeMergeConfigs:
    """Tests for merging CLI args with pyproject.toml config."""

    def it_cli_operators_override_file_config(self):
        """CLI --gremlin-operators overrides pyproject.toml operators."""
        file_config = GremlinConfig(operators=['comparison', 'arithmetic'])
        cli_operators = 'boolean,return'

        result = merge_configs(file_config, cli_operators=cli_operators)

        assert result.operators == ['boolean', 'return']

    def it_uses_file_operators_when_cli_is_none(self):
        """Uses pyproject.toml operators when CLI is not provided."""
        file_config = GremlinConfig(operators=['comparison'])
        cli_operators = None

        result = merge_configs(file_config, cli_operators=cli_operators)

        assert result.operators == ['comparison']

    def it_cli_targets_override_file_paths(self):
        """CLI --gremlin-targets overrides pyproject.toml paths."""
        file_config = GremlinConfig(paths=['src'])
        cli_targets = 'lib,app'

        result = merge_configs(file_config, cli_targets=cli_targets)

        assert result.paths == ['lib', 'app']

    def it_uses_file_paths_when_cli_is_none(self):
        """Uses pyproject.toml paths when CLI is not provided."""
        file_config = GremlinConfig(paths=['src/mypackage'])
        cli_targets = None

        result = merge_configs(file_config, cli_targets=cli_targets)

        assert result.paths == ['src/mypackage']

    def it_returns_none_when_both_are_none(self):
        """Returns None when both CLI and file config are None."""
        file_config = GremlinConfig()
        cli_operators = None
        cli_targets = None

        result = merge_configs(file_config, cli_operators=cli_operators, cli_targets=cli_targets)

        assert result.operators is None
        assert result.paths is None

    def it_exclude_patterns_passed_through(self):
        """Exclude patterns from file config are preserved."""
        file_config = GremlinConfig(exclude=['**/migrations/*'])

        result = merge_configs(file_config)

        assert result.exclude == ['**/migrations/*']

    def it_treats_empty_cli_string_as_none(self):
        """Empty CLI string is treated as not provided."""
        file_config = GremlinConfig(operators=['comparison'])
        cli_operators = ''

        result = merge_configs(file_config, cli_operators=cli_operators)

        assert result.operators == ['comparison']

    def it_trims_whitespace_from_cli_string(self):
        """CLI values have whitespace trimmed."""
        file_config = GremlinConfig()
        cli_operators = ' boolean , arithmetic '

        result = merge_configs(file_config, cli_operators=cli_operators)

        assert result.operators == ['boolean', 'arithmetic']

    def it_cli_exclude_overrides_toml_exclude(self):
        """CLI --gremlin-exclude overrides pyproject.toml exclude patterns."""
        file_config = GremlinConfig(exclude=['**/migrations/*'])

        result = merge_configs(file_config, cli_exclude=['**/generated/*'])

        assert result.exclude == ['**/generated/*']

    def it_toml_exclude_used_when_cli_exclude_is_none(self):
        """TOML exclude patterns used when no CLI --gremlin-exclude provided."""
        file_config = GremlinConfig(exclude=['**/migrations/*', '**/vendor/*'])

        result = merge_configs(file_config, cli_exclude=None)

        assert result.exclude == ['**/migrations/*', '**/vendor/*']

    def it_exclude_is_none_when_neither_cli_nor_toml(self):
        """Exclude is None when neither CLI nor TOML provides patterns."""
        file_config = GremlinConfig()

        result = merge_configs(file_config, cli_exclude=None)

        assert result.exclude is None
