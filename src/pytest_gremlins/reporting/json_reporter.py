"""JSON reporter for gremlin mutation testing results.

Produces machine-readable JSON output for CI integration
and automated analysis of mutation testing results.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.reporting.results import GremlinResult
    from pytest_gremlins.reporting.score import MutationScore


class JsonReporter:
    """Reporter that produces JSON output for CI integration.

    JSON structure:
        {
            "summary": {
                "total": 10,
                "zapped": 8,
                "survived": 2,
                "timeout": 0,
                "error": 0,
                "percentage": 80.0
            },
            "files": {
                "auth.py": {"total": 5, "zapped": 4, "survived": 1, "percentage": 80.0},
                "utils.py": {"total": 5, "zapped": 4, "survived": 1, "percentage": 80.0}
            },
            "results": [
                {
                    "gremlin_id": "g001",
                    "file_path": "auth.py",
                    "line_number": 42,
                    "status": "zapped",
                    "operator": "comparison",
                    "description": ">= to >",
                    "killing_test": "test_auth"
                },
                ...
            ]
        }
    """

    def to_json(self, score: MutationScore) -> str:
        """Convert mutation score to JSON string.

        Args:
            score: The MutationScore to convert.

        Returns:
            Pretty-printed JSON string.
        """
        data = self._build_report_data(score)
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
            Dictionary suitable for JSON serialization.
        """
        return {
            'summary': self._build_summary(score),
            'files': self._build_file_breakdown(score),
            'results': [self._build_result(r) for r in score.results],
        }

    def _build_summary(self, score: MutationScore) -> dict[str, Any]:
        """Build the summary section.

        Args:
            score: The MutationScore to summarize.

        Returns:
            Summary dictionary.
        """
        return {
            'total': score.total,
            'zapped': score.zapped,
            'survived': score.survived,
            'timeout': score.timeout,
            'error': score.error,
            'percentage': score.percentage,
        }

    def _build_file_breakdown(self, score: MutationScore) -> dict[str, dict[str, Any]]:
        """Build per-file breakdown section.

        Args:
            score: The MutationScore to break down.

        Returns:
            Dictionary mapping file paths to their stats.
        """
        file_scores = score.by_file()
        return {
            file_path: {
                'total': file_score.total,
                'zapped': file_score.zapped,
                'survived': file_score.survived,
                'percentage': file_score.percentage,
            }
            for file_path, file_score in file_scores.items()
        }

    def _build_result(self, result: GremlinResult) -> dict[str, Any]:
        """Build a single result entry.

        Args:
            result: The GremlinResult to convert.

        Returns:
            Dictionary representing this result.
        """
        gremlin = result.gremlin
        entry: dict[str, Any] = {
            'gremlin_id': gremlin.gremlin_id,
            'file_path': gremlin.file_path,
            'line_number': gremlin.line_number,
            'status': result.status.value,
            'operator': gremlin.operator_name,
            'description': gremlin.description,
        }
        if result.killing_test is not None:
            entry['killing_test'] = result.killing_test
        return entry
