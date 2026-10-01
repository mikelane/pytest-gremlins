"""Coverage env vars other than COVERAGE_CORE must not redirect the pre-scan.

The pre-scan strips ``COVERAGE_CORE`` from its subprocess env because env vars
beat the generated rc file. ``COVERAGE_FILE`` has the same precedence: when a
user (or CI) sets it, the subprocess writes its data there instead of
``rootdir/.coverage``, the pre-scan reads nothing, and every gremlin falls back to
running the whole suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.plugin import _run_tests_with_coverage

SHARED_SOURCE = 'def add(a, b):\n    return a + b\n'
TWO_TESTS_SHARING_A_LINE = (
    'from calc import add\n\n\n'
    'def test_first():\n    assert add(1, 2) == 3\n\n\n'
    'def test_second():\n    assert add(2, 2) == 4\n'
)


def _write_project(root: Path) -> Path:
    project = root / 'project'
    project.mkdir()
    (project / 'calc.py').write_text(SHARED_SOURCE)
    (project / 'test_calc.py').write_text(TWO_TESTS_SHARING_A_LINE)
    (project / 'pytest.ini').write_text('[pytest]\npythonpath = .\n')
    return project


@pytest.mark.medium
class DescribeCoverageFileEnvOverride:
    """User-level coverage env vars do not divert the pre-scan data file."""

    def it_attributes_lines_when_the_user_sets_coverage_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _write_project(tmp_path)
        monkeypatch.setenv('COVERAGE_FILE', str(tmp_path / 'ci-coverage.db'))

        coverage_by_test = _run_tests_with_coverage(
            ['test_calc.py::test_first', 'test_calc.py::test_second'],
            project,
        )

        assert set(coverage_by_test) == {'test_calc.py::test_first', 'test_calc.py::test_second'}

    def it_attributes_lines_when_the_user_sets_coverage_rcfile(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = _write_project(tmp_path)
        user_rcfile = tmp_path / 'user.coveragerc'
        user_rcfile.write_text(f'[run]\ndata_file = {tmp_path / "elsewhere.db"}\ncore = sysmon\n')
        monkeypatch.setenv('COVERAGE_RCFILE', str(user_rcfile))

        coverage_by_test = _run_tests_with_coverage(
            ['test_calc.py::test_first', 'test_calc.py::test_second'],
            project,
        )

        assert set(coverage_by_test) == {'test_calc.py::test_first', 'test_calc.py::test_second'}
