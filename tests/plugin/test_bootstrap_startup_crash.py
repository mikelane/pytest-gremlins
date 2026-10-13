"""Adversarial QA (issue #656): a gremlin subprocess that never reached its tests must never score as a kill."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from pytest_gremlins.parallel.lightweight import describe_runner_error
from pytest_gremlins.plugin import _get_bootstrap_script

PASSING_TEST = 'def test_ok():\n    pass\n'
# pytest registers _pytest.logging as 'logging'; loading it again by module name hits pluggy's ValueError.
ALREADY_REGISTERED_PLUGIN = '_pytest.logging'
FAILS_ON_IMPORT = 'import pytest\n\npytest.fail("plugin refuses this configuration", pytrace=False)\n'
FAILS_IN_STARTUP_HOOK = (
    'import pytest\n\n'
    'def pytest_load_initial_conftests(early_config, parser, args):\n'
    '    pytest.fail("plugin refuses this configuration", pytrace=False)\n'
)


def _run_bootstrap(project: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    scratch = project.parent
    sources_file = scratch / 'sources.json'
    sources_file.write_text('{}', encoding='utf-8')
    bootstrap = scratch / 'gremlin_bootstrap.py'
    bootstrap.write_text(_get_bootstrap_script(), encoding='utf-8')
    excluded = {'PYTHONPATH', 'COVERAGE_PROCESS_START', 'PYTEST_PLUGINS'}
    environment = {key: value for key, value in os.environ.items() if key not in excluded}
    environment['PYTEST_GREMLINS_SOURCES_FILE'] = str(sources_file)
    environment['PYTHONPATH'] = str(project)
    return subprocess.run(
        [sys.executable, '-P', str(bootstrap), '-p', 'no:cacheprovider', '-o', 'addopts=', '-q', *args],
        cwd=project,
        env=environment,
        capture_output=True,
        timeout=120,
        check=False,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Return a throwaway project directory holding one passing test."""
    directory = tmp_path / 'project'
    directory.mkdir()
    (directory / 'test_sample.py').write_text(PASSING_TEST, encoding='utf-8')
    return directory


@pytest.mark.medium
class DescribeStartupCrashThatIsNotAnException:
    """``pytest.fail`` raises ``Failed``, a ``BaseException``; ``except Exception`` lets it end the interpreter at 1."""

    @pytest.mark.parametrize('plugin_source', [FAILS_ON_IMPORT, FAILS_IN_STARTUP_HOOK], ids=['import', 'hook'])
    def it_exits_with_the_internal_error_code(self, project: Path, plugin_source: str) -> None:
        (project / 'refusing_plugin.py').write_text(plugin_source, encoding='utf-8')

        completed = _run_bootstrap(project, '-p', 'refusing_plugin', 'test_sample.py')

        assert completed.returncode == pytest.ExitCode.INTERNAL_ERROR, completed.stderr.decode(errors='replace')


@pytest.mark.medium
class DescribeStartupCrashErrorOutput:
    """The parent keeps only part of stderr as the gremlin's error output; the exception line must survive."""

    def it_keeps_the_exception_message_of_a_plugin_registration_crash(self, project: Path) -> None:
        completed = _run_bootstrap(project, '-p', ALREADY_REGISTERED_PLUGIN, 'test_sample.py')

        error_output = describe_runner_error(completed.returncode, completed.stderr)

        assert 'Plugin already registered under a different name' in error_output
