"""Per-gremlin pytest subprocesses must not be distributed to xdist workers (refs #486)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.plugin import _build_test_command
from pytest_gremlins.xdist_options import env_without_xdist_addopts


@pytest.mark.small
class DescribeEnvWithoutXdistAddopts:
    def it_strips_xdist_options_from_pytest_addopts(self) -> None:
        env = env_without_xdist_addopts({'PYTEST_ADDOPTS': '-n 2 --import-mode=importlib'})

        pytest_addopts = env['PYTEST_ADDOPTS']

        assert pytest_addopts == '--import-mode=importlib'

    def it_drops_pytest_addopts_when_only_xdist_options_were_set(self) -> None:
        env = env_without_xdist_addopts({'PYTEST_ADDOPTS': '-n auto', 'HOME': '/h'})

        assert 'PYTEST_ADDOPTS' not in env

    def it_leaves_other_variables_untouched(self) -> None:
        env = env_without_xdist_addopts({'PYTEST_ADDOPTS': '-n 2', 'COVERAGE_PROCESS_START': 'rc'})

        coverage_start = env['COVERAGE_PROCESS_START']

        assert coverage_start == 'rc'

    def it_does_not_mutate_the_input(self) -> None:
        original = {'PYTEST_ADDOPTS': '-n 2'}

        env_without_xdist_addopts(original)

        assert original == {'PYTEST_ADDOPTS': '-n 2'}

    def it_returns_the_environment_unchanged_when_pytest_addopts_is_absent(self) -> None:
        assert env_without_xdist_addopts({'HOME': '/h'}) == {'HOME': '/h'}


@pytest.mark.small
class DescribeBuildTestCommandWithXdistAddopts:
    def it_strips_xdist_options_from_the_bootstrap_addopts_override(self, tmp_path: Path) -> None:
        command = _build_test_command(tmp_path, '-n 2 --import-mode=importlib')

        override = command[command.index('-o') + 1]

        assert override == 'addopts=--import-mode=importlib'

    def it_strips_xdist_options_from_the_direct_pytest_addopts_override(self) -> None:
        command = _build_test_command(None, '-n 2 --import-mode=importlib')

        override = command[command.index('-o') + 1]

        assert override == 'addopts=--import-mode=importlib'

    def it_does_not_disable_the_xdist_plugin(self, tmp_path: Path) -> None:
        command = _build_test_command(tmp_path, '-n auto')

        assert 'no:xdist' not in command


@pytest.mark.small
class DescribeBuildTestCommandForcingSingleProcess:
    """``-n 0`` is last on the command line, so it beats any spelling of ``-n`` in addopts or PYTEST_ADDOPTS."""

    def it_ends_the_bootstrap_command_with_n_zero_when_xdist_is_loaded(self, tmp_path: Path) -> None:
        command = _build_test_command(tmp_path, '-xn 2', xdist_loaded=True)

        assert command[-2:] == ['-n', '0']

    def it_ends_the_direct_pytest_command_with_n_zero_when_xdist_is_loaded(self) -> None:
        command = _build_test_command(None, '', xdist_loaded=True)

        assert command[-2:] == ['-n', '0']

    def it_omits_n_zero_when_xdist_is_not_loaded(self, tmp_path: Path) -> None:
        command = _build_test_command(tmp_path, '', xdist_loaded=False)

        assert '-n' not in command

    def it_omits_n_zero_by_default(self) -> None:
        assert '-n' not in _build_test_command(None)
