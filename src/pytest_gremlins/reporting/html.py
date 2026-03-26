"""HTML reporter for gremlin mutation testing results.

Produces a standalone HTML report with source code annotations
and visual highlighting of surviving gremlins.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from pytest_gremlins.reporting.diff import (
    _compute_diff,
    _node_to_source,
)
from pytest_gremlins.reporting.history import (
    _build_operator_data,
    append_history_entry,
    load_history,
)
from pytest_gremlins.reporting.results import GremlinResultStatus

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.reporting.results import GremlinResult
    from pytest_gremlins.reporting.score import MutationScore

__all__ = [
    'HtmlReporter',
    'append_history_entry',
    'load_history',
    'resolve_html_output_path',
]

_SCORE_GREEN_THRESHOLD = 80
_SCORE_AMBER_THRESHOLD = 60
_HISTORY_MIN_ENTRIES_FOR_CHART = 2


def resolve_html_output_path(rootdir: Path, html_dir: Path | None) -> Path:
    """Resolve the output path for the HTML report.

    When no custom directory is given, the report is written to
    ``<rootdir>/coverage/gremlins/index.html`` so it can coexist with
    coverage.py HTML output.  When a custom directory is supplied the
    report is written to ``<html_dir>/index.html``; if *html_dir* is a
    relative path it is anchored to *rootdir*.

    Args:
        rootdir: Project root directory used as the anchor for the default path.
        html_dir: Custom output directory, or ``None`` for the default location.

    Returns:
        Absolute path to ``index.html`` inside the resolved output directory.

    Examples:
        >>> from pathlib import Path
        >>> p = resolve_html_output_path(Path('/project'), None)
        >>> p.parts[-3:]
        ('coverage', 'gremlins', 'index.html')
        >>> q = resolve_html_output_path(Path('/project'), Path('/project/out'))
        >>> q.parts[-2:]
        ('out', 'index.html')
    """
    if html_dir is not None:
        resolved_dir = html_dir if html_dir.is_absolute() else rootdir / html_dir
        return resolved_dir / 'index.html'
    return rootdir / 'coverage' / 'gremlins' / 'index.html'


class HtmlReporter:
    """Reporter that produces standalone HTML reports.

    Generates a self-contained HTML file with embedded CSS, Chart.js
    visualisations, diff panels, dark/light mode toggle, and optional
    historical trend chart for viewing mutation testing results in a browser.
    """

    def to_html(self, score: MutationScore, history: list[dict[str, Any]] | None = None) -> str:
        """Convert mutation score to HTML string.

        Args:
            score: The MutationScore to convert.
            history: Optional list of historical score entries from load_history.
                     When provided, a trend section is rendered.  Pass an empty
                     list to render the "no data yet" placeholder.

        Returns:
            Complete HTML document as a string.
        """
        chart_data = self._build_chart_data(score)
        history_html = self._render_history_section(history) if history is not None else ''
        return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>pytest-gremlins Mutation Report</title>
    <style>
        {self._get_styles()}
    </style>
    <script>
        {self._get_theme_init_script()}
    </script>
</head>
<body>
    <div class="container">
        <header class="report-header">
            <h1>pytest-gremlins Mutation Report</h1>
            <button class="theme-toggle" onclick="toggleTheme()"
                aria-label="Toggle light/dark mode" aria-pressed="true">
                Toggle Theme
            </button>
        </header>
        <main>
        {self._render_summary(score)}
        {self._render_charts(score, chart_data)}
        {self._render_results_table(score)}
        {self._render_pardoned_section(score)}
        {self._render_errors_section(score)}
        {history_html}
        </main>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"
            integrity="sha384-NrKB+u6Ts6AtkIhwPixiKTzgSKNblyhlk0Sohlgar9UHUBzai/sgnNNWWd291xqt"
            crossorigin="anonymous"></script>
    <script>
        {self._get_chart_script(score, chart_data) if score.total > 0 else ''}
        {self._get_expand_collapse_script()}
    </script>
</body>
</html>"""

    def write_report(self, score: MutationScore, output_path: Path) -> None:
        """Write mutation report to an HTML file and persist history.

        Creates any missing parent directories before writing.  History is
        appended to ``history.json`` in the same directory as the report.
        If history persistence fails, a warning is logged and the HTML report
        is still written.

        Args:
            score: The MutationScore to write.
            output_path: Path to the output HTML file.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        history_path = output_path.parent / 'history.json'
        try:
            append_history_entry(
                rootdir=output_path.parent,
                score=score,
                history_path=history_path,
            )
        except Exception:
            logger.warning('Failed to persist history for report at %s', output_path, exc_info=True)
        history = load_history(history_path)
        output_path.write_text(self.to_html(score, history=history), encoding='utf-8')
        logger.info('HTML report written to %s', output_path)

    def _get_styles(self) -> str:
        """Get embedded CSS styles with dark/light mode custom properties."""
        return """
        :root, [data-theme="dark"] {
            --bg-primary: #121212;
            --bg-secondary: #1e1e1e;
            --bg-card: #252525;
            --bg-table-header: #2a2a2a;
            --bg-table-hover: #2a2a2a;
            --bg-details: #1a2a1a;
            --text-primary: #e8e8e8;
            --text-secondary: #a0a0a0;
            --text-heading: #ffffff;
            --border-color: #333333;
            --color-primary: #2e7d32;
            --color-primary-light: #4caf50;
            --link-color: #4caf50;
            --color-zapped: #4caf50;
            --color-survived: #ef5350;
            --color-timeout: #ffa726;
            --color-error: #ab47bc;
            --shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
            --diff-add-bg: rgba(46, 125, 50, 0.2);
            --diff-add-text: #81c784;
            --diff-remove-bg: rgba(211, 47, 47, 0.2);
            --diff-remove-text: #ef9a9a;
            --diff-header-bg: rgba(0, 0, 0, 0.3);
        }

        [data-theme="light"] {
            --bg-primary: #f5f5f5;
            --bg-secondary: #ffffff;
            --bg-card: #ffffff;
            --bg-table-header: #f8f9fa;
            --bg-table-hover: #f8f9fa;
            --bg-details: #f1f8f1;
            --text-primary: #333333;
            --text-secondary: #666666;
            --text-heading: #1a1a1a;
            --border-color: #e0e0e0;
            --color-primary: #2e7d32;
            --color-primary-light: #4caf50;
            --link-color: #1b5e20;
            --color-zapped: #2e7d32;
            --color-survived: #c62828;
            --color-timeout: #e65100;
            --color-error: #6a1b9a;
            --shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            --diff-add-bg: rgba(46, 125, 50, 0.1);
            --diff-add-text: #2e7d32;
            --diff-remove-bg: rgba(198, 40, 40, 0.1);
            --diff-remove-text: #c62828;
            --diff-header-bg: rgba(0, 0, 0, 0.05);
        }

        * { box-sizing: border-box; }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: var(--text-primary);
            background: var(--bg-primary);
            margin: 0;
            padding: 20px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: var(--bg-secondary);
            padding: 30px;
            border-radius: 8px;
            box-shadow: var(--shadow);
        }

        .report-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 12px;
        }

        h1 { color: var(--text-heading); margin: 0; font-size: 1.8em; }
        h2 { color: var(--text-heading); font-size: 1.2em; margin: 24px 0 12px; }

        .theme-toggle {
            background: var(--color-primary);
            color: #ffffff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.9em;
            font-weight: 500;
        }

        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }

        .stat-card {
            background: var(--bg-card);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: var(--shadow);
            border: 1px solid var(--border-color);
        }

        .stat-value { font-size: 2em; font-weight: 700; color: var(--text-heading); }
        .stat-label { color: var(--text-secondary); font-size: 0.9em; margin-top: 4px; }
        .stat-zapped .stat-value { color: var(--color-zapped); }
        .stat-survived .stat-value { color: var(--color-survived); }

        .charts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .chart-card {
            background: var(--bg-card);
            padding: 20px;
            border-radius: 8px;
            box-shadow: var(--shadow);
            border: 1px solid var(--border-color);
        }

        .chart-card h3 {
            color: var(--text-heading);
            font-size: 1em;
            margin: 0 0 12px;
            font-weight: 600;
        }

        .chart-container { position: relative; height: 200px; }
        .chart-container-tall { position: relative; height: 300px; }

        table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            margin-top: 20px;
        }

        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.9em;
        }

        th { background: var(--bg-table-header); font-weight: 600; color: var(--text-heading); }
        tr:hover > td { background: var(--bg-table-hover); }

        .status-zapped { color: var(--color-zapped); font-weight: 500; }
        .status-survived { color: var(--color-survived); font-weight: 700; }
        .status-timeout { color: var(--color-timeout); font-weight: 500; }
        .status-error { color: var(--color-error); font-weight: 500; }

        .no-results { text-align: center; color: var(--text-secondary); padding: 40px; }

        .expand-controls { margin: 16px 0 8px; display: flex; gap: 8px; }

        .expand-btn {
            background: var(--bg-card);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.85em;
            min-height: 44px;
            min-width: 44px;
        }

        details { margin-top: 8px; }

        details summary {
            cursor: pointer;
            color: var(--link-color);
            font-size: 0.85em;
            user-select: none;
            padding: 4px 0;
            min-height: 44px;
            min-width: 44px;
        }

        :focus-visible {
            outline: 3px solid var(--color-primary-light);
            outline-offset: 2px;
        }

        @media (prefers-reduced-motion: reduce) {
            * { transition: none !important; animation: none !important; }
        }

        .diff-panels {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 8px;
        }

        @media (max-width: 640px) {
            .diff-panels { grid-template-columns: 1fr; }
        }

        .diff-panel {
            background: var(--bg-details);
            border-radius: 6px;
            overflow: hidden;
            min-width: 0;
            border: 1px solid var(--border-color);
        }

        .diff-panel-header {
            background: var(--diff-header-bg);
            padding: 6px 12px;
            font-size: 0.8em;
            font-weight: 600;
            color: var(--text-secondary);
            border-bottom: 1px solid var(--border-color);
        }

        .diff-panel pre {
            margin: 0;
            padding: 12px;
            font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
            font-size: 0.82em;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-all;
            color: var(--text-primary);
        }

        .diff-unified {
            background: var(--bg-details);
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            margin-top: 8px;
        }

        .diff-unified pre {
            margin: 0;
            padding: 12px;
            font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
            font-size: 0.82em;
            overflow-x: auto;
            color: var(--text-primary);
        }

        .diff-add { background: var(--diff-add-bg); color: var(--diff-add-text); }
        .diff-remove { background: var(--diff-remove-bg); color: var(--diff-remove-text); }
        .diff-meta { color: var(--text-secondary); font-style: italic; }

        .history-section {
            margin-top: 30px;
            background: var(--bg-card);
            padding: 20px;
            border-radius: 8px;
            box-shadow: var(--shadow);
            border: 1px solid var(--border-color);
        }

        .history-section h2 { margin-top: 0; }

        .no-history { color: var(--text-secondary); font-style: italic; padding: 16px 0; }

        @media (max-width: 600px) {
            body { padding: 12px; }
            .container { padding: 16px; }
            .charts-grid { grid-template-columns: 1fr; }
            .summary { grid-template-columns: repeat(2, 1fr); }
        }
        """

    def _get_theme_init_script(self) -> str:
        """Get the inline script that restores saved theme preference on page load."""
        return """
        (function() {
            var saved = localStorage.getItem('gremlins-theme');
            if (saved === 'dark' || saved === 'light') {
                document.documentElement.setAttribute('data-theme', saved);
            }
            document.addEventListener('DOMContentLoaded', function() {
                var theme = document.documentElement.getAttribute('data-theme');
                var btn = document.querySelector('.theme-toggle');
                if (btn) {
                    btn.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
                }
            });
        })();
        """

    def _get_chart_script(self, score: MutationScore, chart_data: dict[str, Any]) -> str:
        """Get the Chart.js initialisation script.

        Args:
            score: The MutationScore being reported.
            chart_data: Pre-computed chart data from _build_chart_data.

        Returns:
            JavaScript string that creates all Chart.js charts.
        """
        pct = score.percentage
        if pct >= _SCORE_GREEN_THRESHOLD:
            gauge_color = '#4caf50'
        elif pct >= _SCORE_AMBER_THRESHOLD:
            gauge_color = '#ffa726'
        else:
            gauge_color = '#ef5350'

        file_labels = json.dumps(chart_data['file_labels'])
        file_scores = json.dumps(chart_data['file_scores'])
        op_labels = json.dumps(chart_data['op_labels'])
        op_total = json.dumps(chart_data['op_total'])
        op_survived = json.dumps(chart_data['op_survived'])

        return f"""
        window.addEventListener('load', function() {{
            var textColor = getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim();
            var borderColor = getComputedStyle(document.documentElement).getPropertyValue('--border-color').trim();

            var gaugeEl = document.getElementById('scoreGauge');
            if (gaugeEl) {{
                new Chart(gaugeEl, {{
                    type: 'doughnut',
                    data: {{
                        datasets: [{{
                            data: [{pct:.1f}, {100 - pct:.1f}],
                            backgroundColor: ['{gauge_color}', borderColor],
                            borderWidth: 0,
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        cutout: '70%',
                        plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }}
                    }}
                }});
            }}

            var outcomeEl = document.getElementById('outcomeChart');
            if (outcomeEl) {{
                new Chart(outcomeEl, {{
                    type: 'pie',
                    data: {{
                        labels: ['Zapped', 'Survived', 'Timeout', 'Error'],
                        datasets: [{{
                            data: [{score.zapped}, {score.survived}, {score.timeout}, {score.error}],
                            backgroundColor: ['#4caf50', '#ef5350', '#ffa726', '#ab47bc'],
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{ legend: {{ position: 'bottom', labels: {{ color: textColor }} }} }}
                    }}
                }});
            }}

            var fileEl = document.getElementById('fileChart');
            if (fileEl && {file_labels}.length > 0) {{
                new Chart(fileEl, {{
                    type: 'bar',
                    data: {{
                        labels: {file_labels},
                        datasets: [{{
                            label: 'Score %',
                            data: {file_scores},
                            backgroundColor: {file_scores}.map(function(v) {{
                                if (v >= {_SCORE_GREEN_THRESHOLD}) {{ return '#4caf50'; }}
                                return v >= {_SCORE_AMBER_THRESHOLD} ? '#ffa726' : '#ef5350';
                            }}),
                        }}]
                    }},
                    options: {{
                        indexAxis: 'y',
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{ legend: {{ display: false }} }},
                        scales: {{
                            x: {{ min: 0, max: 100, ticks: {{ color: textColor }}, grid: {{ color: borderColor }} }},
                            y: {{ ticks: {{ color: textColor }}, grid: {{ color: borderColor }} }}
                        }}
                    }}
                }});
            }}

            var opEl = document.getElementById('operatorChart');
            if (opEl && {op_labels}.length > 0) {{
                new Chart(opEl, {{
                    type: 'bar',
                    data: {{
                        labels: {op_labels},
                        datasets: [
                            {{ label: 'Total', data: {op_total}, backgroundColor: '#2e7d32' }},
                            {{ label: 'Survived', data: {op_survived}, backgroundColor: '#ef5350' }},
                        ]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{ legend: {{ position: 'bottom', labels: {{ color: textColor }} }} }},
                        scales: {{
                            x: {{ ticks: {{ color: textColor }}, grid: {{ color: borderColor }} }},
                            y: {{ ticks: {{ color: textColor }}, grid: {{ color: borderColor }} }}
                        }}
                    }}
                }});
            }}

            var histEl = document.getElementById('historyChart');
            if (histEl) {{
                var entries = JSON.parse(histEl.dataset.history || '[]');
                if (entries.length >= 2) {{
                    new Chart(histEl, {{
                        type: 'line',
                        data: {{
                            labels: entries.map(function(e) {{ return e.timestamp.substring(0, 10); }}),
                            datasets: [{{
                                label: 'Mutation Score %',
                                data: entries.map(function(e) {{ return e.score; }}),
                                borderColor: '#4caf50',
                                backgroundColor: 'rgba(76, 175, 80, 0.1)',
                                tension: 0.3,
                                fill: true,
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {{ legend: {{ labels: {{ color: textColor }} }} }},
                            scales: {{
                                x: {{ ticks: {{ color: textColor }}, grid: {{ color: borderColor }} }},
                                y: {{ min: 0, max: 100, ticks: {{ color: textColor }}, grid: {{ color: borderColor }} }}
                            }}
                        }}
                    }});
                }}
            }}
        }});

        function toggleTheme() {{
            var html = document.documentElement;
            var current = html.getAttribute('data-theme');
            var next = current === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', next);
            localStorage.setItem('gremlins-theme', next);
            var btn = document.querySelector('.theme-toggle');
            if (next === 'dark') {{
                btn.setAttribute('aria-pressed', 'true');
            }} else {{
                btn.setAttribute('aria-pressed', 'false');
            }}
        }}
        """

    def _get_expand_collapse_script(self) -> str:
        """Get inline JS for expand-all / collapse-all diff panels."""
        return """
        function expandAllDiffs() {
            document.querySelectorAll('details').forEach(function(d) { d.open = true; });
        }
        function collapseAllDiffs() {
            document.querySelectorAll('details').forEach(function(d) { d.open = false; });
        }
        """

    def _build_chart_data(self, score: MutationScore) -> dict[str, Any]:
        """Pre-compute all data needed for Chart.js visualisations.

        Args:
            score: The MutationScore to extract data from.

        Returns:
            Dictionary with file_labels, file_scores, op_labels, op_total, op_survived.
        """
        file_scores_map = score.by_file()
        file_items = sorted(file_scores_map.items(), key=lambda kv: kv[1].percentage)
        file_labels = [fp for fp, _ in file_items]
        file_scores_list = [round(fs.percentage, 1) for _, fs in file_items]

        op_data = _build_operator_data(score)

        op_labels = list(op_data.keys())
        op_total = [op_data[op]['total'] for op in op_labels]
        op_survived = [op_data[op]['survived'] for op in op_labels]

        return {
            'file_labels': file_labels,
            'file_scores': file_scores_list,
            'op_labels': op_labels,
            'op_total': op_total,
            'op_survived': op_survived,
        }

    def _render_summary(self, score: MutationScore) -> str:
        """Render the summary section."""
        timeout_card = ''
        if score.timeout > 0:
            timeout_card = f"""
            <div class="stat-card stat-timeout">
                <div class="stat-value">{score.timeout}</div>
                <div class="stat-label">Timeout</div>
            </div>"""

        error_card = ''
        if score.error > 0:
            error_card = f"""
            <div class="stat-card stat-error">
                <div class="stat-value">{score.error}</div>
                <div class="stat-label">Error</div>
            </div>"""

        pardoned_card = ''
        if score.pardoned > 0:
            pardoned_card = f"""
            <div class="stat-card">
                <div class="stat-value">{score.pardoned}</div>
                <div class="stat-label">Pardoned</div>
            </div>"""

        return f"""
        <div class="summary">
            <div class="stat-card">
                <div class="stat-value">{score.total}</div>
                <div class="stat-label">Total Gremlins</div>
            </div>
            <div class="stat-card stat-zapped">
                <div class="stat-value">{score.zapped}</div>
                <div class="stat-label">Zapped</div>
            </div>
            <div class="stat-card stat-survived">
                <div class="stat-value">{score.survived}</div>
                <div class="stat-label">Survived</div>
            </div>{timeout_card}{error_card}{pardoned_card}
            <div class="stat-card">
                <div class="stat-value">{score.percentage:.0f}%</div>
                <div class="stat-label">Mutation Score</div>
            </div>
        </div>
        """

    def _render_pardoned_section(self, score: MutationScore) -> str:
        """Render a table of pardoned gremlins with their pardon reasons.

        Args:
            score: The MutationScore containing result data.

        Returns:
            HTML string for the pardoned section, or empty string when none exist.
        """
        pardoned_results = [r for r in score.results if r.status == GremlinResultStatus.PARDONED]
        if not pardoned_results:
            return ''

        rows = ''
        for result in pardoned_results:
            gremlin = result.gremlin
            pardon_reason = self._escape_html(gremlin.pardon_reason or '')
            rows += f"""
                <tr>
                    <td>{self._escape_html(gremlin.file_path)}</td>
                    <td>{gremlin.line_number}</td>
                    <td>{self._escape_html(gremlin.operator_name)}</td>
                    <td>{self._escape_html(gremlin.description)}</td>
                    <td>{pardon_reason}</td>
                </tr>"""

        return f"""
        <h2>Pardoned Gremlins</h2>
        <table>
            <caption>Gremlins suppressed by inline pragma</caption>
            <thead>
                <tr>
                    <th scope="col">File</th>
                    <th scope="col">Line</th>
                    <th scope="col">Operator</th>
                    <th scope="col">Description</th>
                    <th scope="col">Pardon Reason</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
        """

    def _render_errors_section(self, score: MutationScore) -> str:
        """Render a table of errored gremlins with collapsible stderr panels.

        Args:
            score: The MutationScore containing result data.

        Returns:
            HTML string for the errors section, or empty string when none exist.
        """
        error_results = [r for r in score.results if r.status == GremlinResultStatus.ERROR and r.error_output]
        if not error_results:
            return ''

        rows = ''
        for result in error_results:
            gremlin = result.gremlin
            escaped_output = self._escape_html(result.error_output)
            rows += f"""
                <tr>
                    <td>{self._escape_html(gremlin.file_path)}</td>
                    <td>{gremlin.line_number}</td>
                    <td>{self._escape_html(gremlin.operator_name)}</td>
                    <td>
                        <details>
                            <summary>Show stderr</summary>
                            <pre>{escaped_output}</pre>
                        </details>
                    </td>
                </tr>"""

        return f"""
        <h2>Errored Gremlins</h2>
        <table>
            <caption>Gremlins that failed with errors during testing</caption>
            <thead>
                <tr>
                    <th scope="col">File</th>
                    <th scope="col">Line</th>
                    <th scope="col">Operator</th>
                    <th scope="col">Error Output</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
        """

    def _render_charts(self, score: MutationScore, chart_data: dict[str, Any]) -> str:
        """Render Chart.js visualisation canvas elements.

        Args:
            score: The MutationScore for per-file and per-operator data.
            chart_data: Pre-computed data from _build_chart_data.

        Returns:
            HTML string containing chart cards with canvas elements, or empty
            string when there are no results to visualise.
        """
        if score.total == 0:
            return ''

        file_chart_height = max(200, len(chart_data['file_labels']) * 28)

        return f"""
        <h2>Charts</h2>
        <div class="charts-grid">
            <div class="chart-card">
                <h3>Mutation Score</h3>
                <div class="chart-container">
                    <canvas id="scoreGauge" role="img" aria-label="Mutation score gauge: {score.percentage:.0f}%">
                        Mutation score: {score.percentage:.0f}%. Chart requires JavaScript.
                    </canvas>
                </div>
                <p style="text-align:center;font-size:1.5em;font-weight:700;color:var(--text-heading);margin:8px 0 0">
                    {score.percentage:.0f}%
                </p>
            </div>
            <div class="chart-card">
                <h3>Outcomes</h3>
                <div class="chart-container">
                    <canvas id="outcomeChart" role="img" aria-label="Outcome distribution pie chart">
                        Outcome distribution chart. Chart requires JavaScript.
                    </canvas>
                </div>
            </div>
            <div class="chart-card" style="grid-column: 1 / -1;">
                <h3>Per-File Score</h3>
                <div style="position:relative;height:{file_chart_height}px;">
                    <canvas id="fileChart" role="img" aria-label="Per-file mutation scores bar chart">
                        Per-file mutation scores chart. Chart requires JavaScript.
                    </canvas>
                </div>
            </div>
            <div class="chart-card" style="grid-column: 1 / -1;">
                <h3>Operator Distribution</h3>
                <div class="chart-container">
                    <canvas id="operatorChart" role="img" aria-label="Operator distribution bar chart">
                        Operator distribution chart. Chart requires JavaScript.
                    </canvas>
                </div>
            </div>
        </div>
        """

    def _render_results_table(self, score: MutationScore) -> str:
        """Render the results table with collapsible diff panels."""
        if score.total == 0:
            return '<div class="no-results">No gremlins tested.</div>'

        rows = '\n'.join(self._render_result_row(r) for r in score.results)
        return f"""
        <div class="expand-controls">
            <button class="expand-btn" onclick="expandAllDiffs()">Expand all diffs</button>
            <button class="expand-btn" onclick="collapseAllDiffs()">Collapse all diffs</button>
        </div>
        <table>
            <caption>Gremlin mutation testing results</caption>
            <thead>
                <tr>
                    <th scope="col">File</th>
                    <th scope="col">Line</th>
                    <th scope="col">Operator</th>
                    <th scope="col">Description</th>
                    <th scope="col">Status</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
        """

    def _render_result_row(self, result: GremlinResult) -> str:
        """Render a single result row with a collapsible diff panel."""
        gremlin = result.gremlin
        status_class = f'status-{result.status.value}'
        diff_html = self._render_diff_panel(gremlin)
        return f"""
                <tr>
                    <td>
                        {self._escape_html(gremlin.file_path)}
                        {diff_html}
                    </td>
                    <td>{gremlin.line_number}</td>
                    <td>{self._escape_html(gremlin.operator_name)}</td>
                    <td>{self._escape_html(gremlin.description)}</td>
                    <td class="{status_class}">{result.status.value}</td>
                </tr>"""

    def _render_diff_panel(self, gremlin: Gremlin) -> str:
        """Render a collapsible side-by-side diff panel for a gremlin.

        Args:
            gremlin: A Gremlin instance with original_node and mutated_node.

        Returns:
            HTML string with a <details> element containing the diff, or empty
            string if source cannot be unparsed from the AST nodes.
        """
        original_src = _node_to_source(gremlin.original_node)
        mutated_src = _node_to_source(gremlin.mutated_node)

        if not original_src and not mutated_src:
            return ''

        diff_lines = _compute_diff(original_src, mutated_src)
        diff_html_lines = []
        for line in diff_lines:
            escaped = self._escape_html(line.rstrip('\n'))
            if line.startswith('+') and not line.startswith('+++'):
                diff_html_lines.append(f'<span class="diff-add">{escaped}</span>')
            elif line.startswith('-') and not line.startswith('---'):
                diff_html_lines.append(f'<span class="diff-remove">{escaped}</span>')
            elif line.startswith('@@'):
                diff_html_lines.append(f'<span class="diff-meta">{escaped}</span>')
            else:
                diff_html_lines.append(escaped)
        diff_body = '\n'.join(diff_html_lines)

        return f"""
                        <details>
                            <summary>Show diff</summary>
                            <div class="diff-panels">
                                <div class="diff-panel">
                                    <div class="diff-panel-header">Mogwai (original)</div>
                                    <pre>{self._escape_html(original_src)}</pre>
                                </div>
                                <div class="diff-panel">
                                    <div class="diff-panel-header">Gremlin (mutated)</div>
                                    <pre>{self._escape_html(mutated_src)}</pre>
                                </div>
                            </div>
                            <div class="diff-unified">
                                <pre>{diff_body}</pre>
                            </div>
                        </details>"""

    def _render_history_section(self, history: list[dict[str, Any]]) -> str:
        """Render the historical trend section.

        Args:
            history: List of history entry dicts.  Empty list renders the
                     placeholder; two or more entries render the chart canvas.

        Returns:
            HTML string for the history section.
        """
        if len(history) < _HISTORY_MIN_ENTRIES_FOR_CHART:
            return """
        <div class="history-section" id="historySection">
            <h2>Historical Trend</h2>
            <p class="no-history">No historical data yet. Run mutation testing multiple times to see trends.</p>
        </div>
        """

        history_json = self._escape_html(json.dumps(history))
        return f"""
        <div class="history-section" id="historySection">
            <h2>Historical Trend</h2>
            <div class="chart-container-tall">
                <canvas id="historyChart" role="img" data-history="{history_json}"
                    aria-label="Historical mutation score trend">
                    Historical mutation score trend chart. Chart requires JavaScript.
                </canvas>
            </div>
        </div>
        """

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
