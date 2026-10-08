"""Adversarial QA (issue #485): a corrupt node ids file must score as an error, never as a kill."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.node_id_file import NODE_IDS_FILE_OPTION
from pytest_gremlins.plugin import _get_bootstrap_script

TESTS = """
def test_passes():
    assert True
"""


def _run_bootstrap(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    scratch = project.parent
    sources_file = scratch / 'sources.json'
    sources_file.write_text('{}', encoding='utf-8')
    bootstrap = scratch / 'gremlin_bootstrap.py'
    bootstrap.write_text(_get_bootstrap_script(), encoding='utf-8')
    excluded = {'PYTHONPATH', 'COVERAGE_PROCESS_START'}
    environment = {key: value for key, value in os.environ.items() if key not in excluded}
    environment['PYTEST_GREMLINS_SOURCES_FILE'] = str(sources_file)
    return subprocess.run(
        [sys.executable, '-P', str(bootstrap), '-p', 'no:cacheprovider', '-o', 'addopts=', '-q', *args],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.medium
class DescribeCorruptNodeIdsFile:
    def it_reports_a_deeply_nested_file_as_a_usage_error_not_as_a_kill(self, tmp_path: Path) -> None:
        project = tmp_path / 'project'
        project.mkdir()
        (project / 'test_sample.py').write_text(TESTS, encoding='utf-8')
        nested = tmp_path / 'node_ids_nested.json'
        nested.write_text('[' * 100_000 + ']' * 100_000, encoding='utf-8')

        completed = _run_bootstrap(project, f'{NODE_IDS_FILE_OPTION}={nested}')

        assert completed.returncode == pytest.ExitCode.USAGE_ERROR
