"""``_command_line_loads_module`` finds a module-name ``-p`` loader in the session's arguments (issue #684)."""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import _command_line_loads_module


@pytest.mark.small
class DescribeCommandLineLoadsModule:
    @pytest.mark.parametrize(
        'args',
        [['-p', 'pytest_rerunfailures'], ['-ppytest_rerunfailures'], ['tests', '-x', '-p', 'pytest_rerunfailures']],
    )
    def it_finds_the_loader(self, args: list[str]) -> None:
        assert _command_line_loads_module(args, 'pytest_rerunfailures') is True

    @pytest.mark.parametrize(
        'args',
        [[], ['-p', 'rerunfailures'], ['-p'], ['pytest_rerunfailures'], ['-p', 'no:pytest_rerunfailures']],
    )
    def it_ignores_everything_else(self, args: list[str]) -> None:
        assert _command_line_loads_module(args, 'pytest_rerunfailures') is False
