"""The sharded coverage pre-scan with session fixtures and a user coverage config (issue #527)."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from pytest_gremlins.plugin import _run_tests_with_coverage

_SAMPLE = """\
def setup_registry():
    return {'ready': True}


def double(value):
    return value * 2
"""

_SESSION_CONFTEST = """\
import pytest

from sample import setup_registry


@pytest.fixture(scope='session', autouse=True)
def registry():
    return setup_registry()
"""

_TEST_A = 'from sample import double\n\n\ndef test_a():\n    assert double(1) == 2\n'
_TEST_B = 'from sample import double\n\n\ndef test_b():\n    assert double(2) == 4\n'

_NODE_IDS = ['test_a.py::test_a', 'test_b.py::test_b']

# Lines of ``setup_registry`` in ``sample.py``, the code the session fixture runs.
_FIXTURE_LINES = {1, 2}


def _write_project(root: Path, conftest: str = '') -> Path:
    (root / 'sample.py').write_text(_SAMPLE, encoding='utf-8')
    (root / 'conftest.py').write_text(conftest, encoding='utf-8')
    (root / 'test_a.py').write_text(_TEST_A, encoding='utf-8')
    (root / 'test_b.py').write_text(_TEST_B, encoding='utf-8')
    return root


def _full_triples(project: Path, workers: int) -> set[tuple[str, int, str]]:
    coverage_data = _run_tests_with_coverage(
        _NODE_IDS,
        project,
        coverage_include=[str((project / 'sample.py').resolve())],
        prescan_workers=workers,
    )
    return {
        (file, line, node_id)
        for node_id, files in coverage_data.items()
        for file, lines in files.items()
        for line in lines
    }


def _triples(project: Path, workers: int) -> set[tuple[str, int, str]]:
    return {(Path(file).name, line, node_id) for file, line, node_id in _full_triples(project, workers)}


@pytest.mark.medium
class DescribeShardedPrescanWithASessionFixture:
    def it_records_every_serial_entry_and_only_fixture_lines_beyond_them(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        project = _write_project(tmp_path, _SESSION_CONFTEST)

        serial = _triples(project, 1)
        sharded = _triples(project, 2)

        assert serial <= sharded
        assert {line for _, line, _ in sharded - serial} <= _FIXTURE_LINES


@pytest.mark.medium
class DescribeShardedPrescanWithUserCoverageConfig:
    def it_records_the_same_file_paths_as_the_serial_pre_scan_when_the_project_sets_relative_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        project = _write_project(tmp_path.resolve())
        (project / '.coveragerc').write_text('[run]\nrelative_files = true\n', encoding='utf-8')
        monkeypatch.chdir(project)

        assert _full_triples(project, 2) == _full_triples(project, 1)

    def it_does_not_raise_when_the_project_names_a_coverage_plugin_the_plugin_process_cannot_import(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        project = _write_project(tmp_path.resolve())
        (project / '.coveragerc').write_text('[run]\nplugins = not_installed_cov_plugin\n', encoding='utf-8')
        monkeypatch.chdir(project)

        assert _full_triples(project, 2) == _full_triples(project, 1)

    def it_leaves_no_generated_coveragerc_behind_when_combine_fails_unexpectedly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        project = _write_project(tmp_path.resolve())
        (project / '.coveragerc').write_text('[run]\nplugins = not_installed_cov_plugin\n', encoding='utf-8')
        monkeypatch.chdir(project)

        with contextlib.suppress(ImportError):
            _full_triples(project, 2)

        assert not (project / '.coveragerc.gremlins').exists()
