"""Keep secret-shaped environment variables out of failure output for the whole test session."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

_TESTS_CONFTEST = Path(__file__).resolve().parents[1] / 'conftest.py'
_FAKE_SECRET_VALUE = 'fake-secret-value-0123456789'  # noqa: S105  # pragma: allowlist secret

_FAILING_ENV_TEST = """
import os


def test_environment_is_empty():
    env = dict(os.environ)
    assert env == {}
"""


def _load_tests_conftest() -> ModuleType:
    spec = importlib.util.spec_from_file_location('_tests_conftest_under_test', _TESTS_CONFTEST)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tests_conftest = _load_tests_conftest()


@pytest.mark.small
class DescribeSecretEnvNames:
    @pytest.mark.parametrize(
        'name',
        [
            'GITHUB_TOKEN',
            'GH_TOKEN',
            'CODECOV_TOKEN',
            'MY_SERVICE_SECRET',
            'AWS_SECRET_ACCESS_KEY',
            'AWS_ACCESS_KEY_ID',
            'OPENAI_API_KEY',
            'DB_PASSWORD',
            'DB_PASS',
            'GOOGLE_CREDENTIALS',
            'PYPI_PASSWORD',
            'PYPI_API_TOKEN',
            'TWINE_PASSWORD',
            'TWINE_USERNAME',
            'FAKE_SECRET_TOKEN',
            'lowercase_api_key',
        ],
    )
    def it_flags_secret_shaped_names(self, name: str) -> None:
        assert tests_conftest._is_secret_env_name(name) is True

    @pytest.mark.parametrize(
        'name',
        [
            'PATH',
            'HOME',
            'PYTHONHASHSEED',
            'PYTHONPATH',
            'PYTEST_ADDOPTS',
            'PYTEST_CURRENT_TEST',
            'COVERAGE_PROCESS_START',
            'ACTIVE_GREMLIN',
            'PYTEST_GREMLINS_SOURCES_FILE',
            'SSH_AUTH_SOCK',
            'KEYBOARD_LAYOUT',
            'TOKENIZERS_PARALLELISM',
            'SECRETARY',
            'PASSTHROUGH',
        ],
    )
    def it_keeps_names_the_suite_or_tools_need(self, name: str) -> None:
        assert tests_conftest._is_secret_env_name(name) is False


@pytest.mark.small
class DescribeScrubSecretEnv:
    def it_removes_secret_entries_from_the_mapping(self) -> None:
        environ = {'GITHUB_TOKEN': 'abc', 'PATH': '/bin'}

        tests_conftest._scrub_secret_env(environ)

        assert environ == {'PATH': '/bin'}

    def it_returns_the_removed_entries_for_restoring(self) -> None:
        environ = {'GITHUB_TOKEN': 'abc', 'PATH': '/bin'}

        removed = tests_conftest._scrub_secret_env(environ)

        assert removed == {'GITHUB_TOKEN': 'abc'}

    def it_leaves_a_clean_mapping_untouched(self) -> None:
        environ = {'PATH': '/bin'}

        removed = tests_conftest._scrub_secret_env(environ)

        assert (environ, removed) == ({'PATH': '/bin'}, {})


@pytest.mark.medium
class DescribeSessionScrub:
    def it_keeps_secret_values_out_of_verbose_failure_output(self, tmp_path: Path) -> None:
        (tmp_path / 'conftest.py').write_text(_TESTS_CONFTEST.read_text(encoding='utf-8'), encoding='utf-8')
        (tmp_path / 'test_env.py').write_text(_FAILING_ENV_TEST, encoding='utf-8')
        child_env = {
            'PATH': os.environ['PATH'],
            'HOME': str(tmp_path),
            'FAKE_SECRET_TOKEN': _FAKE_SECRET_VALUE,
        }

        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '-v', '-l', '-p', 'no:cacheprovider', str(tmp_path)],
            capture_output=True,
            text=True,
            env=child_env,
            cwd=tmp_path,
            check=False,
        )

        assert (result.returncode, _FAKE_SECRET_VALUE in result.stdout + result.stderr) == (1, False)
