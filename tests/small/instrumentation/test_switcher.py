"""Tests for the mutation switcher mechanism."""

from __future__ import annotations

import pytest

from pytest_gremlins.instrumentation.switcher import (
    ACTIVE_GREMLIN_ENV_VAR,
    get_active_gremlin,
)


@pytest.mark.small
class DescribeActiveGremlin:
    """Test the active gremlin detection."""

    def it_returns_none_when_active_gremlin_env_not_set(self, monkeypatch):
        monkeypatch.delenv('ACTIVE_GREMLIN', raising=False)

        assert get_active_gremlin() is None

    def it_returns_gremlin_id_when_active_gremlin_env_is_set(self, monkeypatch):
        monkeypatch.setenv('ACTIVE_GREMLIN', 'g001')

        assert get_active_gremlin() == 'g001'

    def it_returns_empty_string_when_active_gremlin_env_is_empty(self, monkeypatch):
        monkeypatch.setenv('ACTIVE_GREMLIN', '')

        assert get_active_gremlin() == ''


@pytest.mark.small
class DescribeActiveGremlinEnvVar:
    """Test the ACTIVE_GREMLIN_ENV_VAR constant."""

    def it_env_var_name_is_active_gremlin(self):
        """Verifies the expected environment variable name."""
        assert ACTIVE_GREMLIN_ENV_VAR == 'ACTIVE_GREMLIN'
