"""Adversarial QA (issue #996): a failed pre-scan shard's diagnostic must carry the cause, where users can see it."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

import pytest

from pytest_gremlins.coverage import sharded_prescan
from pytest_gremlins.coverage.sharded_prescan import run_prescan_shards

_IN_SHARD = "os.environ.get('COVERAGE_FILE', '').endswith('coverage.data')"

_PASSING_TEST = 'def test_ok():\n    assert True\n'

# pytest reports both of these on stdout, not stderr: a collection error in the shard's test module, and an
# INTERNALERROR raised by a hook. They are the shard failures that exit with 2/3/4, the codes the fix targets.
_COLLECTION_ERROR_MODULE = f'import os\nif {_IN_SHARD}:\n    raise RuntimeError("COLLECT-MARKER")\n\n\n{_PASSING_TEST}'
_INTERNAL_ERROR_CONFTEST = (
    f'import os\n\n\ndef pytest_collection_modifyitems(items):\n    if {_IN_SHARD}:\n'
    '        raise RuntimeError("INTERNAL-MARKER")\n'
)

_CRASHING_SHARD_TEST = (
    f'import os\nimport sys\n\n\ndef test_crash():\n    if {_IN_SHARD}:\n        os._exit(7)\n    assert True\n'
)


def _run_real_shard(tmp_path: Path) -> list[Path] | None:
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    env = {key: value for key, value in os.environ.items() if key not in {'PYTEST_ADDOPTS', 'COVERAGE_FILE'}}
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    return run_prescan_shards(
        [sys.executable, '-m', 'pytest_gremlins.coverage.prescan_main', f'--rootdir={tmp_path}', '-q', '--tb=no'],
        [['test_target.py::test_ok']],
        cwd=tmp_path,
        timeout=120,
        env=env,
        scratch_dir=scratch,
    )


@pytest.mark.medium
class DescribeFailedShardDiagnostic:
    @pytest.mark.parametrize(
        ('file_name', 'content', 'marker'),
        [
            pytest.param('test_target.py', _COLLECTION_ERROR_MODULE, 'COLLECT-MARKER', id='collection-error'),
            pytest.param('conftest.py', _INTERNAL_ERROR_CONFTEST, 'INTERNAL-MARKER', id='internal-error'),
        ],
    )
    def it_logs_the_error_pytest_reported_for_a_failed_shard(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, file_name: str, content: str, marker: str
    ) -> None:
        (tmp_path / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
        (tmp_path / 'test_target.py').write_text(_PASSING_TEST, encoding='utf-8')
        (tmp_path / file_name).write_text(content, encoding='utf-8')

        with caplog.at_level(logging.WARNING, logger=sharded_prescan.__name__):
            data_files = _run_real_shard(tmp_path)

        assert data_files is None
        assert marker in caplog.text


@pytest.mark.medium
class DescribeFailedShardVisibility:
    def it_shows_the_failed_shard_and_its_exit_code_in_a_default_gremlins_run(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(sample='def double(value):\n    return value * 2\n')
        pytester.makepyfile(test_a='from sample import double\n\n\ndef test_a():\n    assert double(2) == 4\n')
        pytester.makepyfile(test_b=_CRASHING_SHARD_TEST)

        result = pytester.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=arithmetic',
            '--gremlin-prescan-workers=2',
            '-p',
            'no:cacheprovider',
        )

        assert 'exited with code 7' in result.stdout.str() + result.stderr.str()
