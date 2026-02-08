"""SonarQube generic issue exporter for mutation testing results.

Exports surviving mutants as external issues that can be imported into
SonarQube using the sonar.externalIssuesReportPaths parameter.

See: https://docs.sonarsource.com/sonarqube/latest/analyzing-source-code/importing-external-issues/generic-issue-import-format/
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pytest_gremlins.reporting.results import GremlinResultStatus


if TYPE_CHECKING:
    from pathlib import Path

    from pytest_gremlins.reporting.results import GremlinResult
    from pytest_gremlins.reporting.score import MutationScore


class SonarQubeExporter:
    """Exporter that produces SonarQube generic issue format JSON.

    Only surviving mutants are exported as issues since they represent
    gaps in test coverage that SonarQube should track.

    Usage with SonarQube:
        sonar-scanner -Dsonar.externalIssuesReportPaths=mutation-sonar.json

    Example:
        >>> from pytest_gremlins.reporting.score import MutationScore
        >>> exporter = SonarQubeExporter()
        >>> # json_str = exporter.to_json(score)
    """

    def __init__(
        self,
        project_root: str | None = None,
        severity: str = 'MAJOR',
        effort_minutes: int = 10,
    ) -> None:
        """Initialize the exporter.

        Args:
            project_root: Optional project root path to strip from file paths.
            severity: Issue severity (BLOCKER, CRITICAL, MAJOR, MINOR, INFO).
            effort_minutes: Estimated effort to fix each issue in minutes.
        """
        self._project_root = project_root.rstrip('/') if project_root else None
        self._severity = severity
        self._effort_minutes = effort_minutes

    def to_json(self, score: MutationScore) -> str:
        """Convert mutation score to SonarQube generic issue format.

        Args:
            score: The MutationScore to convert.

        Returns:
            JSON string in SonarQube generic issue format.
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
            Dictionary in SonarQube generic issue format.
        """
        issues = [
            self._build_issue(result) for result in score.results if result.status == GremlinResultStatus.SURVIVED
        ]
        return {'issues': issues}

    def _build_issue(self, result: GremlinResult) -> dict[str, Any]:
        """Build a single issue entry for a surviving mutant.

        Args:
            result: The GremlinResult to convert.

        Returns:
            Dictionary representing this issue.
        """
        gremlin = result.gremlin
        file_path = self._normalize_path(gremlin.file_path)

        return {
            'engineId': 'pytest-gremlins',
            'ruleId': f'mutant-survived-{gremlin.operator_name}',
            'severity': self._severity,
            'type': 'CODE_SMELL',
            'effortMinutes': self._effort_minutes,
            'primaryLocation': {
                'filePath': file_path,
                'textRange': {
                    'startLine': gremlin.line_number,
                },
                'message': f'Mutant survived: {gremlin.description}',
            },
        }

    def _normalize_path(self, file_path: str) -> str:
        """Normalize file path, stripping project root if configured.

        Args:
            file_path: The file path to normalize.

        Returns:
            Normalized relative path.
        """
        if self._project_root and file_path.startswith(self._project_root):
            return file_path[len(self._project_root) :].lstrip('/')
        return file_path
