"""The runner's "cannot verify" exit code must map to ERROR at every call site, never ZAPPED."""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel import (
    persistent_pool,
    pool,
)
from pytest_gremlins.parallel.lightweight import (
    LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE,
    describe_runner_error,
)
from pytest_gremlins.plugin import _test_gremlin
from pytest_gremlins.reporting.results import GremlinResultStatus

REASON = 'test requires arguments (fixtures or parametrization)'
EXIT_WITH_REASON = [
    sys.executable,
    '-c',
    f'import sys; sys.stderr.write({REASON!r}); sys.exit({LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE})',
]


@pytest.mark.small
class DescribeDescribeRunnerError:
    """The helper names the runner so a user can tell the verdict was withheld."""

    def it_prefixes_the_cannot_verify_exit_code_with_an_explanation(self) -> None:
        message = describe_runner_error(LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE, REASON.encode())

        assert message.startswith('lightweight runner could not verify')
        assert REASON in message

    @pytest.mark.parametrize('exit_code', [2, 3, 4, 5, 139])
    def it_returns_plain_stderr_for_other_exit_codes(self, exit_code: int) -> None:
        assert describe_runner_error(exit_code, b'boom') == 'boom'

    def it_truncates_long_stderr(self) -> None:
        assert len(describe_runner_error(2, b'x' * 5000)) == 2000

    def it_handles_empty_stderr(self) -> None:
        assert describe_runner_error(LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE, b'').startswith('lightweight runner')


@pytest.fixture
def sample_gremlin() -> Gremlin:
    return Gremlin(
        gremlin_id='g001',
        file_path='/path/to/source.py',
        line_number=42,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


@pytest.mark.medium
class DescribeCannotVerifyMapping:
    """ERROR with the runner's reason, at all three subprocess call sites."""

    def it_maps_to_error_in_the_sequential_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        sample_gremlin: Gremlin,
    ) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=['x'], returncode=LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE, stdout=b'', stderr=REASON.encode()
            )

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(sample_gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert result.status == GremlinResultStatus.ERROR
        assert 'lightweight runner could not verify' in result.error_output
        assert REASON in result.error_output

    def it_maps_to_error_in_the_parallel_pool(self, tmp_path: Path) -> None:
        result = pool._run_gremlin_test('g001', EXIT_WITH_REASON, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ERROR
        assert 'lightweight runner could not verify' in result.error_output
        assert REASON in result.error_output

    def it_maps_to_error_in_the_persistent_pool(self, tmp_path: Path) -> None:
        result = persistent_pool._run_gremlin_test('g001', EXIT_WITH_REASON, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ERROR
        assert 'lightweight runner could not verify' in result.error_output
        assert REASON in result.error_output
