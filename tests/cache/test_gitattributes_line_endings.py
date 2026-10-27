"""Checkouts with different ``core.autocrlf`` settings must hash test files identically (issue #482).

``ContentHasher.hash_file`` hashes raw bytes, so CRLF and LF checkouts of one committed file
hash differently unless the repository pins line endings with ``.gitattributes``.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tomllib

import pytest

from pytest_gremlins.cache.hasher import ContentHasher

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_SOURCE = b'def test_it():\n    assert True\n'
NULL_DEVICE = os.devnull


def _git(cwd: Path, *args: str) -> None:
    """Run git with no host or global config so the test cannot depend on the developer's setup."""
    subprocess.run(
        ['git', *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            'PATH': os.environ['PATH'],
            'SYSTEMROOT': os.environ.get('SYSTEMROOT', ''),
            'HOME': str(cwd),
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': NULL_DEVICE,
        },
    )


def _checkout_with_autocrlf(origin: Path, destination: Path, autocrlf: str) -> Path:
    destination.mkdir()
    _git(destination, 'init', '-q')
    _git(destination, 'config', 'core.autocrlf', autocrlf)
    _git(destination, 'fetch', '-q', str(origin), 'HEAD')
    _git(destination, 'checkout', '-q', 'FETCH_HEAD')
    return destination / 'test_sample.py'


@pytest.fixture
def origin_repo(tmp_path: Path) -> Path:
    origin = tmp_path / 'origin'
    origin.mkdir()
    _git(origin, 'init', '-q')
    _git(origin, 'config', 'user.email', 'ci@example.com')
    _git(origin, 'config', 'user.name', 'CI')
    _git(origin, 'config', 'commit.gpgsign', 'false')
    (origin / '.gitattributes').write_bytes((REPO_ROOT / '.gitattributes').read_bytes())
    (origin / 'test_sample.py').write_bytes(COMMITTED_SOURCE)
    _git(origin, 'add', '.gitattributes', 'test_sample.py')
    _git(origin, 'commit', '-q', '-m', 'fixture')
    return origin


@pytest.mark.medium
class DescribeGitattributesLineEndings:
    def it_hashes_crlf_and_lf_checkouts_of_a_python_file_identically(self, tmp_path: Path, origin_repo: Path) -> None:
        crlf_file = _checkout_with_autocrlf(origin_repo, tmp_path / 'crlf', 'true')
        lf_file = _checkout_with_autocrlf(origin_repo, tmp_path / 'lf', 'input')
        hasher = ContentHasher()

        assert hasher.hash_file(crlf_file) == hasher.hash_file(lf_file)

    def it_materializes_python_files_with_lf_endings_under_autocrlf_true(
        self, tmp_path: Path, origin_repo: Path
    ) -> None:
        crlf_file = _checkout_with_autocrlf(origin_repo, tmp_path / 'crlf', 'true')

        assert crlf_file.read_bytes() == COMMITTED_SOURCE


@pytest.fixture
def troubleshooting_section() -> str:
    text = (REPO_ROOT / 'docs' / 'guide' / 'troubleshooting.md').read_text(encoding='utf-8')
    return text.split('### Cache never warms across checkouts on Windows')[1].split('\n---\n')[0]


@pytest.mark.medium
class DescribeTroubleshootingRecheckoutAdvice:
    def it_tells_users_to_recheckout_before_listing_either_remedy(self, troubleshooting_section: str) -> None:
        solution = troubleshooting_section.split('**Solution:**')[1]
        first_remedy = solution.index('core.autocrlf=input')
        recheckout = solution.index('re-checkout')

        assert recheckout < first_remedy

    def it_sets_autocrlf_globally_so_a_fresh_clone_inherits_it(self, troubleshooting_section: str) -> None:
        assert 'git config --global core.autocrlf input' in troubleshooting_section

    def it_never_offers_a_repo_local_autocrlf_setting_that_a_fresh_clone_would_lose(
        self, troubleshooting_section: str
    ) -> None:
        assert 'git config core.autocrlf' not in troubleshooting_section


@pytest.mark.medium
class DescribeSdistIncludesGitattributes:
    def it_lists_gitattributes_in_the_sdist_include_paths(self) -> None:
        pyproject = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        includes = pyproject['tool']['hatch']['build']['targets']['sdist']['include']

        assert '/.gitattributes' in includes
