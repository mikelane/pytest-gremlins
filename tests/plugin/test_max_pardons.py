"""Tests for --max-pardons=N absolute pardon count ceiling."""

from __future__ import annotations

import logging
from pathlib import Path
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
class DescribeMaxPardons:
    """GremlinSession.max_pardons field and enforcement."""

    def it_defaults_to_none(self) -> None:
        session = GremlinSession()

        assert session.max_pardons is None

    def it_accepts_an_int_value(self) -> None:
        session = GremlinSession(max_pardons=5)

        assert session.max_pardons == 5

    def it_accepts_zero(self) -> None:
        session = GremlinSession(max_pardons=0)

        assert session.max_pardons == 0

    def it_registers_cli_flag(self) -> None:
        mock_group = MagicMock(spec=OptionGroup)
        mock_parser = MagicMock(spec=Parser)
        mock_parser.getgroup.return_value = mock_group

        pytest_addoption(mock_parser)

        added_options = {c.args[0]: c.kwargs for c in mock_group.addoption.call_args_list if c.args}
        assert '--max-pardons' in added_options
        opt_kwargs = added_options['--max-pardons']
        assert opt_kwargs.get('type') is int
        assert opt_kwargs.get('default') is None

    def it_no_exit_when_max_pardons_is_none(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons=None)
        score = MutationScore(total=10, zapped=5, survived=3, timeout=0, error=0, pardoned=2, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_not_called()

    def it_no_exit_when_pardoned_within_limit(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons=5)
        # 2 pardoned — within limit of 5
        score = MutationScore(total=10, zapped=8, survived=0, timeout=0, error=0, pardoned=2, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_not_called()

    def it_no_exit_when_pardoned_equals_limit(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons=5)
        # exactly at limit — not exceeding
        score = MutationScore(total=10, zapped=5, survived=0, timeout=0, error=0, pardoned=5, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_not_called()

    def it_exits_when_pardoned_exceeds_limit(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons=5)
        # 7 pardoned — exceeds limit of 5
        score = MutationScore(total=10, zapped=3, survived=0, timeout=0, error=0, pardoned=7, results=())
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
        assert '7' in exit_message
        assert '5' in exit_message
        assert '--max-pardons' in exit_message

    def it_exits_when_pardoned_exceeds_zero_limit(self) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons=0)
        # 1 pardoned — exceeds 0 limit
        score = MutationScore(total=5, zapped=4, survived=0, timeout=0, error=0, pardoned=1, results=())
        mock_reporter = MagicMock(spec=TerminalReporter)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=session),
            patch('pytest_gremlins.plugin.MutationScore.from_results', return_value=score),
            patch('pytest_gremlins.plugin.pytest') as mock_pytest,
        ):
            pytest_terminal_summary(mock_reporter, exitstatus=0, config=MagicMock())  # dynamic attrs; bare-mock: ok

        mock_pytest.exit.assert_called_once()

    def it_cli_value_overrides_toml_value(self) -> None:
        file_config = GremlinConfig(max_pardons=2)

        merged = merge_configs(file_config, cli_max_pardons=10)

        assert merged.max_pardons == 10

    def it_uses_toml_value_when_cli_is_none(self) -> None:
        file_config = GremlinConfig(max_pardons=3)

        merged = merge_configs(file_config, cli_max_pardons=None)

        assert merged.max_pardons == 3

    def it_logs_info_when_pardoned_within_limit(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons=5)
        # 2 pardoned — within limit of 5
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
        assert '2' in info_records[0].message
        assert '5' in info_records[0].message

    def it_logs_warning_when_pardoned_exceeds_limit(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_gremlin = MagicMock()  # opaque filler: attrs never accessed (from_results is patched); bare-mock: ok
        session = GremlinSession(enabled=True, gremlins=[mock_gremlin], max_pardons=5)
        score = MutationScore(total=10, zapped=3, survived=0, timeout=0, error=0, pardoned=7, results=())
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
        assert '7' in caplog.records[0].message
        assert '5' in caplog.records[0].message


@pytest.mark.medium
class DescribeMaxPardonsFileIO:
    """GremlinSession.max_pardons — tests that read/write real pyproject.toml files."""

    def it_reads_max_pardons_from_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax_pardons = 5\n')

        loaded_config = load_config(tmp_path)

        assert loaded_config.max_pardons == 5

    def it_toml_max_pardons_flows_into_session(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_pytest_config: object,
    ) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax_pardons = 4\n')

        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        config = make_pytest_config(tmp_path)  # type: ignore[operator]

        pytest_configure(config)  # type: ignore[arg-type]

        session = plugin._get_session()
        assert session is not None
        assert session.max_pardons == 4

    def it_rejects_negative_max_pardons_in_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax_pardons = -1\n')

        with pytest.raises(ValueError, match='max_pardons'):
            load_config(tmp_path)

    def it_rejects_non_integer_max_pardons_in_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax_pardons = "five"\n')

        with pytest.raises(ValueError, match='max_pardons'):
            load_config(tmp_path)

    def it_rejects_float_max_pardons_in_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax_pardons = 2.5\n')

        with pytest.raises(ValueError, match='max_pardons'):
            load_config(tmp_path)

    def it_rejects_boolean_max_pardons_in_toml(self, tmp_path: Path) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax_pardons = true\n')

        with pytest.raises(ValueError, match='max_pardons'):
            load_config(tmp_path)

    def it_logs_warning_on_invalid_max_pardons_type(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax_pardons = "five"\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='max_pardons'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'max_pardons' in caplog.records[0].message

    def it_logs_warning_on_negative_max_pardons(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text('[tool.pytest-gremlins]\nmax_pardons = -1\n')

        with (
            caplog.at_level(logging.WARNING, logger='pytest_gremlins.config'),
            pytest.raises(ValueError, match='max_pardons'),
        ):
            load_config(tmp_path)

        assert len(caplog.records) == 1
        assert 'max_pardons' in caplog.records[0].message

    def it_rejects_out_of_range_max_pardons_via_cli(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_pytest_config: object,
    ) -> None:
        monkeypatch.setattr('pytest_gremlins.plugin._gremlin_session', None)

        config = make_pytest_config(tmp_path, max_pardons=-1)  # type: ignore[operator]

        with patch('pytest_gremlins.plugin.pytest') as mock_pytest:
            pytest_configure(config)  # type: ignore[arg-type]

        mock_pytest.exit.assert_called_once()
        assert mock_pytest.exit.call_args.kwargs.get('returncode') == 4
