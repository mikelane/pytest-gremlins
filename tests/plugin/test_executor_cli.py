"""Tests for --gremlin-executor CLI option, _build_gremlin_module_map, and _run_mutation_testing_inprocess."""

from __future__ import annotations

import ast
from unittest.mock import (
    MagicMock,
)

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.plugin import (
    pytest_addoption,
)


def _make_gremlin(
    gremlin_id: str,
    file_path: str,
    *,
    pardoned: bool = False,
    pardon_reason: str | None = None,
) -> Gremlin:
    """Create a Gremlin with minimal valid fields for testing."""
    return Gremlin(
        gremlin_id=gremlin_id,
        file_path=file_path,
        line_number=1,
        original_node=ast.Constant(value=True),
        mutated_node=ast.Constant(value=False),
        operator_name='BooleanNegate',
        description='negate boolean',
        pardoned=pardoned,
        pardon_reason=pardon_reason,
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
