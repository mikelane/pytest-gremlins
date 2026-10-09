"""Behavioral check of the verify-test-pypi install step against local stand-ins for Test PyPI and PyPI.

On a normal release the new version is on Test PyPI but not yet on PyPI (publish-pypi runs after
verify-test-pypi), while older versions of pytest-gremlins already exist on PyPI. The install step must
still install the new version from Test PyPI, and must take its runtime dependencies from PyPI only.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest
import yaml

RELEASE_WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'release.yml'
TEST_PYPI_URL = 'https://test.pypi.org/simple/'
PYPI_URL = 'https://pypi.org/simple/'
PROJECT = 'pytest-gremlins'
DEPENDENCY = 'tinydep'

pytestmark = pytest.mark.skipif(
    sys.platform == 'win32', reason='runs the install step in bash with a POSIX .venv layout'
)


def _record_line(path: str, content: str) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(content.encode()).digest()).rstrip(b'=').decode()
    return f'{path},sha256={digest},{len(content)}\n'


def _write_wheel(project_dir: Path, name: str, version: str, requires: tuple[str, ...]) -> str:
    module = name.replace('-', '_')
    filename = f'{module}-{version}-py3-none-any.whl'
    dist_info = f'{module}-{version}.dist-info'
    metadata = f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n'
    metadata += ''.join(f'Requires-Dist: {requirement}\n' for requirement in requires)
    files = {
        f'{module}/__init__.py': f"__version__ = '{version}'\n",
        f'{dist_info}/METADATA': metadata,
        f'{dist_info}/WHEEL': 'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
    }
    record = ''.join(_record_line(path, content) for path, content in files.items()) + f'{dist_info}/RECORD,,\n'
    with zipfile.ZipFile(project_dir / filename, 'w') as wheel:
        for path, content in {**files, f'{dist_info}/RECORD': record}.items():
            wheel.writestr(path, content)
    return filename


def _add_project(root: Path, name: str, versions: dict[str, tuple[str, ...]]) -> None:
    project_dir = root / name
    project_dir.mkdir(parents=True)
    links = ''.join(
        f'<a href="{filename}">{filename}</a>'
        for filename in (_write_wheel(project_dir, name, version, requires) for version, requires in versions.items())
    )
    (project_dir / 'index.html').write_text(f'<html><body>{links}</body></html>')


def _install_script() -> str:
    jobs = yaml.safe_load(RELEASE_WORKFLOW.read_text())['jobs']
    step = next(step for step in jobs['verify-test-pypi']['steps'] if step.get('name') == 'Install from Test PyPI')
    return str(step['run'])


def _run_install_step(tmp_path: Path, *, test_pypi_versions: dict[str, tuple[str, ...]], tag: str):
    uv = shutil.which('uv')
    assert uv is not None
    test_pypi = tmp_path / 'test-pypi'
    pypi = tmp_path / 'pypi'
    _add_project(test_pypi, PROJECT, test_pypi_versions)
    _add_project(pypi, PROJECT, {'1.11.3': ()})
    _add_project(pypi, DEPENDENCY, {'1.0': ()})
    script = _install_script().replace(TEST_PYPI_URL, test_pypi.as_uri() + '/').replace(PYPI_URL, pypi.as_uri() + '/')
    return subprocess.run(
        ['bash', '-eo', 'pipefail', '-c', script],  # noqa: S607
        cwd=tmp_path,
        env={
            'PATH': f'{Path(uv).parent}:/usr/bin:/bin',
            'RELEASE_TAG': tag,
            'HOME': str(tmp_path),
            'UV_PYTHON': sys.executable,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _installed_version(tmp_path: Path, name: str) -> str:
    code = f"from importlib.metadata import version; print(version('{name}'))"
    result = subprocess.run(
        [str(tmp_path / '.venv' / 'bin' / 'python'), '-c', code], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.mark.medium
class DescribeVerifyTestPypiInstall:
    def it_installs_the_new_release_from_test_pypi_when_pypi_only_has_older_versions(self, tmp_path: Path) -> None:
        result = _run_install_step(tmp_path, test_pypi_versions={'1.11.3': (), '1.12.0': ()}, tag='v1.12.0')

        assert result.returncode == 0, result.stderr
        assert _installed_version(tmp_path, PROJECT) == '1.12.0'

    def it_installs_runtime_dependencies_from_pypi_even_though_test_pypi_lacks_them(self, tmp_path: Path) -> None:
        result = _run_install_step(
            tmp_path, test_pypi_versions={'1.12.0': (DEPENDENCY, f'{DEPENDENCY}>=0 ; extra == "dev"')}, tag='v1.12.0'
        )

        assert result.returncode == 0, result.stderr
        assert _installed_version(tmp_path, DEPENDENCY) == '1.0'

    def it_does_not_install_optional_extras_dependencies(self, tmp_path: Path) -> None:
        result = _run_install_step(
            tmp_path, test_pypi_versions={'1.12.0': ('missing-extra-dep ; extra == "dev"',)}, tag='v1.12.0'
        )

        assert result.returncode == 0, result.stderr

    def it_fails_when_the_release_version_is_not_on_test_pypi(self, tmp_path: Path) -> None:
        result = _run_install_step(tmp_path, test_pypi_versions={'1.11.3': ()}, tag='v1.12.0')

        assert result.returncode != 0
