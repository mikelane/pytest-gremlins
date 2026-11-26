"""Adversarial QA findings for the terminal-notice handler (issue #982).

Each test here failed against e42f7da. They pin behavior the notice handler must not break: warnings that
were already visible stay visible, the handler is removed with its session, and one session never receives
another session's notices.
"""

from __future__ import annotations

import logging

import pytest

from pytest_gremlins.notices import (
    PACKAGE_LOGGER_NAME,
    TerminalNoticeHandler,
)
from pytest_gremlins.plugin import _session_for

TARGET = 'def add(a, b):\n    return a + b\n'
FAST_TEST = (
    'import pytest\nfrom target import add\n\n\n@pytest.mark.small\ndef test_add():\n    assert add(1, 2) == 3\n'
)


def _notice_handlers() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger(PACKAGE_LOGGER_NAME).handlers
        if isinstance(handler, TerminalNoticeHandler)
    ]


@pytest.mark.medium
class DescribeWarningsThatWereVisibleBeforeTheNoticeHandler:
    """An unmarked warning that reached stderr through logging's last-resort handler still reaches it."""

    def it_prints_the_no_source_paths_warning_raised_during_configure(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makepyfile(target=TARGET, test_target=FAST_TEST)

        result = pytester.runpytest_subprocess('--gremlins', '-p', 'no:cacheprovider')

        assert 'No source paths discovered; scanning the entire project root' in result.stderr.str()

    def it_prints_an_unmarked_runtime_warning_when_the_logging_plugin_is_disabled(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makepyfile(target=TARGET, test_target=FAST_TEST)

        result = pytester.runpytest_subprocess('--gremlins', '-p', 'no:logging', '-p', 'no:cacheprovider')

        assert 'No source paths discovered; scanning the entire project root' in result.stderr.str()


@pytest.mark.medium
class DescribeNoticeHandlerLifecycle:
    """The handler lives exactly as long as the session it feeds."""

    def it_leaves_no_notice_handler_behind_after_an_inline_gremlins_run(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makepyfile(target=TARGET, test_target=FAST_TEST)
        handlers_before = len(_notice_handlers())

        pytester.inline_run('--gremlins', '--gremlin-targets=target.py', '--collect-only', '-p', 'no:cacheprovider')

        assert len(_notice_handlers()) == handlers_before

    def it_does_not_queue_an_inner_run_notice_on_the_outer_session(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makepyfile(
            target='def add(a, b):\n    return a + b  # gremlin: pardon[no-such-code] because\n',
            test_target=FAST_TEST,
        )
        outer_session = _session_for(request.config)
        assert outer_session is not None
        outer_notices_before = list(outer_session.terminal_notices)

        pytester.inline_run('--gremlins', '--gremlin-targets=target.py', '-p', 'no:cacheprovider')

        assert outer_session.terminal_notices == outer_notices_before
