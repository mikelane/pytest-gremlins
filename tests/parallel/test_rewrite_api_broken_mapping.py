"""A run aborted because pytest's assert-rewrite API changed reports why, even when the child's stderr is lost (#617).

The child ends with ``os._exit`` while pytest captures its stderr, so the explanation it writes never leaves the
process. The parent recognises the exit code and states the cause itself.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys
from unittest.mock import create_autospec

import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.instrumentation import origin_finder
from pytest_gremlins.instrumentation.gremlin import Gremlin
from pytest_gremlins.parallel import pool
from pytest_gremlins.parallel.exit_codes import REWRITE_API_BROKEN_EXIT_CODE
from pytest_gremlins.parallel.lightweight import describe_runner_error
from pytest_gremlins.plugin import (
    GremlinSession,
    _cache_gremlin_result,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)
from pytest_gremlins.verdicts import (
    _test_gremlin,
)

EXPLANATION = f'pytest-gremlins: assertion rewriting is unavailable with pytest {pytest.__version__}'
EXIT_SILENTLY = [sys.executable, '-c', f'import os; os._exit({REWRITE_API_BROKEN_EXIT_CODE})']


def _gremlin() -> Gremlin:
    return Gremlin(
        gremlin_id='g001',
        file_path='/path/to/source.py',
        line_number=42,
        original_node=ast.parse('x > 0').body[0].value,  # type: ignore[attr-defined]
        mutated_node=ast.parse('x >= 0').body[0].value,  # type: ignore[attr-defined]
        operator_name='ComparisonOperatorSwap',
        description='> to >=',
    )


@pytest.mark.small
class DescribeRewriteApiBrokenExitCode:
    """The bootstrap and the parent agree on one code that no other outcome uses."""

    def it_is_the_code_the_loader_exits_with(self) -> None:
        assert origin_finder.REWRITE_API_BROKEN_EXIT_CODE == REWRITE_API_BROKEN_EXIT_CODE

    @pytest.mark.parametrize('taken_code', [*range(6), 70, 71])
    def it_differs_from_every_code_with_another_meaning(self, taken_code: int) -> None:
        assert taken_code != REWRITE_API_BROKEN_EXIT_CODE


@pytest.mark.small
class DescribeDescribeRunnerErrorForABrokenRewriteApi:
    """The parent explains the abort without relying on the child's stderr."""

    def it_names_the_pytest_version_when_the_child_wrote_nothing(self) -> None:
        assert describe_runner_error(REWRITE_API_BROKEN_EXIT_CODE, b'').startswith(EXPLANATION)

    def it_keeps_what_the_child_wrote(self) -> None:
        assert 'TypeError: changed' in describe_runner_error(REWRITE_API_BROKEN_EXIT_CODE, b'TypeError: changed')


@pytest.mark.medium
class DescribeRewriteApiBrokenMapping:
    """A child that exits with the code scores ERROR with the explanation."""

    def it_maps_to_error_with_the_explanation_in_the_parallel_pool(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)

        result = pool._run_gremlin_test('g001', EXIT_SILENTLY, str(tmp_path), {}, timeout=30)

        assert result.status == GremlinResultStatus.ERROR
        assert result.error_output.startswith(EXPLANATION)

    def it_maps_to_error_with_the_explanation_in_the_sequential_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=['x'], returncode=REWRITE_API_BROKEN_EXIT_CODE, stdout=b'', stderr=b''
            )

        monkeypatch.setattr('pytest_gremlins.plugin.subprocess.run', fake_run)

        result = _test_gremlin(_gremlin(), ['pytest'], tmp_path, instrumented_dir=None, timeout=30)

        assert result.status == GremlinResultStatus.ERROR
        assert result.error_output.startswith(EXPLANATION)


@pytest.mark.medium
class DescribeCachingOfRewriteApiAborts:
    """An abort the user fixes by pinning pytest is not replayed from a warm cache."""

    def it_does_not_cache_the_abort(self, tmp_path: Path) -> None:
        cache = create_autospec(IncrementalCache, instance=True)
        session = GremlinSession(
            enabled=True,
            cache_enabled=True,
            cache=cache,
            source_hashes={'/path/to/source.py': 'hash'},
            instrumented_dir=tmp_path,
        )
        aborted = GremlinResult(
            gremlin=_gremlin(),
            status=GremlinResultStatus.ERROR,
            error_output=describe_runner_error(REWRITE_API_BROKEN_EXIT_CODE, b''),
        )

        _cache_gremlin_result(_gremlin(), [], aborted, session)

        cache.cache_result_deferred.assert_not_called()
