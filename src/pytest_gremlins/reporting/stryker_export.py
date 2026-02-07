"""Stryker Dashboard JSON exporter for mutation testing results.

Exports pytest-gremlins results in the mutation-testing-report-schema format
used by the Stryker Dashboard and compatible tools.

See: https://github.com/stryker-mutator/mutation-testing-elements
"""

from __future__ import annotations

from collections import defaultdict
import json
from typing import TYPE_CHECKING, Any, cast

import pytest_gremlins
from pytest_gremlins.reporting.results import GremlinResultStatus


if TYPE_CHECKING:
    import ast
    from pathlib import Path

    from pytest_gremlins.instrumentation.gremlin import Gremlin
    from pytest_gremlins.reporting.results import GremlinResult
    from pytest_gremlins.reporting.score import MutationScore


STATUS_MAP: dict[GremlinResultStatus, str] = {
    GremlinResultStatus.ZAPPED: 'Killed',
    GremlinResultStatus.SURVIVED: 'Survived',
    GremlinResultStatus.TIMEOUT: 'Timeout',
    GremlinResultStatus.ERROR: 'RuntimeError',
}


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

    def __init__(self, thresholds: dict[str, int] | None = None) -> None:
        """Initialize the exporter with optional thresholds.

        Args:
            thresholds: Optional dict with 'high' and 'low' score thresholds.
                        Defaults to high=80, low=60.
        """
        self._thresholds = thresholds or {'high': 80, 'low': 60}

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

    def _build_report_data(self, score: MutationScore) -> dict[str, Any]:
        """Build the complete report data structure.

        Args:
            score: The MutationScore to convert.

        Returns:
            Dictionary conforming to mutation-testing-report-schema.
        """
        return {
            'schemaVersion': '1.0',
            'thresholds': self._thresholds,
            'files': self._build_files(score),
            'framework': {
                'name': 'pytest-gremlins',
                'version': pytest_gremlins.__version__,
            },
        }

    def _build_files(self, score: MutationScore) -> dict[str, dict[str, Any]]:
        """Build the files section grouping mutants by file.

        Args:
            score: The MutationScore containing results.

        Returns:
            Dictionary mapping file paths to file data with mutants.
        """
        results_by_file: dict[str, list[GremlinResult]] = defaultdict(list)
        for result in score.results:
            results_by_file[result.gremlin.file_path].append(result)

        return {
            file_path: {
                'language': 'python',
                'mutants': [self._build_mutant(r) for r in results],
            }
            for file_path, results in results_by_file.items()
        }

    def _build_mutant(self, result: GremlinResult) -> dict[str, Any]:
        """Build a single mutant entry.

        Args:
            result: The GremlinResult to convert.

        Returns:
            Dictionary representing this mutant in Stryker format.
        """
        gremlin = result.gremlin
        mutant: dict[str, Any] = {
            'id': gremlin.gremlin_id,
            'mutatorName': gremlin.operator_name,
            'location': self._build_location(gremlin),
            'status': STATUS_MAP[result.status],
            'description': gremlin.description,
        }

        if result.killing_test is not None:
            mutant['killedBy'] = [result.killing_test]

        if result.execution_time_ms is not None:
            mutant['duration'] = int(result.execution_time_ms)

        return mutant

    def _build_location(self, gremlin: Gremlin) -> dict[str, Any]:
        """Build location object from gremlin's AST node.

        Args:
            gremlin: The Gremlin containing location information.

        Returns:
            Location dictionary with start and optionally end positions.
        """
        node = cast('ast.expr', gremlin.original_node)
        location: dict[str, Any] = {
            'start': {
                'line': node.lineno,
                'column': node.col_offset,
            },
        }

        if node.end_lineno is not None:
            location['end'] = {
                'line': node.end_lineno,
                'column': node.end_col_offset,
            }

        return location
