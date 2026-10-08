"""The gremlin bootstrap runs the node ids it finds in ``--gremlins-node-ids-file`` (issue #485).

pytest must receive the original arguments followed by the ids from the file, exactly as if the ids had
been on the command line, and the bootstrap must stay silent: a stray line on stderr in a child can turn
into a false verdict.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.node_id_file import (
    NODE_IDS_FILE_OPTION,
    write_node_ids_file,
)
from pytest_gremlins.plugin import _get_bootstrap_script

TESTS = """
def test_fails():
    assert False

def test_passes():
    assert True

def test_also_passes():
    assert True
"""

ARGUMENT_RECORDER = """
import json


def pytest_load_initial_conftests(early_config, parser, args):
    with open('recorded_args.json', 'w', encoding='utf-8') as recorded:
        json.dump(list(early_config.invocation_params.args), recorded)
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    directory = tmp_path / 'project'
    directory.mkdir()
    (directory / 'test_sample.py').write_text(TESTS, encoding='utf-8')
    (directory / 'argrecorder.py').write_text(ARGUMENT_RECORDER, encoding='utf-8')
    return directory


def _run_bootstrap(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    scratch = project.parent
    sources_file = scratch / 'sources.json'
    sources_file.write_text('{}', encoding='utf-8')
    bootstrap = scratch / 'gremlin_bootstrap.py'
    bootstrap.write_text(_get_bootstrap_script(), encoding='utf-8')
    environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    environment['PYTEST_GREMLINS_SOURCES_FILE'] = str(sources_file)
    environment['PYTHONPATH'] = str(project)
    return subprocess.run(
        [sys.executable, '-P', str(bootstrap), '-p', 'no:cacheprovider', '-o', 'addopts=', *args],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _node_ids_option(project: Path, *node_ids: str) -> str:
    return f'{NODE_IDS_FILE_OPTION}={write_node_ids_file(node_ids, project.parent)}'


@pytest.mark.medium
class DescribeBootstrapNodeIdsFile:
    def it_runs_only_the_node_ids_in_the_file(self, project: Path) -> None:
        option = _node_ids_option(project, 'test_sample.py::test_passes')

        completed = _run_bootstrap(project, '-q', '--tb=no', option)

        assert completed.returncode == 0
        assert '1 passed' in completed.stdout

    def it_runs_a_failing_id_from_the_file(self, project: Path) -> None:
        option = _node_ids_option(project, 'test_sample.py::test_passes', 'test_sample.py::test_fails')

        completed = _run_bootstrap(project, '-q', '--tb=no', option)

        assert completed.returncode == pytest.ExitCode.TESTS_FAILED

    def it_runs_the_ids_in_the_order_of_the_file(self, project: Path) -> None:
        option = _node_ids_option(project, 'test_sample.py::test_also_passes', 'test_sample.py::test_passes')

        completed = _run_bootstrap(project, '--collect-only', '-q', option)

        assert completed.stdout.splitlines()[:2] == ['test_sample.py::test_also_passes', 'test_sample.py::test_passes']

    def it_hands_pytest_the_original_arguments_followed_by_the_ids(self, project: Path) -> None:
        option = _node_ids_option(project, 'test_sample.py::test_passes', 'test_sample.py::test_also_passes')

        _run_bootstrap(project, '-x', '--tb=no', '-p', 'argrecorder', option, '-q')

        recorded = json.loads((project / 'recorded_args.json').read_text(encoding='utf-8'))
        assert recorded == [
            '-p',
            'no:cacheprovider',
            '-o',
            'addopts=',
            '-x',
            '--tb=no',
            '-p',
            'argrecorder',
            '-q',
            'test_sample.py::test_passes',
            'test_sample.py::test_also_passes',
        ]

    def it_never_shows_pytest_the_option(self, project: Path) -> None:
        option = _node_ids_option(project, 'test_sample.py::test_passes')

        completed = _run_bootstrap(project, '-q', '--tb=no', option)

        assert NODE_IDS_FILE_OPTION not in completed.stdout + completed.stderr

    def it_stays_silent_on_stderr(self, project: Path) -> None:
        option = _node_ids_option(project, 'test_sample.py::test_passes')

        assert _run_bootstrap(project, '-q', '--tb=no', option).stderr == ''

    def it_still_accepts_node_ids_on_the_command_line(self, project: Path) -> None:
        completed = _run_bootstrap(project, '-q', '--tb=no', 'test_sample.py::test_passes')

        assert completed.returncode == 0

    def it_reports_an_unreadable_file_as_a_usage_error_not_as_a_kill(self, project: Path) -> None:
        completed = _run_bootstrap(project, '-q', f'{NODE_IDS_FILE_OPTION}={project / "gone.json"}')

        assert completed.returncode == pytest.ExitCode.USAGE_ERROR
        assert 'gone.json' in completed.stderr
