"""Tests for the actionable error message when no gremlins are found.

When no gremlins are found, the terminal summary tells the user where
we looked and how to configure paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.plugin import GremlinSession


@pytest.mark.small
class TestNoGremlinsMessage:
    """Tests for actionable error message in terminal summary."""

    def _run_terminal_summary(self, session: GremlinSession) -> list[str]:
        """Run pytest_terminal_summary and capture written lines."""
        lines: list[str] = []

        mock_reporter = MagicMock()
        mock_reporter.write_line = lambda text='': lines.append(text)
        mock_reporter.write_sep = lambda char, text: lines.append(f'{char} {text}')

        mock_config = MagicMock()

        plugin._set_session(session)
        plugin.pytest_terminal_summary(mock_reporter, 0, mock_config)

        return lines

    def test_message_lists_searched_paths(self) -> None:
        """Error message includes the paths that were searched."""
        session = GremlinSession(
            enabled=True,
            target_paths=[Path('/project/src'), Path('/project/lib')],
        )

        lines = self._run_terminal_summary(session)
        output = '\n'.join(lines)

        assert '/project/src' in output
        assert '/project/lib' in output

    def test_message_suggests_config_when_no_paths(self) -> None:
        """Error message suggests configuring paths when no paths were found."""
        session = GremlinSession(
            enabled=True,
            target_paths=[],
        )

        lines = self._run_terminal_summary(session)
        output = '\n'.join(lines)

        assert '[tool.pytest-gremlins]' in output
        assert 'paths' in output

    def test_message_differs_for_searched_paths_vs_no_paths(self) -> None:
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
