"""The bootstrap reports a suite that failed to load through a dedicated exit code (issue #550).

A mutant can stop pytest from running anything: a conftest import fails, a test module fails to
collect, or a parametrize id changes so the selected node id no longer exists. pytest exits 4 (or 2)
for all of these, which is also what pytest-gremlins' own bad arguments produce. The bootstrap tells
the two apart in-process, so the parent never has to parse pytest's output.
"""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.control_run import UNATTRIBUTABLE_MARKER
from pytest_gremlins.instrumentation.origin_finder import normalize_origin
from pytest_gremlins.parallel.exit_codes import GREMLIN_COLLECTION_FAILED_EXIT_CODE
from pytest_gremlins.plugin import _get_bootstrap_script

RunBootstrap = Callable[..., int]
RunBootstrapProcess = Callable[..., 'subprocess.CompletedProcess[bytes]']

PASSING_TEST = 'def test_ok():\n    pass\n'
RAISES_ON_IMPORT = 'raise RuntimeError("mutant broke the import")\n'
# pytest registers _pytest.logging as 'logging'; loading it again by module name hits pluggy's ValueError.
ALREADY_REGISTERED_PLUGIN = '_pytest.logging'
PARAMETRIZED_TEST = 'import pytest\n\n@pytest.mark.parametrize("level", [1, 2])\ndef test_level(level):\n    pass\n'


@pytest.fixture
def run_bootstrap_process(tmp_path: Path) -> RunBootstrapProcess:
    """Return a runner executing the generated bootstrap script, with the sources file under the test's control."""
    bootstrap = tmp_path / 'gremlin_bootstrap.py'
    bootstrap.write_text(_get_bootstrap_script())
    project = tmp_path / 'project'
    project.mkdir()

    def run(
        *args: str, sources: str | None = '{}', files: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        for name, content in (files or {}).items():
            (project / name).write_text(content)
        environment = {
            key: value for key, value in os.environ.items() if key not in ('PYTHONPATH', 'PYTEST_GREMLINS_SOURCES_FILE')
        }
        if sources is not None:
            sources_file = tmp_path / 'sources.json'
            sources_file.write_text(sources)
            environment['PYTEST_GREMLINS_SOURCES_FILE'] = str(sources_file)
        return subprocess.run(
            [sys.executable, '-P', str(bootstrap), *args],
            cwd=project,
            env=environment,
            capture_output=True,
            timeout=120,
            check=False,
        )

    return run


@pytest.fixture
def run_bootstrap(run_bootstrap_process: RunBootstrapProcess) -> RunBootstrap:
    """Return a runner executing the bootstrap against a throwaway project and returning its exit code."""

    def run(files: dict[str, str], *args: str) -> int:
        quiet_args = ('-p', 'no:cacheprovider', '--tb=no', '-q', '-o', 'addopts=', *args)
        return run_bootstrap_process(*quiet_args, files=files).returncode

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

    def it_reports_a_plugin_registration_crash_as_an_internal_error(self, run_bootstrap: RunBootstrap) -> None:
        exit_code = run_bootstrap({'test_sample.py': PASSING_TEST}, '-p', ALREADY_REGISTERED_PLUGIN, 'test_sample.py')

        assert exit_code == pytest.ExitCode.INTERNAL_ERROR

    def it_prints_the_traceback_of_a_startup_crash_to_stderr(self, run_bootstrap_process: RunBootstrapProcess) -> None:
        completed = run_bootstrap_process('-p', ALREADY_REGISTERED_PLUGIN)

        assert b'Plugin already registered under a different name' in completed.stderr

    def it_reports_a_missing_sources_file_variable_as_a_usage_error(
        self, run_bootstrap_process: RunBootstrapProcess
    ) -> None:
        completed = run_bootstrap_process(sources=None)

        assert completed.returncode == pytest.ExitCode.USAGE_ERROR

    def it_reports_an_unreadable_sources_file_as_an_internal_error(
        self, run_bootstrap_process: RunBootstrapProcess
    ) -> None:
        completed = run_bootstrap_process(sources='not json')

        assert completed.returncode == pytest.ExitCode.INTERNAL_ERROR

    def it_keeps_a_passing_run_at_exit_0(self, run_bootstrap: RunBootstrap) -> None:
        assert run_bootstrap({'test_sample.py': PASSING_TEST}, 'test_sample.py::test_ok') == 0

    def it_keeps_a_failing_test_at_exit_1(self, run_bootstrap: RunBootstrap) -> None:
        failing = 'def test_ok():\n    assert False\n'

        assert run_bootstrap({'test_sample.py': failing}, 'test_sample.py::test_ok') == 1


@pytest.mark.medium
class DescribeBootstrapWhenLoadFailuresCannotBeAttributed:
    """A failed unmutated control run withdraws the collection-failed signal."""

    def it_keeps_pytests_exit_code_for_a_conftest_that_fails_to_import(
        self, run_bootstrap: RunBootstrap, tmp_path: Path
    ) -> None:
        (tmp_path / UNATTRIBUTABLE_MARKER).write_text('')

        exit_code = run_bootstrap(
            {'conftest.py': RAISES_ON_IMPORT, 'test_sample.py': PASSING_TEST},
            'test_sample.py::test_ok',
        )

        assert exit_code == pytest.ExitCode.USAGE_ERROR

    def it_keeps_pytests_exit_code_for_a_node_id_that_no_longer_exists(
        self, run_bootstrap: RunBootstrap, tmp_path: Path
    ) -> None:
        (tmp_path / UNATTRIBUTABLE_MARKER).write_text('')

        exit_code = run_bootstrap({'test_sample.py': PARAMETRIZED_TEST}, 'test_sample.py::test_level[3]')

        assert exit_code == pytest.ExitCode.USAGE_ERROR


@pytest.mark.medium
class DescribeBootstrapInstrumentsModulesPytestImports:
    """pytest must not be imported before the origin finder is installed (issue #656 review)."""

    def it_serves_a_module_pytest_imports_at_startup_from_the_instrumented_sources(
        self, run_bootstrap_process: RunBootstrapProcess
    ) -> None:
        origin = Path(importlib.util.find_spec('iniconfig').origin)  # type: ignore[union-attr, arg-type]
        instrumented = origin.read_text(encoding='utf-8') + '\nINSTRUMENTED_MARKER = True\n'
        entry = {'source': instrumented, 'origin': str(origin), 'tree': None}
        sources = json.dumps({normalize_origin(str(origin)): entry})
        probe = 'import iniconfig\n\ndef test_marker():\n    assert iniconfig.INSTRUMENTED_MARKER\n'

        completed = run_bootstrap_process(
            '-p', 'no:cacheprovider', '-o', 'addopts=', 'test_probe.py', sources=sources, files={'test_probe.py': probe}
        )

        assert completed.returncode == 0, completed.stdout.decode()
