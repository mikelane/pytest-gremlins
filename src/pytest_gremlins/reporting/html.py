"""HTML reporter for gremlin mutation testing results.

Produces a standalone HTML report with source code annotations
and visual highlighting of surviving gremlins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.reporting.results import GremlinResult
    from pytest_gremlins.reporting.score import MutationScore


class HtmlReporter:
    """Reporter that produces standalone HTML reports.

    Generates a self-contained HTML file with embedded CSS for
    viewing mutation testing results in a browser.
    """

    def to_html(self, score: MutationScore) -> str:
        """Convert mutation score to HTML string.

        Args:
            score: The MutationScore to convert.

        Returns:
            Complete HTML document as a string.
        """
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>pytest-gremlins Mutation Report</title>
    <style>
        {self._get_styles()}
    </style>
</head>
<body>
    <div class="container">
        <h1>pytest-gremlins Mutation Report</h1>
        {self._render_summary(score)}
        {self._render_results_table(score)}
    </div>
</body>
</html>"""

    def write_report(self, score: MutationScore, output_path: Path) -> None:
        """Write mutation report to an HTML file.

        Args:
            score: The MutationScore to write.
            output_path: Path to the output HTML file.
        """
        output_path.write_text(self.to_html(score))

    def _get_styles(self) -> str:
        """Get embedded CSS styles."""
        return """
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 { color: #2c3e50; margin-top: 0; }
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value { font-size: 2em; font-weight: bold; }
        .stat-label { color: #666; }
        .stat-zapped .stat-value { color: #27ae60; }
        .stat-survived .stat-value { color: #e74c3c; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        th { background: #f8f9fa; font-weight: 600; }
        tr:hover { background: #f8f9fa; }
        .status-zapped { color: #27ae60; }
        .status-survived { color: #e74c3c; font-weight: bold; }
        .status-timeout { color: #f39c12; }
        .status-error { color: #9b59b6; }
        .no-results { text-align: center; color: #666; padding: 40px; }
        """

    def _render_summary(self, score: MutationScore) -> str:
        """Render the summary section."""
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
            </div>
            <div class="stat-card">
                <div class="stat-value">{score.percentage:.0f}%</div>
                <div class="stat-label">Mutation Score</div>
            </div>
        </div>
        """

    def _render_results_table(self, score: MutationScore) -> str:
        """Render the results table."""
        if score.total == 0:
            return '<div class="no-results">No gremlins tested.</div>'

        rows = '\n'.join(self._render_result_row(r) for r in score.results)
        return f"""
        <table>
            <thead>
                <tr>
                    <th>File</th>
                    <th>Line</th>
                    <th>Operator</th>
                    <th>Description</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
        """

    def _render_result_row(self, result: GremlinResult) -> str:
        """Render a single result row."""
        gremlin = result.gremlin
        status_class = f'status-{result.status.value}'
        return f'''
                <tr>
                    <td>{self._escape_html(gremlin.file_path)}</td>
                    <td>{gremlin.line_number}</td>
                    <td>{self._escape_html(gremlin.operator_name)}</td>
                    <td>{self._escape_html(gremlin.description)}</td>
                    <td class="{status_class}">{result.status.value}</td>
                </tr>'''

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
