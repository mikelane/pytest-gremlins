"""Tests for the --gremlin-executor CLI option registration."""

from __future__ import annotations

from unittest.mock import (
    MagicMock,
)

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
import pytest

from pytest_gremlins.plugin import (
    pytest_addoption,
)


@pytest.mark.small
class DescribeGremlinExecutorOption:
    """Tests that --gremlin-executor CLI option is registered."""

    def it_registers_gremlin_executor_option(self) -> None:
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_option_names = [call.args[0] for call in group.addoption.call_args_list]
        assert '--gremlin-executor' in added_option_names

    def it_defaults_to_auto(self) -> None:
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_options = {c.args[0]: c.kwargs for c in group.addoption.call_args_list if c.args}
        opt_kwargs = added_options['--gremlin-executor']
        assert opt_kwargs['default'] == 'auto'

    def it_accepts_four_choices(self) -> None:
        parser = MagicMock(spec=Parser)
        group = MagicMock(spec=OptionGroup)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_options = {c.args[0]: c.kwargs for c in group.addoption.call_args_list if c.args}
        opt_kwargs = added_options['--gremlin-executor']
        assert set(opt_kwargs['choices']) == {'auto', 'subprocess', 'fork', 'inprocess'}
