"""A failed pre-scan shard is reported once, with its cause, wherever the user is looking (issue #996)."""

from __future__ import annotations

from collections.abc import Iterator
import io
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

_CRASHING_SHARD_TEST = f'import os\n\n\ndef test_crash():\n    if {_IN_SHARD}:\n        os._exit(7)\n    assert True\n'

# A stand-in shard command that prints to stdout and exits 5, so no pytest runs inside the shard.
_FAILING_COMMAND = [sys.executable, '-c', 'import sys; print("STDOUT-MARKER"); sys.exit(5)']


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


def _run_failing_shard(tmp_path: Path) -> list[Path] | None:
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    return run_prescan_shards(
        _FAILING_COMMAND, [['t.py::t']], cwd=tmp_path, timeout=60, env=dict(os.environ), scratch_dir=scratch
    )


def _run_gremlins_with_a_crashing_shard(pytester: pytest.Pytester, *extra_args: str) -> pytest.RunResult:
    pytester.makepyfile(sample='def double(value):\n    return value * 2\n')
    pytester.makepyfile(test_a='from sample import double\n\n\ndef test_a():\n    assert double(2) == 4\n')
    pytester.makepyfile(test_b=_CRASHING_SHARD_TEST)
    return pytester.runpytest_subprocess(
        '--gremlins',
        '--gremlin-targets=sample.py',
        '--gremlin-operators=arithmetic',
        '--gremlin-prescan-workers=2',
        '-p',
        'no:cacheprovider',
        *extra_args,
    )


@pytest.fixture
def root_handler_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    yield stream
    root.removeHandler(handler)


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
class DescribeFailedShardRecord:
    def it_carries_the_exit_code_and_stdout_tail_to_caplog(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=sharded_prescan.__name__):
            data_files = _run_failing_shard(tmp_path)

        assert data_files is None
        assert 'shard 0 exited with code 5' in caplog.text
        assert 'STDOUT-MARKER' in caplog.text

    def it_reaches_a_handler_the_user_added_to_the_root_logger(
        self, tmp_path: Path, root_handler_stream: io.StringIO
    ) -> None:
        data_files = _run_failing_shard(tmp_path)

        assert data_files is None
        assert 'shard 0 exited with code 5' in root_handler_stream.getvalue()

    def it_prints_the_failure_line_to_stderr_once(self, tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
        data_files = _run_failing_shard(tmp_path)

        assert data_files is None
        assert capfd.readouterr().err.count('shard 0 exited with code 5') == 1


@pytest.mark.medium
class DescribeFailedShardInAGremlinsRun:
    @pytest.mark.parametrize(
        'extra_args',
        [
            pytest.param((), id='default'),
            pytest.param(('-p', 'no:logging'), id='logging-plugin-disabled'),
        ],
    )
    def it_prints_the_failed_shard_and_its_exit_code_to_stderr_exactly_once(
        self, pytester: pytest.Pytester, extra_args: tuple[str, ...]
    ) -> None:
        result = _run_gremlins_with_a_crashing_shard(pytester, *extra_args)

        assert result.stderr.str().count('shard 1 exited with code 7') == 1
        assert result.stdout.str().count('shard 1 exited with code 7') == 0
