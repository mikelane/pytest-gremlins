"""Console reporter for gremlin mutation testing results.

Produces human-readable output for terminal display with summary
statistics and top surviving gremlins.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, TextIO


if TYPE_CHECKING:
    from pytest_gremlins.reporting.score import MutationScore


class ConsoleReporter:
    """Reporter that writes mutation testing results to the console.

    Produces output in the following format:

        ================== pytest-gremlins mutation report ==================

        Zapped: 142 gremlins (89%)
        Survived: 18 gremlins (11%)

        Top surviving gremlins:
          src/auth.py:42    >= to >     (boundary not tested)
          src/utils.py:17   + to -      (arithmetic not verified)

        Run with --gremlin-report=html for detailed report.
        =====================================================================

    Attributes:
        output: The file-like object to write to.
    """

    BORDER_CHAR = '='
    BORDER_WIDTH = 70

    def __init__(self, output: TextIO | None = None) -> None:
        """Initialize the console reporter.

        Args:
            output: File-like object to write to. Defaults to sys.stdout.
        """
        self.output = output or sys.stdout

    def write_report(self, score: MutationScore) -> None:
        """Write the mutation testing report to the output.

        Args:
            score: The MutationScore containing aggregated results.
        """
        self._write_header()
        self._write_blank_line()

        if score.total == 0:
            self._write_line('No gremlins tested.')
        else:
            self._write_summary(score)
            self._write_blank_line()
            self._write_survivors(score)

        self._write_hint()
        self._write_footer()

    def _write_header(self) -> None:
        """Write the report header."""
        title = ' pytest-gremlins mutation report '
        border_len = (self.BORDER_WIDTH - len(title)) // 2
        header = f'{self.BORDER_CHAR * border_len}{title}{self.BORDER_CHAR * border_len}'
        self._write_line(header)

    def _write_footer(self) -> None:
        """Write the report footer."""
        self._write_line(self.BORDER_CHAR * self.BORDER_WIDTH)

    def _write_summary(self, score: MutationScore) -> None:
        """Write the summary statistics."""
        zapped_pct = round(score.percentage)
        survived_pct = 100 - zapped_pct if score.total > 0 else 0

        self._write_line(f'Zapped: {score.zapped} gremlins ({zapped_pct}%)')
        self._write_line(f'Survived: {score.survived} gremlins ({survived_pct}%)')

    def _write_survivors(self, score: MutationScore) -> None:
        """Write the top surviving gremlins."""
        survivors = score.top_survivors(limit=10)
        if not survivors:
            return

        self._write_line('Top surviving gremlins:')
        for result in survivors:
            gremlin = result.gremlin
            location = f'{gremlin.file_path}:{gremlin.line_number}'
            self._write_line(f'  {location:<24} {gremlin.description:<16} ({gremlin.operator_name})')

    def _write_hint(self) -> None:
        """Write hint about detailed report."""
        self._write_blank_line()
        self._write_line('Run with --gremlin-report=html for detailed report.')

    def _write_blank_line(self) -> None:
        """Write a blank line."""
        self.output.write('\n')

    def _write_line(self, text: str) -> None:
        """Write a line of text followed by newline."""
        self.output.write(text + '\n')
