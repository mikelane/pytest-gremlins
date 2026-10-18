"""Stryker Dashboard JSON exporter for mutation testing results.

Exports pytest-gremlins results in the mutation-testing-report-schema format
used by the Stryker Dashboard and compatible tools.

See: https://github.com/stryker-mutator/mutation-testing-elements
"""

from __future__ import annotations

from collections import defaultdict
import json
import logging
import re
import tokenize
from typing import TYPE_CHECKING

import pytest_gremlins
from pytest_gremlins.reporting.results import GremlinResultStatus

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.reporting.results import GremlinResult
    from pytest_gremlins.reporting.score import MutationScore
    from pytest_gremlins.reporting.types import (
        StrykerFileResult,
        StrykerFramework,
        StrykerLocation,
        StrykerMutant,
        StrykerPosition,
        StrykerReport,
        StrykerScoreSummary,
    )

logger = logging.getLogger(__name__)


STATUS_MAP: dict[GremlinResultStatus, str] = {
    GremlinResultStatus.ZAPPED: 'Killed',
    GremlinResultStatus.SURVIVED: 'Survived',
    GremlinResultStatus.TIMEOUT: 'Timeout',
    GremlinResultStatus.ERROR: 'RuntimeError',
    GremlinResultStatus.PARDONED: 'Ignored',
}

LINE_BREAK = re.compile(r'\r\n|\r|\n')

SCORE_NOTE = (
    'pytest-gremlins mutation score: (zapped + timeout) / (total - pardoned). ERROR gremlins are exported as '
    'RuntimeError, which Stryker excludes from its score denominator, but pytest-gremlins keeps them in the '
    'denominator, so a score recomputed from the mutant statuses can be higher than this one. This value is '
    'authoritative.'
)


def read_source(file_path: str) -> str:
    """Read the original source of a mutated file, which the schema requires per file.

    Args:
        file_path: Path of the mutated file, as recorded on the gremlin.

    Returns:
        The file's text decoded the way the plugin decodes it for instrumentation (PEP 263
        declarations honoured, BOM stripped), or an empty string when it cannot be read (the
        schema requires the key, so an unreadable file still yields a valid report).
    """
    try:
        with tokenize.open(file_path) as source_stream:
            return source_stream.read()
    except (OSError, UnicodeDecodeError, SyntaxError, LookupError):
        logger.warning('Could not read %s for the Stryker report; exporting empty source', file_path, exc_info=True)
        return ''


def utf16_column(source_lines: list[str], line_number: int, byte_offset: int) -> int:
    """Convert an AST column, counted in UTF-8 bytes, to a 0-based UTF-16 code unit column.

    The report viewer indexes source text with JavaScript string indices, which count UTF-16
    code units, so a character outside the BMP (an emoji) occupies two columns.

    Args:
        source_lines: The file's lines.
        line_number: 1-based line number the column belongs to.
        byte_offset: The AST's 0-based UTF-8 byte offset within that line.

    Returns:
        The 0-based UTF-16 column, or ``byte_offset`` unchanged when the line is not available.

    Example:
        >>> utf16_column(["s = 'é'; x"], 1, 9)
        8
        >>> utf16_column(["s = '\U0001f600'; x"], 1, 12)
        10
        >>> utf16_column([], 1, 4)
        4
    """
    if not 1 <= line_number <= len(source_lines):
        return byte_offset
    prefix = source_lines[line_number - 1].encode('utf-8')[:byte_offset].decode('utf-8', errors='ignore')
    return len(prefix.encode('utf-16-le')) // 2


