"""Tests for xdist incompatibility detection in pytest_configure.

These tests verify that pytest-gremlins emits a clear, actionable error
when --gremlins and -n (pytest-xdist) are used together.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from pytest_gremlins.plugin import pytest_configure


_UNSET: object = object()  # sentinel: numprocesses attribute absent (xdist not installed)


def _make_config(
    *,
    gremlins: bool = False,
    gremlin_parallel: bool = False,
    gremlin_workers: int | None = None,
    gremlin_operators: str | None = None,
    gremlin_targets: str | None = None,
    gremlin_report: str = 'console',
    gremlin_cache: bool = False,
    gremlin_clear_cache: bool = False,
    gremlin_batch: bool = False,
    gremlin_batch_size: int = 10,
    numprocesses: object = _UNSET,
) -> MagicMock:
    """Build a mock pytest.Config with the given option values.

    Pass numprocesses=_UNSET (default) to simulate xdist not installed.
    Pass numprocesses=None to simulate xdist installed but -n not passed.
    Pass numprocesses='auto' or an int to simulate -n auto / -n N.
    """
    attrs: dict[str, object] = {
        'gremlins': gremlins,
        'gremlin_parallel': gremlin_parallel,
        'gremlin_workers': gremlin_workers,
        'gremlin_operators': gremlin_operators,
        'gremlin_targets': gremlin_targets,
        'gremlin_report': gremlin_report,
        'gremlin_cache': gremlin_cache,
        'gremlin_clear_cache': gremlin_clear_cache,
        'gremlin_batch': gremlin_batch,
        'gremlin_batch_size': gremlin_batch_size,
    }
    if numprocesses is not _UNSET:
        attrs['numprocesses'] = numprocesses
    config = MagicMock()
    config.option = SimpleNamespace(**attrs)
    config.rootdir = '/fake/rootdir'
    return config


@pytest.mark.small
class DescribeXdistIncompatibilityError:
    """Tests for --gremlins + -n incompatibility detection.

    When --gremlins is active and xdist is installed and the user passed -n,
    pytest_configure must call pytest.exit with return code 4 and an actionable
    message before configuring any session state.
    """

    def it_gremlins_with_n_auto_calls_pytest_exit(self) -> None:
        """--gremlins with -n auto triggers pytest.exit with returncode 4."""
        config = _make_config(gremlins=True, numprocesses='auto')

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(config)
            mock_pytest.exit.assert_called_once()
            assert mock_pytest.exit.call_args.kwargs['returncode'] == 4

    def it_gremlins_with_n_integer_calls_pytest_exit(self) -> None:
        """--gremlins with -n 4 triggers pytest.exit with returncode 4."""
        config = _make_config(gremlins=True, numprocesses=4)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(config)
            mock_pytest.exit.assert_called_once()

    def it_gremlins_with_n_1_calls_pytest_exit(self) -> None:
        """--gremlins with -n 1 triggers pytest.exit — 1 is still an xdist invocation."""
        config = _make_config(gremlins=True, numprocesses=1)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(config)
            mock_pytest.exit.assert_called_once()

    def it_exit_message_mentions_incompatibility(self) -> None:
        """The exit message mentions incompatibility with xdist test distribution."""
        config = _make_config(gremlins=True, numprocesses=2)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(config)
            call_args = mock_pytest.exit.call_args
            message = call_args.args[0] if call_args.args else call_args.kwargs.get('msg', '')
            assert 'incompatible' in message.lower() or 'pytest-xdist' in message

    def it_exit_message_mentions_gremlin_workers_alternative(self) -> None:
        """The exit message mentions --gremlin-workers as the correct alternative."""
        config = _make_config(gremlins=True, numprocesses=2)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(config)
            call_args = mock_pytest.exit.call_args
            message = call_args.args[0] if call_args.args else call_args.kwargs.get('msg', '')
            assert '--gremlin-workers' in message

    def it_exit_message_mentions_tracking_issue(self) -> None:
        """The exit message contains the tracking issue URL."""
        config = _make_config(gremlins=True, numprocesses=2)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(config)
            call_args = mock_pytest.exit.call_args
            message = call_args.args[0] if call_args.args else call_args.kwargs.get('msg', '')
            assert 'issues/181' in message

    def it_raises_no_error_when_gremlins_disabled_with_xdist(self) -> None:
        """When --gremlins is not passed, pytest_configure returns before the xdist guard."""
        config = _make_config(gremlins=False, numprocesses='auto')
        # No patch needed: the gremlins=False early-return fires before the guard is evaluated.
        pytest_configure(config)  # no exception = correct

    def it_gremlins_with_n_0_calls_pytest_exit(self) -> None:
        """--gremlins with -n 0 triggers pytest.exit — 0 is not None, so xdist is considered active."""
        config = _make_config(gremlins=True, numprocesses=0)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(config)
            mock_pytest.exit.assert_called_once()

    def it_raises_no_error_when_gremlins_enabled_but_xdist_not_installed(self) -> None:
        """When xdist is not installed (no numprocesses attr), no error fires."""
        config = _make_config(gremlins=True)  # numprocesses attribute absent

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            with (
                patch('pytest_gremlins.plugin.load_config'),
                patch('pytest_gremlins.plugin.merge_configs'),
                patch('pytest_gremlins.plugin.get_default_registry'),
                patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            ):
                pytest_configure(config)
            mock_pytest.exit.assert_not_called()

    def it_raises_no_error_when_gremlins_enabled_and_xdist_n_not_passed(self) -> None:
        """xdist installed but -n not passed (numprocesses=None) is fine."""
        config = _make_config(gremlins=True, numprocesses=None)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            with (
                patch('pytest_gremlins.plugin.load_config'),
                patch('pytest_gremlins.plugin.merge_configs'),
                patch('pytest_gremlins.plugin.get_default_registry'),
                patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            ):
                pytest_configure(config)
            mock_pytest.exit.assert_not_called()
