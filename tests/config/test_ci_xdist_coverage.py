"""The CI Test job's coverage must include the code its xdist workers run (issue #1016).

ci.yml runs ``coverage run -m pytest ... -n auto`` with ``COVERAGE_PROCESS_START=pyproject.toml``. The tests run in the
xdist workers, not in the controller that ``coverage run`` measures, so the workers must write coverage data too, or
the report only holds what the controller ran and ``fail_under`` fails.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

REPO_ROOT = Path(__file__).parents[2]

_SAMPLE = 'def double(value):\n    result = value * 2\n    return result\n'
_TEST = 'from sample import double\n\n\ndef test_double():\n    assert double(2) == 4\n'
# What tests/parallel/test_process_tree_coverage_pragmas.py does: build a private Coverage object in the process that
# runs the test, here an xdist worker. Coverage then stops that worker from saving its data unless the environment
# says otherwise.
_TEST_OWN_COVERAGE = (
    'import coverage\n\n\n'
    'def test_reads_the_config():\n'
    "    cov = coverage.Coverage(data_file=None, config_file='pyproject.toml')\n"
    "    assert cov.get_option('run:branch') is not None\n"
)
_ENV_LINE = re.compile(r'^\s+(?P<name>[A-Z_]+): [\'"]?(?P<value>[^\'"\s#]+)[\'"]?\s*$')


def _ci_coverage_step_env() -> dict[str, str]:
    """Return the env entries of the ci.yml step that runs ``coverage run``, which the Test job's step is."""
    step = (
        (REPO_ROOT / '.github/workflows/ci.yml')
        .read_text(encoding='utf-8')
        .split('      - name: Run tests with coverage')[1]
    )
    env_block = step.split('        env:\n')[1].split('        run: |')[0]
    matches = (_ENV_LINE.match(line) for line in env_block.splitlines())
    return {match['name']: match['value'] for match in matches if match}


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        return '[' + ', '.join(_toml_value(item) for item in value) + ']'
    return repr(str(value)).replace("'", '"')


def _repo_coverage_run_section() -> str:
    run = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['tool']['coverage']['run']
    kept = {key: value for key, value in run.items() if key not in {'source', 'omit'}}
    lines = [f'{key} = {_toml_value(value)}' for key, value in kept.items()]
    return '[tool.coverage.run]\nsource = ["sample"]\n' + '\n'.join(lines) + '\n'


@pytest.mark.medium
class DescribeCiXdistCoverage:
    def it_records_the_lines_an_xdist_worker_runs_when_a_test_builds_its_own_coverage_object(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / 'pyproject.toml').write_text(_repo_coverage_run_section(), encoding='utf-8')
        (tmp_path / 'sample.py').write_text(_SAMPLE, encoding='utf-8')
        (tmp_path / 'test_sample.py').write_text(_TEST, encoding='utf-8')
        (tmp_path / 'test_own_coverage.py').write_text(_TEST_OWN_COVERAGE, encoding='utf-8')
        inherited = {name: value for name, value in os.environ.items() if name != 'COVERAGE_COVERAGE'}
        env = {**inherited, **_ci_coverage_step_env(), 'COVERAGE_PROCESS_START': 'pyproject.toml', 'PYTHONPATH': '.'}
        env.pop('COVERAGE_RCFILE', None)
        coverage_command = [sys.executable, '-m', 'coverage']
        coverage_run_options = ['-m', 'pytest', '-q', '-n', '1', '--dist', 'loadgroup', '-p', 'no:cacheprovider']
        measured = subprocess.run(
            [*coverage_command, 'run', *coverage_run_options],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = subprocess.run(
            [*coverage_command, 'combine', '--quiet'],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        report = subprocess.run(
            [*coverage_command, 'report', '--fail-under=0', '--format=total'],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert (measured.returncode, report.returncode, report.stdout.strip()) == (0, 0, '100'), (
            f'coverage run: {measured.stdout}{measured.stderr}\n'
            f'coverage combine: {combined.stdout}{combined.stderr}\n'
            f'coverage report: {report.stdout}{report.stderr}'
        )
