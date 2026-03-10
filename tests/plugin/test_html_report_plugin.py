"""Tests for Epic A: HTML report output path wiring in the plugin.

References: #155, #156, #157
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.plugin import _write_html_report
from pytest_gremlins.reporting.score import MutationScore


def _empty_score() -> MutationScore:
    return MutationScore.from_results([])


@pytest.mark.medium
class DescribeWriteHtmlReportDefaultOutputPath:
    """_write_html_report writes to coverage/gremlins/index.html by default.

    References: #155, #156
    """

    def it_writes_to_coverage_gremlins_index_html_by_default(self, tmp_path: Path):
        # The old hardcoded path was rootdir/gremlin-report.html.
        # This test fails if that path is still used.
        score = _empty_score()

        result_path = _write_html_report(score, rootdir=tmp_path, html_dir=None)

        assert result_path == tmp_path / 'coverage' / 'gremlins' / 'index.html'
        assert result_path.exists()

    def it_creates_coverage_gremlins_directory_automatically(self, tmp_path: Path):
        # The directory does not exist before the call.
        # Fails if mkdir is absent.
        score = _empty_score()
        expected_dir = tmp_path / 'coverage' / 'gremlins'
        assert not expected_dir.exists()

        _write_html_report(score, rootdir=tmp_path, html_dir=None)

        assert expected_dir.is_dir()

    def it_does_not_write_to_the_old_gremlin_report_html_path(self, tmp_path: Path):
        # Regression guard: old path must not exist after a default run.
        score = _empty_score()

        _write_html_report(score, rootdir=tmp_path, html_dir=None)

        assert not (tmp_path / 'gremlin-report.html').exists()


@pytest.mark.medium
class DescribeWriteHtmlReportCustomDir:
    """_write_html_report respects a custom html_dir argument.

    References: #156, #157
    """

    def it_writes_to_custom_dir_slash_index_html_when_html_dir_given(self, tmp_path: Path):
        score = _empty_score()
        custom = tmp_path / 'my-reports'

        result_path = _write_html_report(score, rootdir=tmp_path, html_dir=custom)

        assert result_path == custom / 'index.html'
        assert result_path.exists()

    def it_does_not_write_under_coverage_gremlins_when_custom_dir_given(self, tmp_path: Path):
        # When html_dir is provided, the report must NOT land in coverage/gremlins/.
        score = _empty_score()
        custom = tmp_path / 'out'

        _write_html_report(score, rootdir=tmp_path, html_dir=custom)

        assert not (tmp_path / 'coverage' / 'gremlins' / 'index.html').exists()


@pytest.mark.small
class DescribeGremlinsHtmlDirOption:
    """--gremlins-html-dir CLI option is registered in pytest_addoption.

    References: #157
    """

    def it_registers_gremlins_html_dir_option(self):
        # Call pytest_addoption with a real Parser and parse a CLI value to prove
        # the option is registered (parse_known_args raises SystemExit if unrecognised).
        # pytest.Parser() is a private class; suppress its deprecation warning since
        # testing option registration is a legitimate use of the internal API here.
        with pytest.warns(pytest.PytestDeprecationWarning):
            parser = pytest.Parser()
        plugin.pytest_addoption(parser)

        namespace, _ = parser.optparser.parse_known_args(['--gremlins-html-dir', '/project/reports'])

        assert namespace.gremlins_html_dir == '/project/reports'

    def it_stores_option_under_gremlins_html_dir_dest(self):
        # The dest must be gremlins_html_dir so config.getoption('gremlins_html_dir') works.
        # Parsing without the flag must yield None (the declared default).
        with pytest.warns(pytest.PytestDeprecationWarning):
            parser = pytest.Parser()
        plugin.pytest_addoption(parser)

        namespace, _ = parser.optparser.parse_known_args([])

        assert namespace.gremlins_html_dir is None
