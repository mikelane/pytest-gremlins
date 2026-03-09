"""Tests for the HTML reporter."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
import re

import pytest

from pytest_gremlins.reporting.diff import _node_to_source
from pytest_gremlins.reporting.html import (
    HtmlReporter,
    _build_operator_data,
    append_history_entry,
    load_history,
    resolve_html_output_path,
)
from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore


def _extract_canvas_tag(html: str, canvas_id: str) -> str:
    """Extract the full <canvas ...>...</canvas> tag for the given id."""
    pattern = rf'<canvas\s[^>]*id="{canvas_id}"[^>]*>.*?</canvas>'
    match = re.search(pattern, html, re.DOTALL)
    assert match is not None, f'No <canvas id="{canvas_id}"> found in HTML'
    return match.group(0)


@pytest.mark.small
class DescribeHtmlReporterBasicStructure:
    """Tests for basic HTML structure."""

    def it_produces_valid_html(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<!DOCTYPE html>' in html
        assert '<html' in html
        assert '</html>' in html

    def it_includes_head_section(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<head>' in html
        assert '</head>' in html
        assert '<title>' in html

    def it_includes_body_section(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<body>' in html
        assert '</body>' in html

    def it_includes_embedded_styles(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<style>' in html


@pytest.mark.small
class DescribeHtmlReporterContent:
    """Tests for HTML content."""

    def it_includes_title(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'pytest-gremlins' in html.lower()
        assert 'mutation' in html.lower()

    def it_includes_summary_stats(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '50' in html  # 50% score
        assert 'zapped' in html.lower()

    def it_includes_results_table(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, file_path='auth.py', line_number=42),
            make_result(GremlinResultStatus.SURVIVED, file_path='utils.py', line_number=17),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'auth.py' in html
        assert 'utils.py' in html
        assert '42' in html
        assert '17' in html

    def it_highlights_survived_gremlins(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have some visual distinction for survived
        assert 'survived' in html.lower()


@pytest.mark.medium
class DescribeHtmlReporterFileOutput:
    """Tests for writing HTML to file."""

    def it_writes_to_file(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        output_file = tmp_path / 'report.html'

        reporter.write_report(score, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert '<!DOCTYPE html>' in content


@pytest.mark.small
class DescribeHtmlReporterEmpty:
    """Tests for handling empty results."""

    def it_produces_valid_html_with_zero_indicator_for_empty_results(self):
        score = MutationScore.from_results([])
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<!DOCTYPE html>' in html
        # Must indicate no results rather than crash
        assert 'No gremlins tested' in html


@pytest.mark.small
class DescribeHtmlReporterAllOutcomeCategories:
    """Tests for displaying all mutation outcome categories in HTML."""

    def it_displays_timeout_card_when_timeouts_present(self, make_result):
        """It displays a timeout stat card when there are timeout results."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.TIMEOUT),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have timeout card with count
        assert 'stat-timeout' in html
        assert 'Timeout' in html
        assert '>2<' in html  # 2 timeouts

    def it_displays_error_card_when_errors_present(self, make_result):
        """It displays an error stat card when there are error results."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ERROR),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have error card with count
        assert 'stat-error' in html
        assert 'Error' in html
        assert '>1<' in html  # 1 error

    def it_omits_timeout_card_when_no_timeouts(self, make_result):
        """It omits the timeout card when there are no timeout results."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.ERROR),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should not have timeout card
        assert 'stat-timeout' not in html
        # But should have zapped, survived, and error
        assert 'stat-zapped' in html
        assert 'stat-survived' in html
        assert 'stat-error' in html

    def it_omits_error_card_when_no_errors(self, make_result):
        """It omits the error card when there are no error results."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.TIMEOUT),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should not have error card
        assert 'stat-error' not in html
        # But should have zapped, survived, and timeout
        assert 'stat-zapped' in html
        assert 'stat-survived' in html
        assert 'stat-timeout' in html

    def it_displays_all_four_outcome_cards_when_mixed_results(self, make_result):
        """It displays all four stat cards (zapped, survived, timeout, error) when all outcomes present."""
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.TIMEOUT),
            make_result(GremlinResultStatus.ERROR),
        ]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        # Should have all four stat cards
        assert 'stat-zapped' in html
        assert 'stat-survived' in html
        assert 'stat-timeout' in html
        assert 'stat-error' in html
        # Verify counts
        assert '>2<' in html  # 2 zapped
        assert '>1<' in html  # 1 survived, 1 timeout, 1 error


@pytest.mark.medium
class DescribeHtmlReporterOutputLocation:
    """Tests for Epic A: write_report creates parent directories automatically.

    References: #155, #157
    """

    def it_creates_nested_parent_directories_before_writing(self, make_result, tmp_path: Path):
        # write_text without mkdir raises FileNotFoundError for missing parents.
        # This test fails if mkdir(parents=True) is absent from write_report.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        nested = tmp_path / 'coverage' / 'gremlins' / 'index.html'

        reporter.write_report(score, nested)

        assert nested.exists()
        assert '<!DOCTYPE html>' in nested.read_text()

    def it_writes_to_the_exact_nested_path_not_a_sibling(self, make_result, tmp_path: Path):
        # Hardcoding 'gremlin-report.html' next to rootdir would fail this assertion.
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        exact = tmp_path / 'deep' / 'nested' / 'index.html'

        reporter.write_report(score, exact)

        assert exact.exists()
        assert not (tmp_path / 'deep' / 'nested.html').exists()
        assert not (tmp_path / 'index.html').exists()

    def it_succeeds_when_parent_directory_already_exists(self, make_result, tmp_path: Path):
        # exist_ok=True must be set; without it a second mkdir raises FileExistsError.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()
        output = tmp_path / 'coverage' / 'gremlins' / 'index.html'
        output.parent.mkdir(parents=True, exist_ok=True)

        reporter.write_report(score, output)  # must not raise

        assert output.exists()


@pytest.mark.small
class DescribeResolveHtmlOutputPath:
    """Tests for Epic A: resolve_html_output_path pure function.

    References: #155, #156
    """

    def it_returns_coverage_gremlins_index_when_no_custom_dir(self, tmp_path: Path):
        resolved_path = resolve_html_output_path(rootdir=tmp_path, html_dir=None)

        # Must be exactly <rootdir>/coverage/gremlins/index.html, not rootdir/gremlin-report.html.
        assert resolved_path == tmp_path / 'coverage' / 'gremlins' / 'index.html'

    def it_returns_custom_dir_slash_index_when_html_dir_provided(self, tmp_path: Path):
        custom = tmp_path / 'my-reports'
        resolved_path = resolve_html_output_path(rootdir=tmp_path, html_dir=custom)

        # Must append index.html to the custom dir, not the default subpath.
        assert resolved_path == custom / 'index.html'

    def it_does_not_embed_coverage_gremlins_when_custom_dir_given(self, tmp_path: Path):
        custom = tmp_path / 'out'
        resolved_path = resolve_html_output_path(rootdir=tmp_path, html_dir=custom)

        # A naïve impl that always appends coverage/gremlins would fail here.
        assert 'coverage' not in resolved_path.parts
        assert 'gremlins' not in resolved_path.parts

    def it_uses_rootdir_not_cwd_for_default_path(self, tmp_path: Path):
        different_rootdir = tmp_path / 'project-root'
        resolved_path = resolve_html_output_path(rootdir=different_rootdir, html_dir=None)

        # The default path must be anchored at rootdir, not at tmp_path or cwd.
        assert resolved_path == different_rootdir / 'coverage' / 'gremlins' / 'index.html'
        assert resolved_path.is_relative_to(different_rootdir)

    def it_resolves_relative_html_dir_against_rootdir(self, tmp_path: Path):
        # When --gremlins-html-dir is passed as a relative path string (e.g. "reports"),
        # resolve_html_output_path must anchor it to rootdir, not to cwd.
        # A naïve impl that uses html_dir as-is would return a relative path like
        # 'reports/index.html' instead of '<rootdir>/reports/index.html'.
        relative_html_dir = Path('reports')  # simulates Path(config.getoption(...)) for a relative CLI value

        resolved_path = resolve_html_output_path(rootdir=tmp_path, html_dir=relative_html_dir)

        assert resolved_path.is_absolute()
        assert resolved_path == tmp_path / 'reports' / 'index.html'


@pytest.mark.small
class DescribeHtmlReporterDarkMode:
    """Tests for Epic B: dark-mode-by-default via CSS custom properties.

    References: #159, #160
    """

    def it_sets_data_theme_dark_on_html_element(self, make_result):
        # Light fallback would use no data-theme; dark default requires the attribute.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'data-theme="dark"' in html

    def it_defines_css_custom_properties_for_theming(self, make_result):
        # Old impl used raw hex values; new impl must use --var-name tokens.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert '--' in html  # at least one CSS custom property defined
        assert 'var(--' in html  # at least one CSS custom property consumed

    def it_includes_gremlin_green_primary_colour(self, make_result):
        # The gremlin-green palette anchors at #2e7d32 (primary).
        # Old grey palette would not contain this value.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert '#2e7d32' in html

    def it_includes_light_mode_css_block(self, make_result):
        # A data-theme toggle requires both dark and light variable sets.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert '[data-theme="light"]' in html


@pytest.mark.small
class DescribeHtmlReporterFonts:
    """Tests for Epic B: Inter body font and JetBrains Mono code font.

    References: #160
    """

    def it_imports_inter_font(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'Inter' in html

    def it_imports_jetbrains_mono_font(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'JetBrains Mono' in html


@pytest.mark.small
class DescribeHtmlReporterThemeToggle:
    """Tests for Epic B: light/dark mode toggle with localStorage persistence.

    References: #161
    """

    def it_includes_a_theme_toggle_button(self, make_result):
        # Must have a button element the user can click to switch theme.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert '<button' in html

    def it_persists_theme_via_localstorage(self, make_result):
        # The inline script must reference localStorage so preference survives reload.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'localStorage' in html

    def it_includes_inline_script_for_toggle(self, make_result):
        # The toggle must be self-contained (no external JS file needed).
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert '<script>' in html


@pytest.mark.small
class DescribeHtmlReporterResponsive:
    """Tests for Epic B: responsive viewport meta tag.

    References: #161
    """

    def it_includes_viewport_meta_tag(self, make_result):
        # Required for 375px mobile viewport to render without horizontal scroll.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'viewport' in html
        assert 'width=device-width' in html


@pytest.mark.small
class DescribeHtmlReporterCdnSecurity:
    """Tests for CDN security: pinned versions and SRI hashes.

    References: #217
    """

    def it_pins_chartjs_to_specific_version(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'chart.js@4.4.4' in html
        assert 'integrity="sha384-' in html

    def it_does_not_embed_google_fonts_import(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'fonts.googleapis.com' not in html


@pytest.mark.small
class DescribeHtmlReporterChartJs:
    """Tests for Epic C: Chart.js visualisations.

    References: #163, #164, #165
    """

    def it_loads_chartjs_from_cdn(self, make_result):
        # Charts require the Chart.js library; must be loaded via CDN script tag.
        # Checking the CDN domain is specific enough that a stub cannot fake it.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'chart.js' in html.lower()

    def it_includes_score_gauge_canvas(self, make_result):
        # The donut gauge must use a <canvas> element with id="scoreGauge".
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'scoreGauge' in html
        assert '<canvas' in html

    def it_includes_outcome_pie_canvas(self, make_result):
        # The outcome breakdown must use a <canvas> element with id="outcomeChart".
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'outcomeChart' in html

    def it_includes_per_file_bar_canvas(self, make_result):
        # Per-file scores must use a <canvas> element with id="fileChart".
        results = [
            make_result(GremlinResultStatus.ZAPPED, file_path='a.py'),
            make_result(GremlinResultStatus.SURVIVED, file_path='b.py'),
        ]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'fileChart' in html

    def it_includes_operator_distribution_canvas(self, make_result):
        # Operator breakdown must use a <canvas> element with id="operatorChart".
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'operatorChart' in html

    def it_embeds_file_scores_as_json_data(self, make_result):
        # File paths must appear inside a <script> block as JSON data for Chart.js,
        # not just in the HTML table rows. We verify they appear in a JSON array
        # context by checking for the quoted path adjacent to numeric score data.
        results = [
            make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py'),
            make_result(GremlinResultStatus.SURVIVED, file_path='src/utils.py'),
        ]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        # json.dumps produces the quoted form; it must appear inside a script block
        assert json.dumps('src/auth.py') in html
        assert json.dumps('src/utils.py') in html

    def it_omits_charts_when_no_gremlins_tested(self):
        # With zero results there is nothing to visualise; canvas elements must be absent.
        score = MutationScore.from_results([])

        html = HtmlReporter().to_html(score)

        assert 'scoreGauge' not in html
        assert 'outcomeChart' not in html


@pytest.mark.small
class DescribeHtmlReporterDiffPanels:
    """Tests for Epic D: collapsible diff panels for each result row.

    References: #167, #168, #169
    """

    def it_includes_details_element_for_each_result(self, make_result):
        # Each row needs a <details> element for expand/collapse behaviour.
        results = [
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
        ]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert html.count('<details>') == 2

    def it_includes_show_diff_summary_label(self, make_result):
        # The summary toggle must be labelled so users know what it reveals.
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'Show diff' in html

    def it_renders_original_source_in_mogwai_panel(self, make_result):
        # The left panel must show the original code labelled 'Mogwai'.
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'Mogwai' in html

    def it_renders_mutated_source_in_gremlin_panel(self, make_result):
        # The right panel header must be labelled 'Gremlin (mutated)' — the word
        # "Gremlin" alone is insufficient because the page title already contains it.
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'Gremlin (mutated)' in html

    def it_includes_expand_all_button(self, make_result):
        # A global control lets users expand every diff at once.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'expand' in html.lower()

    def it_includes_collapse_all_button(self, make_result):
        # A global control lets users collapse every diff at once.
        # The word 'collapse' alone is insufficient (CSS has border-collapse).
        # The button must invoke a JS function whose name contains 'collapse'.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'collapseAll' in html


@pytest.mark.medium
class DescribeAppendHistoryEntry:
    """Tests for Epic E: appending a history entry to history.json.

    References: #171, #172
    """

    def it_creates_history_json_when_absent(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        history_path = tmp_path / 'history.json'

        append_history_entry(rootdir=tmp_path, score=score, history_path=history_path)

        assert history_path.exists()

    def it_writes_score_and_timestamp_to_entry(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        history_path = tmp_path / 'history.json'

        append_history_entry(rootdir=tmp_path, score=score, history_path=history_path)

        entries = json.loads(history_path.read_text())
        assert len(entries) == 1
        assert 'timestamp' in entries[0]
        assert 'score' in entries[0]
        assert entries[0]['score'] == 100.0

    def it_appends_to_existing_entries(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        history_path = tmp_path / 'history.json'

        append_history_entry(rootdir=tmp_path, score=score, history_path=history_path)
        append_history_entry(rootdir=tmp_path, score=score, history_path=history_path)

        entries = json.loads(history_path.read_text())
        assert len(entries) == 2

    def it_caps_entries_at_history_limit(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        history_path = tmp_path / 'history.json'

        for _ in range(5):
            append_history_entry(rootdir=tmp_path, score=score, history_limit=3, history_path=history_path)

        entries = json.loads(history_path.read_text())
        assert len(entries) == 3

    def it_includes_by_file_breakdown_in_entry(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED, file_path='src/auth.py')]
        score = MutationScore.from_results(results)
        history_path = tmp_path / 'history.json'

        append_history_entry(rootdir=tmp_path, score=score, history_path=history_path)

        entries = json.loads(history_path.read_text())
        assert 'by_file' in entries[0]
        assert 'src/auth.py' in entries[0]['by_file']

    def it_includes_by_operator_breakdown_in_entry(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED, operator_name='comparison')]
        score = MutationScore.from_results(results)
        history_path = tmp_path / 'history.json'

        append_history_entry(rootdir=tmp_path, score=score, history_path=history_path)

        entries = json.loads(history_path.read_text())
        assert 'by_operator' in entries[0]
        assert 'comparison' in entries[0]['by_operator']


@pytest.mark.small
class DescribeHtmlReporterHistorySection:
    """Tests for Epic E: historical trend section rendered in the HTML report.

    References: #173
    """

    def it_renders_no_history_message_when_history_is_empty(self, make_result):
        score = MutationScore.from_results([make_result(GremlinResultStatus.ZAPPED)])

        html = HtmlReporter().to_html(score, history=[])

        assert 'No historical data' in html

    def it_renders_no_history_message_when_history_has_exactly_one_entry(self, make_result):
        # The JS chart requires >= 2 entries to draw. With only 1 entry the canvas
        # element is rendered but the chart is never initialised, producing a blank
        # section. The "no historical data" placeholder must appear instead.
        score = MutationScore.from_results([make_result(GremlinResultStatus.ZAPPED)])
        history = [
            {'timestamp': '2026-01-01T00:00:00+00:00', 'score': 80.0, 'by_file': {}, 'by_operator': {}},
        ]

        html = HtmlReporter().to_html(score, history=history)

        assert 'No historical data' in html
        assert '<canvas id="historyChart"' not in html

    def it_renders_history_canvas_when_two_or_more_entries_present(self, make_result):
        score = MutationScore.from_results([make_result(GremlinResultStatus.ZAPPED)])
        history = [
            {'timestamp': '2026-01-01T00:00:00+00:00', 'score': 80.0, 'by_file': {}, 'by_operator': {}},
            {'timestamp': '2026-01-02T00:00:00+00:00', 'score': 85.0, 'by_file': {}, 'by_operator': {}},
        ]

        html = HtmlReporter().to_html(score, history=history)

        assert 'historyChart' in html

    def it_embeds_history_data_as_json_in_canvas_attribute(self, make_result):
        score = MutationScore.from_results([make_result(GremlinResultStatus.ZAPPED)])
        history = [
            {'timestamp': '2026-01-01T00:00:00+00:00', 'score': 80.0, 'by_file': {}, 'by_operator': {}},
            {'timestamp': '2026-01-02T00:00:00+00:00', 'score': 85.0, 'by_file': {}, 'by_operator': {}},
        ]

        html = HtmlReporter().to_html(score, history=history)

        assert '2026-01-01' in html
        assert '80.0' in html

    def it_escapes_double_quotes_in_history_json_attribute(self, make_result):
        # json.dumps uses double-quote delimiters for all JSON keys and string values.
        # Embedding that unescaped inside a double-quoted HTML attribute produces:
        #   data-history="[{"timestamp": "…"}]"
        # An HTML parser stops at the second `"` — the attribute value becomes `[{`
        # and the JS JSON.parse silently fails, hiding the history chart entirely.
        # The fix: HTML-escape the JSON so `"` becomes `&quot;` inside the attribute.
        score = MutationScore.from_results([make_result(GremlinResultStatus.ZAPPED)])
        history = [
            {'timestamp': '2026-01-01T00:00:00+00:00', 'score': 80.0, 'by_file': {}, 'by_operator': {}},
            {'timestamp': '2026-01-02T00:00:00+00:00', 'score': 85.0, 'by_file': {}, 'by_operator': {}},
        ]

        html = HtmlReporter().to_html(score, history=history)

        # Raw double-quotes inside the attribute value break HTML parsing.
        assert 'data-history="[{"' not in html
        # The attribute must use &quot; so the JSON string delimiters are safe.
        assert '&quot;timestamp&quot;' in html

    def it_does_not_produce_malformed_html_when_file_path_contains_single_quote(self, make_result):
        # The history canvas originally embedded JSON in a single-quoted attribute:
        #   data-history='...'
        # A file path like "it's/file.py" produces a literal ' inside the JSON string.
        # That bare single quote terminates the attribute early, breaking HTML parsing
        # and causing JSON.parse in JS to silently fail.
        # Fix: use a double-quoted attribute (data-history="...") instead, since
        # json.dumps only uses double quotes for object/string delimiters and a
        # bare single quote in a value is harmless inside a double-quoted attribute.
        score = MutationScore.from_results([make_result(GremlinResultStatus.ZAPPED)])
        history = [
            {
                'timestamp': '2026-01-01T00:00:00+00:00',
                'score': 80.0,
                'by_file': {"it's/file.py": 80.0},
                'by_operator': {},
            },
            {'timestamp': '2026-01-02T00:00:00+00:00', 'score': 85.0, 'by_file': {}, 'by_operator': {}},
        ]

        html = HtmlReporter().to_html(score, history=history)

        # Canvas must be present (2 entries → chart renders).
        assert '<canvas id="historyChart"' in html
        # The attribute must use double-quote delimiters so the single quote is safe.
        assert 'data-history="' in html
        # The file path with its single quote must be present in the output (not dropped).
        assert "it's" in html


@pytest.mark.small
class DescribeHtmlReporterA11y:
    """Tests for WCAG-compliant accessibility in the HTML report.

    References: #214
    """

    def it_adds_role_img_to_score_gauge_canvas(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        canvas = _extract_canvas_tag(html, 'scoreGauge')
        assert 'role="img"' in canvas

    def it_adds_aria_label_to_score_gauge_canvas(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        canvas = _extract_canvas_tag(html, 'scoreGauge')
        assert 'aria-label="Mutation score gauge: 100%"' in canvas

    def it_adds_fallback_text_inside_score_gauge_canvas(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        canvas = _extract_canvas_tag(html, 'scoreGauge')
        assert 'Chart requires JavaScript' in canvas

    def it_adds_role_img_and_aria_label_to_outcome_chart_canvas(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        canvas = _extract_canvas_tag(html, 'outcomeChart')
        assert 'role="img"' in canvas
        assert 'aria-label="Outcome distribution pie chart"' in canvas

    def it_adds_role_img_and_aria_label_to_file_chart_canvas(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        canvas = _extract_canvas_tag(html, 'fileChart')
        assert 'role="img"' in canvas
        assert 'aria-label="Per-file mutation scores bar chart"' in canvas

    def it_restricts_theme_init_to_valid_values(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert "if (saved === 'dark' || saved === 'light')" in html

    def it_adds_role_img_and_aria_label_to_operator_chart_canvas(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        canvas = _extract_canvas_tag(html, 'operatorChart')
        assert 'role="img"' in canvas
        assert 'aria-label="Operator distribution bar chart"' in canvas

    def it_adds_role_img_and_aria_label_to_history_chart_canvas(self, make_result):
        score = MutationScore.from_results([make_result(GremlinResultStatus.ZAPPED)])
        history = [
            {'timestamp': '2026-01-01T00:00:00+00:00', 'score': 80.0, 'by_file': {}, 'by_operator': {}},
            {'timestamp': '2026-01-02T00:00:00+00:00', 'score': 85.0, 'by_file': {}, 'by_operator': {}},
        ]

        html = HtmlReporter().to_html(score, history=history)

        canvas = _extract_canvas_tag(html, 'historyChart')
        assert 'role="img"' in canvas
        assert 'aria-label="Historical mutation score trend"' in canvas

    def it_sets_3px_outline_with_offset_on_focus_visible(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        style_start = html.index('<style>')
        style_end = html.index('</style>')
        css = html[style_start:style_end]
        focus_rule_start = css.index(':focus-visible')
        focus_rule_end = css.index('}', focus_rule_start)
        focus_rule = css[focus_rule_start:focus_rule_end]
        assert 'outline: 3px solid' in focus_rule
        assert 'outline-offset: 2px' in focus_rule

    def it_adds_aria_pressed_true_to_theme_toggle_button_in_default_dark_mode(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        # The toggle button must have aria-pressed matching the default dark theme
        button_match = re.search(r'<button\s[^>]*class="theme-toggle"[^>]*>', html)
        assert button_match is not None, 'Theme toggle button not found'
        button_tag = button_match.group(0)
        assert 'aria-pressed="true"' in button_tag

    def it_sets_min_height_44px_on_expand_btn(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'min-height: 44px' in html

    def it_sets_min_width_44px_on_expand_btn(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert 'min-width: 44px' in html

    def it_wraps_main_content_in_main_landmark(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        assert '<main' in html
        assert '</main>' in html

    def it_disables_transitions_and_animations_when_prefers_reduced_motion(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        style_start = html.index('<style>')
        style_end = html.index('</style>')
        css = html[style_start:style_end]
        motion_start = css.index('prefers-reduced-motion')
        # Find the closing brace of the @media block (two levels: @media { * { } })
        inner_brace = css.index('}', motion_start)
        outer_brace = css.index('}', inner_brace + 1)
        motion_block = css[motion_start:outer_brace]
        assert 'transition: none !important' in motion_block
        assert 'animation: none !important' in motion_block

    def it_has_h2_before_first_h3_in_charts_section(self, make_result):
        # WCAG heading hierarchy: h3 inside chart cards requires a parent h2 section
        # heading to appear first. Without an h2 the hierarchy jumps h1 -> h3.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        html = HtmlReporter().to_html(score)

        h2_pos = html.find('<h2')
        h3_pos = html.find('<h3')
        # h3 elements exist in the chart section; there must be an h2 before them
        assert h3_pos != -1, 'Expected <h3> elements in chart cards'
        assert h2_pos != -1, 'Expected at least one <h2> section heading before <h3> chart titles'
        assert h2_pos < h3_pos

    def it_uses_a_defined_css_variable_for_focus_visible_outline(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        style_start = html.index('<style>')
        style_end = html.index('</style>')
        css = html[style_start:style_end]
        focus_rule_start = css.index(':focus-visible')
        focus_rule_end = css.index('}', focus_rule_start)
        focus_rule = css[focus_rule_start:focus_rule_end]
        assert 'var(--color-primary-light)' in focus_rule
        assert 'var(--accent)' not in focus_rule

    def it_updates_aria_pressed_when_toggling_to_dark_theme(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        script_start = html.index('function toggleTheme()')
        script_end = html.index('\n        }', script_start) + len('\n        }')
        toggle_fn = html[script_start:script_end]
        assert "btn.setAttribute('aria-pressed', 'true')" in toggle_fn

    def it_updates_aria_pressed_when_toggling_to_light_theme(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        script_start = html.index('function toggleTheme()')
        script_end = html.index('\n        }', script_start) + len('\n        }')
        toggle_fn = html[script_start:script_end]
        assert "btn.setAttribute('aria-pressed', 'false')" in toggle_fn

    def it_syncs_aria_pressed_with_restored_theme_on_page_load(self, make_result):
        # The theme init script runs in <head> before <body> is parsed.
        # document.querySelector('.theme-toggle') returns null in <head>.
        # aria-pressed sync must use DOMContentLoaded to defer until the button exists.
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        init_script_start = html.index('(function()')
        init_script_end = html.index('})();', init_script_start) + len('})();')
        init_script = html[init_script_start:init_script_end]
        assert 'DOMContentLoaded' in init_script
        assert "setAttribute('aria-pressed'" in init_script

    def it_includes_a_caption_in_the_results_table(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '<caption>Gremlin mutation testing results</caption>' in html

    def it_adds_scope_col_to_all_th_elements(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        table_start = html.index('<table>')
        table_end = html.index('</table>', table_start)
        table_html = html[table_start:table_end]
        th_count = table_html.count('<th>')
        scope_col_count = table_html.count('scope="col"')
        assert th_count == 0
        assert scope_col_count == 5


@pytest.mark.medium
class DescribeLoadHistory:
    """Tests for the load_history module-level function."""

    def it_returns_empty_list_when_file_is_missing(self, tmp_path: Path):
        loaded_entries = load_history(tmp_path / 'nonexistent.json')

        assert loaded_entries == []

    def it_returns_parsed_list_from_valid_json_file(self, tmp_path: Path):
        history_path = tmp_path / 'history.json'
        expected_entries = [
            {'timestamp': '2026-01-01T00:00:00+00:00', 'score': 80.0, 'by_file': {}, 'by_operator': {}},
            {'timestamp': '2026-01-02T00:00:00+00:00', 'score': 90.0, 'by_file': {}, 'by_operator': {}},
        ]
        history_path.write_text(json.dumps(expected_entries), encoding='utf-8')

        loaded_entries = load_history(history_path)

        assert loaded_entries == expected_entries

    def it_returns_empty_list_for_corrupt_json(self, tmp_path: Path):
        history_path = tmp_path / 'history.json'
        history_path.write_text('invalid json', encoding='utf-8')

        loaded_entries = load_history(history_path)

        assert loaded_entries == []

    def it_returns_empty_list_when_path_is_a_directory(self, tmp_path: Path):
        # Passing a directory where a file is expected raises OSError on read_text.
        loaded_entries = load_history(tmp_path)

        assert loaded_entries == []


@pytest.mark.small
class DescribeBuildOperatorData:
    """Tests for the _build_operator_data module-level function."""

    def it_returns_empty_dict_when_score_has_no_results(self):
        score = MutationScore.from_results([])

        operator_data = _build_operator_data(score)

        assert operator_data == {}

    def it_returns_correct_keys_and_values_for_single_operator(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, operator_name='comparison'),
            make_result(GremlinResultStatus.SURVIVED, operator_name='comparison'),
            make_result(GremlinResultStatus.ZAPPED, operator_name='comparison'),
        ]
        score = MutationScore.from_results(results)

        operator_data = _build_operator_data(score)

        assert operator_data == {'comparison': {'total': 3, 'survived': 1}}

    def it_returns_separate_entries_for_multiple_operators(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, operator_name='comparison'),
            make_result(GremlinResultStatus.SURVIVED, operator_name='arithmetic'),
            make_result(GremlinResultStatus.SURVIVED, operator_name='arithmetic'),
        ]
        score = MutationScore.from_results(results)

        operator_data = _build_operator_data(score)

        assert operator_data['comparison'] == {'total': 1, 'survived': 0}
        assert operator_data['arithmetic'] == {'total': 2, 'survived': 2}

    def it_counts_only_survived_status_as_survived(self, make_result):
        results = [
            make_result(GremlinResultStatus.ZAPPED, operator_name='comparison'),
            make_result(GremlinResultStatus.TIMEOUT, operator_name='comparison'),
            make_result(GremlinResultStatus.ERROR, operator_name='comparison'),
            make_result(GremlinResultStatus.SURVIVED, operator_name='comparison'),
        ]
        score = MutationScore.from_results(results)

        operator_data = _build_operator_data(score)

        assert operator_data['comparison'] == {'total': 4, 'survived': 1}


@pytest.mark.small
class DescribeNodeToSourceLogging:
    """Tests for logging in _node_to_source when AST unparsing fails."""

    def it_logs_warning_when_node_to_source_fails(self, caplog: pytest.LogCaptureFixture):
        # Build a minimal AST node then corrupt it so ast.unparse raises.
        node = ast.parse('x + 1', mode='eval').body
        # Remove the required attributes so ast.unparse raises an AttributeError.
        del node.left

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.reporting.diff'):
            source_text = _node_to_source(node)

        assert source_text == ''
        assert 'Failed to get source for AST node' in caplog.text


@pytest.mark.medium
class DescribeAppendHistoryEntryLogging:
    """Tests for logging in append_history_entry when history file is corrupt."""

    def it_logs_warning_when_history_file_is_corrupt(
        self, make_result, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        corrupt = tmp_path / 'history.json'
        corrupt.write_text('not json', encoding='utf-8')
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.reporting.history'):
            append_history_entry(rootdir=tmp_path, score=score, history_path=corrupt)

        assert 'Could not read existing history' in caplog.text
        assert str(corrupt) in caplog.text


@pytest.mark.medium
class DescribeLoadHistoryLogging:
    """Tests for logging in load_history when history file is corrupt."""

    def it_logs_warning_when_history_file_is_corrupt(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        corrupt = tmp_path / 'history.json'
        corrupt.write_text('not json', encoding='utf-8')

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.reporting.history'):
            loaded_entries = load_history(corrupt)

        assert loaded_entries == []
        assert 'Could not load history' in caplog.text
        assert str(corrupt) in caplog.text


@pytest.mark.medium
class DescribeWriteReportLogging:
    """Tests for logging in HtmlReporter.write_report."""

    def it_logs_info_with_output_path(self, make_result, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output_path = tmp_path / 'report.html'
        reporter = HtmlReporter()

        with caplog.at_level(logging.INFO, logger='pytest_gremlins.reporting.html'):
            reporter.write_report(score, output_path)

        assert 'HTML report written to' in caplog.text
        assert str(output_path) in caplog.text


@pytest.mark.medium
class DescribeWriteReportHistoryPersistence:
    """Tests that write_report persists history alongside the HTML file."""

    def it_creates_history_json_next_to_the_html_report(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output_path = tmp_path / 'coverage' / 'gremlins' / 'index.html'
        reporter = HtmlReporter()

        reporter.write_report(score, output_path)

        history_path = output_path.parent / 'history.json'
        assert history_path.exists()

    def it_appends_a_score_entry_to_history_json(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output_path = tmp_path / 'index.html'
        reporter = HtmlReporter()

        reporter.write_report(score, output_path)

        history_path = output_path.parent / 'history.json'
        entries = json.loads(history_path.read_text())
        assert len(entries) == 1
        assert entries[0]['score'] == 100.0

    def it_still_writes_html_when_history_raises(self, make_result, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output_path = tmp_path / 'index.html'
        reporter = HtmlReporter()

        def _boom(*_args, **_kwargs):
            raise OSError('disk full')

        monkeypatch.setattr('pytest_gremlins.reporting.html.append_history_entry', _boom)

        reporter.write_report(score, output_path)  # must not raise

        content = output_path.read_text(encoding='utf-8')
        assert '<!DOCTYPE html>' in content

    def it_logs_a_warning_when_history_raises(
        self, make_result, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output_path = tmp_path / 'index.html'
        reporter = HtmlReporter()

        def _boom(*_args, **_kwargs):
            raise OSError('disk full')

        monkeypatch.setattr('pytest_gremlins.reporting.html.append_history_entry', _boom)

        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.reporting.html'):
            reporter.write_report(score, output_path)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert 'history' in record.message.lower()
        assert str(output_path) in record.message

    def it_renders_no_data_placeholder_with_single_history_entry(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output_path = tmp_path / 'index.html'
        reporter = HtmlReporter()

        reporter.write_report(score, output_path)

        content = output_path.read_text(encoding='utf-8')
        assert 'No historical data yet.' in content

    def it_passes_history_to_html_when_history_exists(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        output_path = tmp_path / 'index.html'
        reporter = HtmlReporter()

        reporter.write_report(score, output_path)
        reporter.write_report(score, output_path)

        content = output_path.read_text(encoding='utf-8')
        assert 'data-history' in content


@pytest.mark.small
class DescribeHtmlReporterCssUx:
    """Tests for CSS UX correctness: contrast and overflow."""

    def it_uses_a_wcag_compliant_link_color_in_light_mode(self, make_result):
        # #4caf50 on white = 3.07:1 contrast ratio — WCAG AA requires 4.5:1.
        # The light theme must define --link-color with a darker value (#1b5e20 = 7.06:1).
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert '--link-color: #1b5e20' in html

    def it_uses_link_color_for_details_summary_not_color_primary_light(self, make_result):
        # details summary was using --color-primary-light (#4caf50) which fails contrast
        # in light mode. It must use --link-color instead.
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'details summary' in html
        # Find the details summary rule and confirm it uses --link-color
        style_start = html.index('<style>')
        style_end = html.index('</style>')
        css = html[style_start:style_end]
        summary_rule_start = css.index('details summary')
        summary_rule_end = css.index('}', summary_rule_start)
        summary_rule = css[summary_rule_start:summary_rule_end]
        assert 'var(--link-color)' in summary_rule
        assert 'var(--color-primary-light)' not in summary_rule

    def it_sets_table_layout_fixed_to_prevent_diff_overflow(self, make_result):
        # Without table-layout: fixed, opening diff panels inside a <td> expands
        # the entire table causing extreme horizontal overflow.
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        assert 'table-layout: fixed' in html

    def it_sets_min_width_zero_on_diff_panel_to_allow_grid_shrinking(self, make_result):
        # CSS grid children default to min-width: auto, preventing them from shrinking
        # below content width. min-width: 0 allows the grid to constrain them.
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        reporter = HtmlReporter()

        html = reporter.to_html(score)

        style_start = html.index('<style>')
        style_end = html.index('</style>')
        css = html[style_start:style_end]
        panel_rule_start = css.index('.diff-panel {')
        panel_rule_end = css.index('}', panel_rule_start)
        panel_rule = css[panel_rule_start:panel_rule_end]
        assert 'min-width: 0' in panel_rule
