"""Tests for --gremlin-executor CLI option and _build_gremlin_module_map helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pytest_gremlins.plugin import (
    _build_gremlin_module_map,
    pytest_addoption,
)


@pytest.mark.small
class DescribeGremlinExecutorOption:
    """Tests that --gremlin-executor CLI option is registered."""

    def it_registers_gremlin_executor_option(self) -> None:
        parser = MagicMock()
        group = MagicMock()
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_option_names = [call.args[0] for call in group.addoption.call_args_list]
        assert '--gremlin-executor' in added_option_names

    def it_defaults_to_subprocess(self) -> None:
        parser = MagicMock()
        group = MagicMock()
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_options = {c.args[0]: c.kwargs for c in group.addoption.call_args_list if c.args}
        opt_kwargs = added_options['--gremlin-executor']
        assert opt_kwargs['default'] == 'subprocess'

    def it_accepts_three_choices(self) -> None:
        parser = MagicMock()
        group = MagicMock()
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        added_options = {c.args[0]: c.kwargs for c in group.addoption.call_args_list if c.args}
        opt_kwargs = added_options['--gremlin-executor']
        assert set(opt_kwargs['choices']) == {'subprocess', 'fork', 'inprocess'}


@pytest.mark.small
class DescribeBuildGremlinModuleMap:
    """Tests for _build_gremlin_module_map helper."""

    def it_maps_simple_file_to_module_name(self) -> None:
        gremlin = MagicMock()
        gremlin.gremlin_id = 'g1'
        gremlin.file_path = '/project/src/mypackage/module.py'
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([gremlin], rootdir)

        assert result == {'g1': 'mypackage.module'}

    def it_maps_init_file_to_package_name(self) -> None:
        gremlin = MagicMock()
        gremlin.gremlin_id = 'g2'
        gremlin.file_path = '/project/src/mypackage/__init__.py'
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([gremlin], rootdir)

        assert result == {'g2': 'mypackage'}

    def it_handles_file_outside_rootdir(self) -> None:
        gremlin = MagicMock()
        gremlin.gremlin_id = 'g3'
        gremlin.file_path = '/elsewhere/module.py'
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([gremlin], rootdir)

        assert result == {'g3': 'module'}

    def it_maps_multiple_gremlins(self) -> None:
        g1 = MagicMock()
        g1.gremlin_id = 'g1'
        g1.file_path = '/project/src/pkg/a.py'
        g2 = MagicMock()
        g2.gremlin_id = 'g2'
        g2.file_path = '/project/src/pkg/b.py'
        rootdir = Path('/project/src')

        result = _build_gremlin_module_map([g1, g2], rootdir)

        assert result == {'g1': 'pkg.a', 'g2': 'pkg.b'}
