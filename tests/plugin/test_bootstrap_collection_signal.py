"""The bootstrap reports a suite that failed to load through a dedicated exit code (issue #550).

A mutant can stop pytest from running anything: a conftest import fails, a test module fails to
collect, or a parametrize id changes so the selected node id no longer exists. pytest exits 4 (or 2)
for all of these, which is also what pytest-gremlins' own bad arguments produce. The bootstrap tells
the two apart in-process, so the parent never has to parse pytest's output.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.parallel.exit_codes import GREMLIN_COLLECTION_FAILED_EXIT_CODE
from pytest_gremlins.plugin import _get_bootstrap_script

RunBootstrap = Callable[..., int]

PASSING_TEST = 'def test_ok():\n    pass\n'
RAISES_ON_IMPORT = 'raise RuntimeError("mutant broke the import")\n'
PARAMETRIZED_TEST = 'import pytest\n\n@pytest.mark.parametrize("level", [1, 2])\ndef test_level(level):\n    pass\n'


@pytest.fixture
def run_bootstrap(tmp_path: Path) -> RunBootstrap:
    """Return a runner executing the generated bootstrap script in a throwaway project."""
    sources_file = tmp_path / 'sources.json'
    sources_file.write_text('{}')
    bootstrap = tmp_path / 'gremlin_bootstrap.py'
    bootstrap.write_text(_get_bootstrap_script())
    project = tmp_path / 'project'
    project.mkdir()

    def run(files: dict[str, str], *args: str) -> int:
        for name, content in files.items():
            (project / name).write_text(content)
        environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        environment['PYTEST_GREMLINS_SOURCES_FILE'] = str(sources_file)
        completed = subprocess.run(
            [sys.executable, '-P', str(bootstrap), '-p', 'no:cacheprovider', '--tb=no', '-q', '-o', 'addopts=', *args],
            cwd=project,
            env=environment,
            capture_output=True,
            timeout=120,
            check=False,
        )
        return completed.returncode

    return run


@pytest.mark.medium
class DescribeBootstrapCollectionSignal:
    """Exit codes the bootstrap produces for each way a mutant can stop the suite from loading."""

    def it_signals_a_conftest_that_fails_to_import(self, run_bootstrap: RunBootstrap) -> None:
        exit_code = run_bootstrap(
            {'conftest.py': RAISES_ON_IMPORT, 'test_sample.py': PASSING_TEST},
            'test_sample.py::test_ok',
        )

        assert exit_code == GREMLIN_COLLECTION_FAILED_EXIT_CODE

    def it_signals_a_test_module_that_fails_to_collect_when_a_node_id_is_selected(
        self, run_bootstrap: RunBootstrap
    ) -> None:
        exit_code = run_bootstrap(
            {'test_sample.py': RAISES_ON_IMPORT + PASSING_TEST},
            'test_sample.py::test_ok',
        )

        assert exit_code == GREMLIN_COLLECTION_FAILED_EXIT_CODE

    def it_signals_a_test_module_that_fails_to_collect_when_the_file_is_selected(
        self, run_bootstrap: RunBootstrap
    ) -> None:
        exit_code = run_bootstrap(
            {'test_sample.py': RAISES_ON_IMPORT + PASSING_TEST},
            'test_sample.py',
        )

        assert exit_code == GREMLIN_COLLECTION_FAILED_EXIT_CODE

    def it_signals_a_selected_node_id_that_no_longer_exists(self, run_bootstrap: RunBootstrap) -> None:
        exit_code = run_bootstrap(
            {'test_sample.py': PARAMETRIZED_TEST},
            'test_sample.py::test_level[3]',
        )

        assert exit_code == GREMLIN_COLLECTION_FAILED_EXIT_CODE


@pytest.mark.medium
class DescribeBootstrapKeepsOurOwnFailuresDistinct:
    """pytest-gremlins' own mistakes and ordinary outcomes keep pytest's exit codes."""

    def it_keeps_an_unrecognized_argument_as_a_usage_error(self, run_bootstrap: RunBootstrap) -> None:
        exit_code = run_bootstrap({'test_sample.py': PASSING_TEST}, '--no-such-option', 'test_sample.py')

        assert exit_code == pytest.ExitCode.USAGE_ERROR

    def it_keeps_a_missing_test_file_as_a_usage_error(self, run_bootstrap: RunBootstrap) -> None:
        exit_code = run_bootstrap({'test_sample.py': PASSING_TEST}, 'test_gone.py::test_ok')

        assert exit_code == pytest.ExitCode.USAGE_ERROR

    def it_keeps_an_internal_error_as_an_internal_error(self, run_bootstrap: RunBootstrap) -> None:
        exit_code = run_bootstrap(
            {
                'conftest.py': 'def pytest_collection(session):\n    raise RuntimeError("our bug")\n',
                'test_sample.py': PASSING_TEST,
            },
            'test_sample.py::test_ok',
        )

        assert exit_code == pytest.ExitCode.INTERNAL_ERROR

    def it_keeps_a_passing_run_at_exit_0(self, run_bootstrap: RunBootstrap) -> None:
        assert run_bootstrap({'test_sample.py': PASSING_TEST}, 'test_sample.py::test_ok') == 0

    def it_keeps_a_failing_test_at_exit_1(self, run_bootstrap: RunBootstrap) -> None:
        failing = 'def test_ok():\n    assert False\n'

        assert run_bootstrap({'test_sample.py': failing}, 'test_sample.py::test_ok') == 1
