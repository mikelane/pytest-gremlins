"""Drift check 1b: the documented ``[tool.pytest-gremlins]`` keys are exactly the keys the config loader reads."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from pytest_gremlins.config import (
    CONFIG_KEYS,
    GremlinConfig,
)

from .docs_facts import (
    documented_keys,
    keys_shown_in_toml_blocks,
    keys_the_loader_ignores,
)


@pytest.mark.medium
class DescribeConfigKeyDocumentation:
    """The pyproject.toml reference in configuration.md matches the config loader."""

    def it_documents_every_loader_key_in_the_options_table(self):
        undocumented = CONFIG_KEYS - documented_keys()

        assert not undocumented, (
            f'Keys read by config.py but missing from the options table in configuration.md: {sorted(undocumented)}'
        )

    def it_shows_every_loader_key_in_a_toml_block(self):
        never_shown = CONFIG_KEYS - keys_shown_in_toml_blocks()

        assert not never_shown, f'Keys read by config.py but absent from every TOML example: {sorted(never_shown)}'

    def it_documents_no_key_the_loader_does_not_read(self):
        stale = documented_keys() - CONFIG_KEYS

        assert not stale, f'configuration.md documents keys config.py does not read: {sorted(stale)}'

    def it_shows_no_toml_key_the_loader_does_not_read(self):
        unknown = keys_shown_in_toml_blocks() - CONFIG_KEYS

        assert not unknown, f'TOML examples in configuration.md use keys config.py does not read: {sorted(unknown)}'

    def it_keeps_the_key_constant_in_step_with_the_config_fields(self):
        field_keys = {field.name for field in fields(GremlinConfig)}

        assert {key.replace('-', '_') for key in CONFIG_KEYS} == field_keys

    def it_loads_every_documented_example_value(self, tmp_path: Path):
        ignored = keys_the_loader_ignores(tmp_path)

        assert not ignored, f'The loader accepts but drops these documented keys: {sorted(ignored)}'
