"""Keep secret-shaped environment variables out of failure output for the whole test session."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from secret_env_scrub import (
    is_secret_env_name,
    scrub_secret_env,
)

_TESTS_DIRECTORY = Path(__file__).resolve().parents[1]
_TESTS_CONFTEST = _TESTS_DIRECTORY / 'conftest.py'
_SCRUB_MODULE = _TESTS_DIRECTORY / 'secret_env_scrub.py'
_FAKE_SECRET_VALUE = 'fake-secret-value-0123456789'  # noqa: S105  # pragma: allowlist secret
_CHILD_TIMEOUT_SECONDS = 120
_CHILD_PLATFORM_VARIABLES = ('PATH', 'SYSTEMROOT')

_FAILING_ENV_TEST = """
import os


def test_environment_is_empty():
    env = dict(os.environ)
    assert env == {}
"""

_IN_PROCESS_USAGE_ERROR_RUN = """
import os
import sys

import pytest

pytest.main(['-p', 'no:cacheprovider', '--no-such-option', sys.argv[1]])
print('FAKE_SECRET_TOKEN' in os.environ)
"""


def _child_environment() -> dict[str, str]:
    """Return a minimal environment holding the fake secret, for a child pytest run.

    The environment stays small so pytest's truncated ``-l`` repr of it would still show the secret if
    the scrub broke. It keeps ``SYSTEMROOT``, which a Python child needs to start on Windows.
    """
    environment = {'FAKE_SECRET_TOKEN': _FAKE_SECRET_VALUE, 'PYTHONIOENCODING': 'utf-8'}
    environment.update({name: os.environ[name] for name in _CHILD_PLATFORM_VARIABLES if name in os.environ})
    return environment


def _copy_scrub_support_into(directory: Path) -> None:
    for source in (_TESTS_CONFTEST, _SCRUB_MODULE):
        (directory / source.name).write_text(source.read_text(encoding='utf-8'), encoding='utf-8')


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
            'RELEASE_PAT',
            'GITHUB_PAT',
            'OPENAI_APIKEY',
            'GPG_PASSPHRASE',
            'CLIENT_SECRETS',
            'DB_PWD',
        ],
    )
    def it_flags_secret_shaped_names(self, name: str) -> None:
        assert is_secret_env_name(name) is True

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
            'PYTHON_COMPAT',
            'LIBEXPAT',
            'SYSTEMROOT',
            'USERPROFILE',
            'APPDATA',
            'GIT_ASKPASS',
            'PWD',
            'OLDPWD',
            'MAX_TOKENS',
        ],
    )
    def it_keeps_names_the_suite_or_tools_need(self, name: str) -> None:
        assert is_secret_env_name(name) is False


@pytest.mark.small
class DescribeScrubSecretEnv:
    def it_removes_secret_entries_from_the_mapping(self) -> None:
        environ = {'GITHUB_TOKEN': 'abc', 'PATH': '/bin'}

        scrub_secret_env(environ)

        assert environ == {'PATH': '/bin'}

    def it_returns_the_removed_entries_for_restoring(self) -> None:
        environ = {'GITHUB_TOKEN': 'abc', 'PATH': '/bin'}

        removed = scrub_secret_env(environ)

        assert removed == {'GITHUB_TOKEN': 'abc'}

    def it_leaves_a_clean_mapping_untouched(self) -> None:
        environ = {'PATH': '/bin'}

        removed = scrub_secret_env(environ)

        assert (environ, removed) == ({'PATH': '/bin'}, {})


@pytest.mark.small
class DescribeChildEnvironment:
    def it_keeps_the_platform_variables_a_windows_interpreter_needs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('SYSTEMROOT', r'C:\Windows')

        assert _child_environment()['SYSTEMROOT'] == r'C:\Windows'

    def it_adds_the_fake_secret(self) -> None:
        assert _child_environment()['FAKE_SECRET_TOKEN'] == _FAKE_SECRET_VALUE

    def it_leaves_out_other_parent_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTHONPATH', 'parent')

        assert 'PYTHONPATH' not in _child_environment()


@pytest.mark.medium
class DescribeSessionScrub:
    def it_keeps_secret_values_out_of_verbose_failure_output(self, tmp_path: Path) -> None:
        _copy_scrub_support_into(tmp_path)
        (tmp_path / 'test_env.py').write_text(_FAILING_ENV_TEST, encoding='utf-8')
        result = subprocess.run(
            [sys.executable, '-P', '-m', 'pytest', '-vv', '-l', '-p', 'no:cacheprovider', str(tmp_path)],
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            env=_child_environment(),
            cwd=tmp_path,
            check=False,
            timeout=_CHILD_TIMEOUT_SECONDS,
        )

        assert (result.returncode, _FAKE_SECRET_VALUE in result.stdout + result.stderr) == (1, False)

    def it_restores_the_secrets_when_an_in_process_session_fails_to_configure(self, tmp_path: Path) -> None:
        _copy_scrub_support_into(tmp_path)
        (tmp_path / 'test_env.py').write_text(_FAILING_ENV_TEST, encoding='utf-8')
        (tmp_path / 'run_in_process.py').write_text(_IN_PROCESS_USAGE_ERROR_RUN, encoding='utf-8')
        result = subprocess.run(
            [sys.executable, '-P', str(tmp_path / 'run_in_process.py'), str(tmp_path)],
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            env=_child_environment(),
            cwd=tmp_path,
            check=False,
            timeout=_CHILD_TIMEOUT_SECONDS,
        )

        assert result.stdout.splitlines()[-1:] == ['True']
