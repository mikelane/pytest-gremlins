"""The batch/parallel start-up line must not call unrunnable or pardoned gremlins cache hits (issue #571 follow-up)."""

from __future__ import annotations

import pytest

from pytest_gremlins.plugin import _format_cache_report


@pytest.mark.small
class DescribeFormatCacheReport:
    def it_reports_cache_hits_and_gremlins_left_to_test(self) -> None:
        assert _format_cache_report(cache_hits=3, settled_without_running=0, to_test=2) == (
            'pytest-gremlins: 3 gremlins from cache, 2 to test'
        )

    def it_does_not_call_gremlins_settled_without_running_cache_hits(self) -> None:
        assert _format_cache_report(cache_hits=0, settled_without_running=4, to_test=0) == (
            'pytest-gremlins: 0 gremlins from cache, 4 settled without running, 0 to test'
        )

    def it_reports_all_three_counts_when_they_are_mixed(self) -> None:
        assert _format_cache_report(cache_hits=2, settled_without_running=1, to_test=5) == (
            'pytest-gremlins: 2 gremlins from cache, 1 settled without running, 5 to test'
        )
