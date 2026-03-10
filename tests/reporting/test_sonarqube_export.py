"""Tests for the SonarQube generic issue exporter.

SonarQube imports mutation testing results as external issues using
the generic issue import format. Only survived and uncovered mutants
are exported as they represent quality issues.

See: https://stryker-mutator.io/docs/mutation-testing-elements/sonarqube-integration/
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.reporting.results import GremlinResultStatus
from pytest_gremlins.reporting.score import MutationScore
from pytest_gremlins.reporting.sonarqube_export import SonarQubeExporter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class DescribeSonarQubeExporterOutput:
    """Tests for SonarQube generic issue format output."""

    def it_produces_valid_json(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        json_str = exporter.to_json(score)

        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def it_includes_issues_array(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))

        assert 'issues' in data
        assert isinstance(data['issues'], list)


@pytest.mark.small
class DescribeSonarQubeExporterFiltering:
    """Tests for filtering which mutants become issues."""

    def it_exports_survived_mutants(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))

        assert len(data['issues']) == 1

    def it_does_not_export_zapped_mutants(self, make_result):
        results = [make_result(GremlinResultStatus.ZAPPED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))

        assert len(data['issues']) == 0

    def it_does_not_export_timeout_mutants(self, make_result):
        results = [make_result(GremlinResultStatus.TIMEOUT)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))

        assert len(data['issues']) == 0

    def it_does_not_export_error_mutants(self, make_result):
        results = [make_result(GremlinResultStatus.ERROR)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))

        assert len(data['issues']) == 0

    def it_filters_mixed_results(self, make_result):
        results = [
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.ZAPPED),
            make_result(GremlinResultStatus.SURVIVED),
            make_result(GremlinResultStatus.TIMEOUT),
        ]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))

        assert len(data['issues']) == 2


@pytest.mark.small
class DescribeSonarQubeExporterIssueFormat:
    """Tests for individual issue format."""

    def it_issue_includes_engine_id(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))
        issue = data['issues'][0]

        assert issue['engineId'] == 'pytest-gremlins'

    def it_issue_includes_rule_id(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED, operator_name='comparison')]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))
        issue = data['issues'][0]

        assert issue['ruleId'] == 'mutant-survived-comparison'

    def it_issue_includes_severity(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))
        issue = data['issues'][0]

        assert issue['severity'] == 'MAJOR'

    def it_issue_includes_type(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))
        issue = data['issues'][0]

        assert issue['type'] == 'CODE_SMELL'

    def it_issue_includes_primary_location(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED, file_path='src/auth.py', line_number=42)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))
        issue = data['issues'][0]

        assert 'primaryLocation' in issue
        assert issue['primaryLocation']['filePath'] == 'src/auth.py'

    def it_issue_includes_text_range(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED, line_number=42)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))
        location = data['issues'][0]['primaryLocation']

        assert 'textRange' in location
        assert location['textRange']['startLine'] == 42

    def it_issue_includes_message(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED, description='>= to >')]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))
        location = data['issues'][0]['primaryLocation']

        assert 'message' in location
        assert '>= to >' in location['message']

    def it_issue_includes_effort_minutes(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()

        data = json.loads(exporter.to_json(score))
        issue = data['issues'][0]

        assert issue['effortMinutes'] == 10


@pytest.mark.medium
class DescribeSonarQubeExporterFileOutput:
    """Tests for writing SonarQube format to file."""

    def it_writes_to_file(self, make_result, tmp_path: Path):
        results = [make_result(GremlinResultStatus.SURVIVED)]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter()
        output_file = tmp_path / 'sonar-mutation.json'

        exporter.write_report(score, output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert 'issues' in data


@pytest.mark.small
class DescribeSonarQubeExporterProjectRoot:
    """Tests for project root path handling."""

    def it_strips_project_root_from_paths(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED, file_path='/home/user/project/src/auth.py')]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter(project_root='/home/user/project')

        data = json.loads(exporter.to_json(score))
        issue = data['issues'][0]

        assert issue['primaryLocation']['filePath'] == 'src/auth.py'

    def it_preserves_relative_paths_unchanged(self, make_result):
        results = [make_result(GremlinResultStatus.SURVIVED, file_path='src/auth.py')]
        score = MutationScore.from_results(results)
        exporter = SonarQubeExporter(project_root='/home/user/project')

        data = json.loads(exporter.to_json(score))
        issue = data['issues'][0]

        assert issue['primaryLocation']['filePath'] == 'src/auth.py'