class StrykerExporter:
    """Exporter that produces Stryker Dashboard compatible JSON.

    The output follows the mutation-testing-report-schema specification
    which enables compatibility with:
    - Stryker Dashboard (badge and report hosting)
    - SonarQube (via jq conversion)
    - Other mutation testing report viewers

    JSON structure follows the schema at:
    https://github.com/stryker-mutator/mutation-testing-elements

    Example:
        >>> from pytest_gremlins.reporting.score import MutationScore
        >>> exporter = StrykerExporter()
        >>> # json_str = exporter.to_json(score)
    """

    def __init__(
        self,
        thresholds: dict[str, int] | None = None,
        source_reader: Callable[[str], str] | None = None,
    ) -> None:
        """Initialize the exporter with optional thresholds and source reader.

        Args:
            thresholds: Optional dict with 'high' and 'low' score thresholds.
                        Defaults to high=80, low=60.
            source_reader: Optional callable returning a mutated file's source text
                           from its path. Defaults to reading the file from disk.
        """
        self._thresholds = thresholds or {'high': 80, 'low': 60}
        self._source_reader = source_reader or read_source

    def to_json(self, score: MutationScore) -> str:
        """Convert mutation score to Stryker format JSON string.

        Args:
            score: The MutationScore to convert.

        Returns:
            JSON string conforming to mutation-testing-report-schema.
        """
        data = self._build_report_data(score)
        return json.dumps(data, indent=2)

    def to_score_only_json(self, score: MutationScore) -> str:
        """Convert mutation score to simple score-only format.

        This minimal format is accepted by the Stryker Dashboard
        for badge display when full report details are not needed.

        Args:
            score: The MutationScore to convert.

        Returns:
            JSON string with only mutationScore field.
        """
        data = {'mutationScore': score.percentage}
        return json.dumps(data, indent=2)

    def write_report(self, score: MutationScore, output_path: Path) -> None:
        """Write mutation report to a JSON file.

        Args:
            score: The MutationScore to write.
            output_path: Path to the output JSON file.
        """
        output_path.write_text(self.to_json(score))

    def _build_report_data(self, score: MutationScore) -> StrykerReport:
        """Build the complete report data structure.

        Args:
            score: The MutationScore to convert.

        Returns:
            Dictionary conforming to mutation-testing-report-schema.
        """
        framework: StrykerFramework = {
            'name': 'pytest-gremlins',
            'version': pytest_gremlins.__version__,
        }
        return {
            'schemaVersion': '1.0',
            'thresholds': self._thresholds,
            'files': self._build_files(score),
            'framework': framework,
            'config': {'pytestGremlins': self._build_score_summary(score)},
        }

    def _build_score_summary(self, score: MutationScore) -> StrykerScoreSummary:
        """Build pytest-gremlins' own score for the schema's free-form ``config`` object.

        Args:
            score: The MutationScore to summarize.

        Returns:
            The authoritative score, the counts behind it, and a note on how ERRORs are counted.
        """
        return {
            'mutationScore': score.percentage,
            'counts': {
                'total': score.total,
                'zapped': score.zapped,
                'survived': score.survived,
                'timeout': score.timeout,
                'error': score.error,
                'pardoned': score.pardoned,
            },
            'note': SCORE_NOTE,
        }

    def _build_files(self, score: MutationScore) -> dict[str, StrykerFileResult]:
        """Build the files section grouping mutants by file.

        Args:
            score: The MutationScore containing results.

        Returns:
            Dictionary mapping file paths to file data with mutants.
        """
        results_by_file: dict[str, list[GremlinResult]] = defaultdict(list)
        for result in score.results:
            results_by_file[result.gremlin.file_path].append(result)

        files: dict[str, StrykerFileResult] = {}
        for file_path, results in results_by_file.items():
            source = self._source_reader(file_path)
            source_lines = LINE_BREAK.split(source) if source else []
            files[file_path] = {
                'language': 'python',
                'source': source,
                'mutants': [self._build_mutant(r, source_lines) for r in results],
            }
        return files

    def _build_mutant(self, result: GremlinResult, source_lines: list[str]) -> StrykerMutant:
        """Build a single mutant entry.

        Args:
            result: The GremlinResult to convert.
            source_lines: Lines of the mutated file, used to convert byte columns to UTF-16 columns.

        Returns:
            Dictionary representing this mutant in Stryker format.
        """
        gremlin = result.gremlin
        mutant: StrykerMutant = {
            'id': gremlin.gremlin_id,
            'mutatorName': gremlin.operator_name,
            'location': self._build_location(gremlin, source_lines),
            'status': STATUS_MAP[result.status],
            'description': gremlin.description,
        }

        if result.killing_test is not None:
            mutant['killedBy'] = [result.killing_test]

        if result.execution_time_ms is not None:
            mutant['duration'] = int(result.execution_time_ms)

        if result.error_output:
            # Truncate to 500 chars for Stryker (vs 2000 at capture sites) to keep
            # the JSON report size reasonable when many gremlins error.
            mutant['statusReason'] = result.error_output[:500]

        return mutant

    def _build_location(self, gremlin: Gremlin, source_lines: list[str]) -> StrykerLocation:
        """Build a schema location with 1-based start and end positions.

        Python AST columns are 0-based UTF-8 byte offsets and the schema's positions are
        1-based UTF-16 code unit columns, so each column is converted to UTF-16 units and
        shifted by one. The schema requires ``end``; a node without end information gets an
        empty range at its start.

        Args:
            gremlin: The Gremlin containing location information.
            source_lines: Lines of the mutated file, used to convert byte columns to UTF-16 columns.

        Returns:
            Location dictionary with start and end positions.
        """
        node = gremlin.original_node
        start: StrykerPosition = {
            'line': node.lineno,
            'column': utf16_column(source_lines, node.lineno, node.col_offset) + 1,
        }
        end: StrykerPosition = start
        if node.end_lineno is not None and node.end_col_offset is not None:
            end = {
                'line': node.end_lineno,
                'column': utf16_column(source_lines, node.end_lineno, node.end_col_offset) + 1,
            }
        return {'start': start, 'end': end}
