"""Tests for --strict-pardons and --gremlin-audit-pardons plugin flags."""

from __future__ import annotations

from unittest.mock import MagicMock

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    pytest_addoption,
)


@pytest.mark.small
class DescribeGremlinSessionStrictPardons:
    """Tests for strict_pardons field on GremlinSession."""

    def it_defaults_strict_pardons_to_false(self):
        session = GremlinSession()
        assert session.strict_pardons is False

    def it_accepts_strict_pardons_true(self):
        session = GremlinSession(strict_pardons=True)
        assert session.strict_pardons is True


@pytest.mark.small
class DescribePytestAddoptionPardons:
    """Tests that pardon CLI options are registered."""

    def it_registers_strict_pardons_option(self):
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_option_names = [call.args[0] for call in group.addoption.call_args_list]
        assert '--strict-pardons' in added_option_names

    def it_registers_gremlin_audit_pardons_option(self):
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_option_names = [call.args[0] for call in group.addoption.call_args_list]
        assert '--gremlin-audit-pardons' in added_option_names


@pytest.mark.small
class DescribeGremlinSessionAuditPardons:
    """Tests for audit_pardons field on GremlinSession."""

    def it_defaults_audit_pardons_to_false(self):
        session = GremlinSession()
        assert session.audit_pardons is False

    def it_accepts_audit_pardons_true(self):
        session = GremlinSession(audit_pardons=True)
        assert session.audit_pardons is True
