"""Tests for _run_tests_with_coverage subprocess command construction.

Verifies that the coverage subprocess uses the subprocess_bootstrap plugin
for full node ID contexts instead of dynamic_context=test_function.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest
import xdist.plugin

from pytest_gremlins.plugin import (
    GremlinSession,
    _addopts_without_xdist,
    _collect_coverage,
    _prescan_env,
    _run_tests_with_coverage,
)


@pytest.mark.medium
class DescribeRunTestsWithCoverageCommand:
    """Tests for subprocess command construction in _run_tests_with_coverage."""

    def it_includes_subprocess_bootstrap_plugin(self, tmp_path: Path) -> None:
        """The subprocess command loads the bootstrap plugin via -p."""
        captured_cmd: list[str] = []

        def capture_cmd(cmd: list[str], **_kwargs: object) -> None:
            captured_cmd.extend(cmd)

        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        assert '-p' in captured_cmd
        bootstrap_idx = captured_cmd.index('-p')
        assert captured_cmd[bootstrap_idx + 1] == 'pytest_gremlins.coverage.subprocess_bootstrap'

    def it_disables_gremlins_plugin_in_subprocess(self, tmp_path: Path) -> None:
        """The subprocess command disables the full gremlins plugin via -p no:gremlins."""
        captured_cmd: list[str] = []

        def capture_cmd(cmd: list[str], **_kwargs: object) -> None:
            captured_cmd.extend(cmd)

        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        p_indices = [i for i, v in enumerate(captured_cmd) if v == '-p']
        no_gremlins_found = any(captured_cmd[i + 1] == 'no:gremlins' for i in p_indices)
        assert no_gremlins_found, f'-p no:gremlins not found in command: {captured_cmd}'

    def it_does_not_use_dynamic_context_in_coveragerc(self, tmp_path: Path) -> None:
        """The generated coveragerc does not contain dynamic_context = test_function."""
        captured_content: list[str] = []

        def capture_cmd(*_args: object, **_kwargs: object) -> None:
            coveragerc_path = tmp_path / '.coveragerc.gremlins'
            if coveragerc_path.exists():
                captured_content.append(coveragerc_path.read_text())

        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        assert captured_content, 'coveragerc was not written before subprocess.run'
        assert 'dynamic_context' not in captured_content[0]

    def it_uses_source_dot_when_no_coverage_include(self, tmp_path: Path) -> None:
        """Without coverage_include, the coveragerc keeps the source = . default."""
        captured_content: list[str] = []

        def capture_cmd(*_args: object, **_kwargs: object) -> None:
            coveragerc_path = tmp_path / '.coveragerc.gremlins'
            if coveragerc_path.exists():
                captured_content.append(coveragerc_path.read_text())

        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        assert captured_content
        assert 'source = .' in captured_content[0]
        assert 'include =' not in captured_content[0]

    def it_writes_include_section_when_coverage_include_provided(self, tmp_path: Path) -> None:
        """With coverage_include, the coveragerc lists those paths under include and drops source = ."""
        captured_content: list[str] = []

        def capture_cmd(*_args: object, **_kwargs: object) -> None:
            coveragerc_path = tmp_path / '.coveragerc.gremlins'
            if coveragerc_path.exists():
                captured_content.append(coveragerc_path.read_text())

        include = ['/abs/src/foo.py', '/abs/src/bar.py']
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path, coverage_include=include)

        assert captured_content
        content = captured_content[0]
        assert 'source = .' not in content
        assert 'include =' in content
        assert '/abs/src/foo.py' in content
        assert '/abs/src/bar.py' in content


@pytest.mark.medium
class DescribeCollectCoverageScoping:
    """_collect_coverage scopes coverage to the gremlin source files."""

    def it_passes_resolved_gremlin_source_files_as_coverage_include(self, tmp_path: Path) -> None:
        """_collect_coverage forwards the resolved, sorted gremlin file paths as coverage_include."""
        source_file = tmp_path / 'mymodule.py'
        source_file.write_text('x = 1\n')

        gremlin_a = MagicMock(spec=['file_path'])
        gremlin_a.file_path = str(source_file)
        gremlin_b = MagicMock(spec=['file_path'])
        gremlin_b.file_path = str(source_file)

        gs = GremlinSession(enabled=True)
        gs.gremlins = [gremlin_a, gremlin_b]

        captured: dict[str, object] = {}

        def fake_run(*_args: object, **kwargs: object) -> dict[str, dict[str, list[int]]]:
            captured.update(kwargs)
            return {'tests/test_x.py::test_x': {str(source_file): [1]}}

        with patch('pytest_gremlins.plugin._run_tests_with_coverage', side_effect=fake_run):
            _collect_coverage(gs, tmp_path)

        assert captured['coverage_include'] == [str(source_file.resolve())]


def _prescan_command(tmp_path: Path, preserved_addopts: str) -> list[str]:
    """Run the pre-scan with subprocess.run patched and return the command it built."""
    captured_cmd: list[str] = []

    def capture_cmd(cmd: list[str], **_kwargs: object) -> None:
        captured_cmd.extend(cmd)

    with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=capture_cmd):
        _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path, preserved_addopts=preserved_addopts)
    return captured_cmd


def _addopts_value(cmd: list[str]) -> str:
    option = next(arg for arg in cmd if arg.startswith('addopts='))
    return option.removeprefix('addopts=')


@pytest.mark.medium
class DescribeRunTestsWithCoverageXdistStripping:
    """The pre-scan must not inherit xdist options from the project's addopts (issue #502)."""

    @pytest.mark.parametrize(
        'addopts',
        [
            '-n 4',
            '-n4',
            '-nauto',
            '-n auto',
            '--numprocesses=4',
            '--numprocesses 4',
            '--numprocesses=auto',
            '--maxprocesses=8',
            '--maxprocesses 8',
            '--dist worksteal',
            '--dist=load',
            '--max-worker-restart=2',
            '--max-worker-restart 2',
            '--tx popen//python=python3',
            '--tx=popen//python=python3',
            '--rsyncdir src',
            '--rsyncdir=src',
            '-d',
            '--distributed',
            '--loadscope-reorder',
            '--no-loadscope-reorder',
            '--px id=proxy',
            '--px=id=proxy',
            '--rsyncignore *.pyc',
            '--rsyncignore=*.pyc',
            '--testrunuid abc',
            '--testrunuid=abc',
            '--maxschedchunk 2',
            '--maxschedchunk=2',
            '-f',
            '--looponfail',
        ],
    )
    def it_strips_xdist_options_from_addopts(self, tmp_path: Path, addopts: str) -> None:
        cmd = _prescan_command(tmp_path, addopts)

        assert _addopts_value(cmd) == ''

    def it_keeps_unrelated_options_around_stripped_xdist_options(self, tmp_path: Path) -> None:
        cmd = _prescan_command(tmp_path, '--import-mode=importlib -n 4 --dist=load -ra')

        assert _addopts_value(cmd) == '--import-mode=importlib -ra'

    @pytest.mark.parametrize('addopts', ['--no-header', '-q', '--durations=5', '--nodeid-width=3'])
    def it_does_not_strip_options_that_merely_start_with_n(self, tmp_path: Path, addopts: str) -> None:
        cmd = _prescan_command(tmp_path, addopts)

        assert _addopts_value(cmd) == addopts

    def it_leaves_the_xdist_plugin_loaded_so_its_fixtures_and_hooks_exist(self, tmp_path: Path) -> None:
        cmd = _prescan_command(tmp_path, '-n 4')

        assert 'no:xdist' not in cmd

    def it_passes_the_subprocess_the_inherited_environment_without_coverage_overrides(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('COVERAGE_CORE', 'sysmon')
        monkeypatch.setenv('GREMLIN_SENTINEL', 'kept')

        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True) as run:
            _run_tests_with_coverage([], tmp_path)

        env = run.call_args.kwargs['env']
        sentinel = env['GREMLIN_SENTINEL']
        assert sentinel == 'kept'
        assert 'COVERAGE_CORE' not in env


