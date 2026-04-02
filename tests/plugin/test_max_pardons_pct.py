"""Tests for --gremlin-max-pardons-pct threshold enforcement."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import (
    MagicMock,
    patch,
)

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
from _pytest.terminal import TerminalReporter
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

from pytest_gremlins import plugin
from pytest_gremlins.config import (
    GremlinConfig,
    load_config,
    merge_configs,
)
from pytest_gremlins.plugin import (
    GremlinSession,
    pytest_addoption,
    pytest_configure,
    pytest_terminal_summary,
)
from pytest_gremlins.reporting.score import MutationScore


@pytest.mark.small
class DescribeMaxPardonsPct:
    """GremlinSession.max_pardons_pct field and threshold enforcement."""

    def it_defaults_to_none(self) -> None:
        session = GremlinSession()

        assert session.max_pardons_pct is None

    def it_accepts_a_float_value(self) -> None:
        session = GremlinSession(max_pardons_pct=5.0)

        assert session.max_pardons_pct == 5.0

    def it_registers_cli_flag(self) -> None:
        mock_group = MagicMock(spec=OptionGroup)
        mock_parser = MagicMock(spec=Parser)
        mock_parser.getgroup.return_value = mock_group

        pytest_addoption(mock_parser)

        added_options = {c.args[0]: c.kwargs for c in mock_group.addoption.call_args_list if c.args}
        assert '--gremlin-max-pardons-pct' in added_options
        opt_kwargs = added_options['--gremlin-max-pardons-pct']
        assert opt_kwargs.get('type') is float
        assert opt_kwargs.get('default') is None

    def it_no_exit_when_max_pardons_pct_is_none(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons_pct=None)
        score = MutationScore(total=10, zapped=5, survived=3, timeout=0, error=0, pardoned=2, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_not_called()

    def it_no_exit_when_pardoned_pct_within_limit(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons_pct=20.0)
        # 2 pardoned of 10 total = 20.0% — exactly at limit, not exceeding
        score = MutationScore(total=10, zapped=8, survived=0, timeout=0, error=0, pardoned=2, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_not_called()

    def it_exits_when_pardoned_pct_exceeds_limit(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons_pct=10.0)
        # 3 pardoned of 10 total = 30.0% — exceeds 10.0% limit
        score = MutationScore(total=10, zapped=7, survived=0, timeout=0, error=0, pardoned=3, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_called_once()
        exit_call_args = mock_pytest.exit.call_args
        exit_message = exit_call_args.args[0] if exit_call_args.args else exit_call_args.kwargs.get('msg', '')
        assert exit_call_args.kwargs.get('returncode') == 1
        assert '30.0%' in exit_message
        assert '10.0%' in exit_message
        assert '3 pardoned gremlins' in exit_message
        assert '--gremlin-max-pardons-pct' in exit_message

    def it_cli_value_overrides_toml_value(self) -> None:
        file_config = GremlinConfig(max_pardons_pct=5.0)

        merged = merge_configs(file_config, cli_max_pardons_pct=15.0)

        assert merged.max_pardons_pct == 15.0

    def it_no_exit_when_total_is_zero(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons_pct=5.0)
        score = MutationScore(total=0, zapped=0, survived=0, timeout=0, error=0, pardoned=0, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_not_called()

    def it_logs_info_when_pardoned_pct_within_limit(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons_pct=20.0)
        # 2 pardoned of 10 total = 20.0% — exactly at limit, not exceeding
        score = MutationScore(total=10, zapped=8, survived=0, timeout=0, error=0, pardoned=2, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            caplog.at_level(logging.INFO, logger='pytest_gremlins.plugin'),
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest'),
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) == 1
        assert '20.0%' in info_records[0].message

    def it_logs_warning_when_pardoned_pct_exceeds_limit(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons_pct=10.0)
        # 3 pardoned of 10 total = 30.0% — exceeds 10.0% limit
        score = MutationScore(total=10, zapped=7, survived=0, timeout=0, error=0, pardoned=3, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.plugin'),
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest'),
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert '30.0%' in caplog.records[0].message
        assert '10.0%' in caplog.records[0].message

    def it_exits_when_pardoned_pct_exceeds_zero_limit(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons_pct=0.0)
        # 1 pardoned of 5 total = 20.0% — exceeds 0.0% limit
        score = MutationScore(total=5, zapped=4, survived=0, timeout=0, error=0, pardoned=1, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_called_once()

    def it_no_exit_when_all_pardoned_at_100_limit(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons_pct=100.0)
        # 10 pardoned of 10 total = 100.0% — exactly at limit, not exceeding
        score = MutationScore(total=10, zapped=0, survived=0, timeout=0, error=0, pardoned=10, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_not_called()


@pytest.mark.medium
class DescribeMaxPardonsPctFileIO:
    """GremlinSession.max_pardons_pct — tests that read/write real pyproject.toml files."""

    def it_reads_max_pardons_pct_from_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = 5.0\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.max_pardons_pct == 5.0

    def it_toml_max_pardons_pct_flows_into_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_pytest_config: Callable[..., Any]
    ) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = 7.5\n')

        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        pytest_configure(make_pytest_config(tmp_path))  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.max_pardons_pct == 7.5

    def it_rejects_non_numeric_max_pardons_pct_in_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = "five"\n')

        with pytest.raises(ValueError, match='max-pardons-pct'):
            load_config(tmp_path)

    def it_rejects_boolean_max_pardons_pct_in_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = true\n')

        with pytest.raises(ValueError, match='max-pardons-pct'):
            load_config(tmp_path)

    def it_rejects_negative_max_pardons_pct_in_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = -1.0\n')

        with pytest.raises(ValueError, match='max-pardons-pct'):
            load_config(tmp_path)

    def it_rejects_max_pardons_pct_above_100_in_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = 101.0\n')

        with pytest.raises(ValueError, match='max-pardons-pct'):
            load_config(tmp_path)

    def it_reads_integer_max_pardons_pct_from_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax-pardons-pct = 5\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.max_pardons_pct == 5

    def it_rejects_out_of_range_max_pardons_pct_via_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_pytest_config: Callable[..., Any]
    ) -> None:
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(make_pytest_config(tmp_path, gremlin_max_pardons_pct=150.0))  # type: ignore[arg-type]

        mock_pytest.exit.assert_called_once()
        assert mock_pytest.exit.call_args.kwargs.get('returncode') == 4
