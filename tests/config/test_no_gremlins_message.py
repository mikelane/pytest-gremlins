"""Tests for the actionable error message when no gremlins are found.

When no gremlins are found, the terminal summary tells the user where
we looked and how to configure paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import (
    MagicMock,
    patch,
)

from _pytest.terminal import TerminalReporter
import pytest

from pytest_gremlins import plugin
from pytest_gremlins.plugin import GremlinSession
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)


@pytest.mark.small
class DescribeNoGremlinsMessage:
    """Tests for actionable error message in terminal summary."""

    def _run_terminal_summary(self, session: GremlinSession) -> list[str]:
        """Run pytest_terminal_summary and capture written lines."""
        lines: list[str] = []

        mock_reporter = MagicMock(spec=TerminalReporter)
        mock_reporter.write_line = lambda text='': lines.append(text)
        mock_reporter.write_sep = lambda char, text: lines.append(f'{char} {text}')

        mock_config = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok

        plugin._set_session(session)
        plugin.pytest_terminal_summary(mock_reporter, 0, mock_config)

        return lines

    def it_message_lists_searched_paths(self) -> None:
        """Error message includes the paths that were searched."""
        session = GremlinSession(
            enabled=True,
            target_paths=[Path('/project/src'), Path('/project/lib')],
        )

        lines = self._run_terminal_summary(session)
        output = '\n'.join(lines)

        assert str(Path('/project/src')) in output
        assert str(Path('/project/lib')) in output

    def it_message_suggests_config_when_no_paths(self) -> None:
        """Error message suggests configuring paths when no paths were found."""
        session = GremlinSession(
            enabled=True,
            target_paths=[],
        )

        lines = self._run_terminal_summary(session)
        output = '\n'.join(lines)

        assert '[tool.pytest-gremlins]' in output
        assert 'paths' in output

    def it_shows_discovery_chain_in_no_paths_message(self) -> None:
        """Error message lists the full discovery chain when no paths found."""
        session = GremlinSession(
            enabled=True,
            target_paths=[],
        )

        lines = self._run_terminal_summary(session)
        output = '\n'.join(lines)

        assert '--gremlin-targets' in output
        assert '[tool.pytest-gremlins]' in output
        assert '[tool.setuptools]' in output
        assert 'src/' in output

    def it_shows_numbered_steps_in_no_paths_message(self) -> None:
        """Error message presents discovery chain as numbered steps."""
        session = GremlinSession(
            enabled=True,
            target_paths=[],
        )

        lines = self._run_terminal_summary(session)
        output = '\n'.join(lines)

        assert '1.' in output
        assert '2.' in output
        assert '3.' in output
        assert '4.' in output

    def it_suggests_gremlin_targets_flag_in_no_paths_message(self) -> None:
        """Error message tells user how to specify targets explicitly."""
        session = GremlinSession(
            enabled=True,
            target_paths=[],
        )

        lines = self._run_terminal_summary(session)
        output = '\n'.join(lines)

        assert 'pytest --gremlins --gremlin-targets=' in output

    def it_message_differs_for_searched_paths_vs_no_paths(self) -> None:
        """Message with searched paths differs from message with no paths."""
        session_with_paths = GremlinSession(
            enabled=True,
            target_paths=[Path('/project/src')],
        )
        session_no_paths = GremlinSession(
            enabled=True,
            target_paths=[],
        )

        lines_with = self._run_terminal_summary(session_with_paths)
        lines_without = self._run_terminal_summary(session_no_paths)

        assert lines_with != lines_without


def _make_gremlin_result(status: GremlinResultStatus) -> GremlinResult:
    """Build a GremlinResult with a mock Gremlin for terminal summary tests."""
    mock_gremlin = MagicMock()  # Gremlin is a frozen dataclass; spec= misses instance fields; bare-mock: ok
    mock_gremlin.file_path = 'src/module.py'
    mock_gremlin.line_number = 42
    mock_gremlin.description = 'replaced + with -'
    mock_gremlin.operator_name = 'ArithmeticOperator'
    return GremlinResult(gremlin=mock_gremlin, status=status)


@pytest.mark.small
class DescribeMutationResultsReport:
    """Tests for the results display section of pytest_terminal_summary (lines 1832-1881).

    All tests supply a non-empty gremlins list so the no-gremlins early-return
    is bypassed and the results display path is exercised.
    """

    def _run_terminal_summary(self, session: GremlinSession) -> list[str]:
        """Run pytest_terminal_summary and capture written lines."""
        lines: list[str] = []
        mock_reporter = MagicMock(spec=TerminalReporter)
        mock_reporter.write_line = lambda text='': lines.append(text)
        mock_reporter.write_sep = lambda char, text: lines.append(f'{char} {text}')
        mock_config = MagicMock()  # pytest.Config sets attrs dynamically; bare-mock: ok
        plugin._set_session(session)
        plugin.pytest_terminal_summary(mock_reporter, 0, mock_config)
        return lines

    def it_shows_no_gremlins_tested_when_results_empty(self) -> None:
        """When results list is empty (total=0), 'No gremlins tested.' appears."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[],
        )

        lines = self._run_terminal_summary(gs)
        output = '\n'.join(lines)

        assert 'No gremlins tested.' in output

    def it_shows_zapped_and_survived_counts(self) -> None:
        """Zapped and survived gremlins produce count lines in the report."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[
                _make_gremlin_result(GremlinResultStatus.ZAPPED),
                _make_gremlin_result(GremlinResultStatus.SURVIVED),
            ],
        )

        lines = self._run_terminal_summary(gs)
        output = '\n'.join(lines)

        assert 'Zapped: 1 gremlins' in output
        assert 'Survived: 1 gremlins' in output

    def it_shows_timeout_line_when_timeouts_present(self) -> None:
        """A 'Timeout:' line appears only when at least one timeout result exists."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.TIMEOUT)],
        )

        lines = self._run_terminal_summary(gs)
        output = '\n'.join(lines)

        assert 'Timeout: 1 gremlins' in output

    def it_shows_error_line_when_errors_present(self) -> None:
        """An 'Error:' line appears only when at least one error result exists."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.ERROR)],
        )

        lines = self._run_terminal_summary(gs)
        output = '\n'.join(lines)

        assert 'Error: 1 gremlins' in output

    def it_shows_cache_stats_when_cache_enabled_with_hits(self) -> None:
        """Cache hit/miss statistics appear when cache_enabled and total cache activity > 0."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.ZAPPED)],
            cache_enabled=True,
            cache_hits=3,
            cache_misses=1,
        )

        lines = self._run_terminal_summary(gs)
        output = '\n'.join(lines)

        assert 'Cache: 3 hits' in output
        assert '1 misses' in output

    def it_omits_cache_stats_when_cache_disabled(self) -> None:
        """Cache stats do not appear when cache_enabled is False."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.ZAPPED)],
            cache_enabled=False,
        )

        lines = self._run_terminal_summary(gs)
        output = '\n'.join(lines)

        assert 'Cache:' not in output

    def it_shows_top_surviving_gremlins_section(self) -> None:
        """Survivors section appears when at least one gremlin survived."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.SURVIVED)],
        )

        lines = self._run_terminal_summary(gs)
        output = '\n'.join(lines)

        assert 'Top surviving gremlins:' in output
        assert 'src/module.py:42' in output

    def it_shows_html_report_hint_when_format_is_console(self) -> None:
        """Console report format includes a hint to use --gremlin-report=html."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.ZAPPED)],
            report_formats=['console'],
        )

        lines = self._run_terminal_summary(gs)
        output = '\n'.join(lines)

        assert '--gremlin-report=html' in output

    def it_writes_html_report_when_format_is_html(self) -> None:
        """When report_formats=['html'], the HTML report is written and its path displayed."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.ZAPPED)],
            report_formats=['html'],
        )

        with patch(
            'pytest_gremlins.plugin._write_html_report',
            return_value=Path('gremlin-report.html'),
        ) as mock_write_html:
            lines = self._run_terminal_summary(gs)

        output = '\n'.join(lines)
        mock_write_html.assert_called_once()
        assert 'HTML report written to:' in output

    def it_writes_json_report_when_format_is_json(self) -> None:
        """When report_formats=['json'], the JSON report is written and its path displayed."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.ZAPPED)],
            report_formats=['json'],
        )

        with patch(
            'pytest_gremlins.plugin._write_json_report',
            return_value=Path('gremlins.json'),
        ) as mock_write_json:
            lines = self._run_terminal_summary(gs)

        output = '\n'.join(lines)
        mock_write_json.assert_called_once()
        assert 'JSON report written to:' in output

    def it_writes_both_html_and_json_when_both_requested(self) -> None:
        """When report_formats=['html', 'json'], both reports are written."""
        gs = GremlinSession(
            enabled=True,
            gremlins=[MagicMock()],  # opaque filler: attrs never accessed; bare-mock: ok
            results=[_make_gremlin_result(GremlinResultStatus.ZAPPED)],
            report_formats=['html', 'json'],
        )

        with (
            patch(
                'pytest_gremlins.plugin._write_html_report',
                return_value=Path('gremlin-report.html'),
            ) as mock_write_html,
            patch(
                'pytest_gremlins.plugin._write_json_report',
                return_value=Path('gremlins.json'),
            ) as mock_write_json,
        ):
            lines = self._run_terminal_summary(gs)

        output = '\n'.join(lines)
        mock_write_html.assert_called_once()
        mock_write_json.assert_called_once()
        assert 'HTML report written to:' in output
        assert 'JSON report written to:' in output