@pytest.mark.small
class DescribePrescanEnv:
    """PYTEST_ADDOPTS must not smuggle xdist options into the pre-scan (issue #502)."""

    @pytest.mark.parametrize('value', ['-n 2', '-n2', '--numprocesses=auto', '-n 2 --dist=load'])
    def it_drops_pytest_addopts_when_only_xdist_options_remain(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', value)

        env = _prescan_env()

        assert 'PYTEST_ADDOPTS' not in env

    def it_keeps_the_non_xdist_options_in_pytest_addopts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTEST_ADDOPTS', '-n 4 --import-mode=importlib -ra')

        env = _prescan_env()

        kept = env['PYTEST_ADDOPTS']
        assert kept == '--import-mode=importlib -ra'

    def it_leaves_other_variables_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('GREMLIN_SENTINEL', 'kept')
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)

        env = _prescan_env()

        sentinel = env['GREMLIN_SENTINEL']
        assert sentinel == 'kept'
        assert 'PYTEST_ADDOPTS' not in env


class _RecordingOptionGroup:
    """Stands in for pytest's option group, recording every option xdist registers."""

    def __init__(self) -> None:
        self.recorded: list[tuple[str, bool]] = []

    def addoption(self, *names: str, **attrs: object) -> None:
        takes_value = attrs.get('action') not in {'store_true', 'store_false', 'count'} and attrs.get('nargs') != 0
        self.recorded.extend((name, takes_value) for name in names)

    _addoption = addoption


class _RecordingParser:
    """Stands in for pytest's parser, exposing the calls ``xdist.plugin.pytest_addoption`` makes."""

    def __init__(self) -> None:
        self.group = _RecordingOptionGroup()

    def getgroup(self, *_group_args: object) -> _RecordingOptionGroup:
        return self.group

    def addini(self, name: str, help: str, type: str | None = None, default: object = None) -> None:  # noqa: A002
        """xdist registers ini keys here; they are not command-line options."""


def _installed_xdist_options() -> list[tuple[str, bool]]:
    """Return ``(option, takes_value)`` for every option the installed pytest-xdist registers."""
    parser = _RecordingParser()
    xdist.plugin.pytest_addoption(cast('pytest.Parser', parser))
    return parser.group.recorded


@pytest.mark.small
class DescribeXdistOptionCoverage:
    """Every option the installed pytest-xdist registers is stripped (guards against xdist adding new ones)."""

    @pytest.mark.parametrize(('option', 'takes_value'), _installed_xdist_options())
    def it_strips_the_option(self, option: str, takes_value: bool) -> None:
        addopts = f'{option} 2' if takes_value else option

        assert _addopts_without_xdist(addopts) == ''
