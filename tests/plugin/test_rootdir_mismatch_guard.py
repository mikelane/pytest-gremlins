"""A run whose gremlin runs cannot resolve what the session resolved stops early with one error (#686, #690).

Gremlin runs start in the rootdir.  When the session was started elsewhere, an ``@file`` named by a relative
path in ``addopts`` or ``PYTEST_ADDOPTS`` may exist only relative to the session's directory (#686), and the
node ids of collected tests may not resolve from the rootdir (#690).  Every gremlin would then score ERROR, so
the run stops before any gremlin executes.  The control tests pin the layouts that work today.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

STRONG_TEST = """
from sample import classify


def test_big():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

ARGUMENT_FILE_CONTENT = '-q\n'
USAGE_ERROR_EXIT_CODE = 4
ROOTDIR_PHRASE = 'gremlin runs start in the rootdir'
# The two comparison gremlins of ``n > 10`` that ``STRONG_TEST`` pins at the boundary.
SCORED_VERDICTS = {'Zapped': 2, 'Survived': 0, 'Error': 0}
# Lets a test in a subdirectory import ``sample`` from the project root.
SYS_PATH_CONFTEST = 'import sys\nsys.path.insert(0, "..")\n'


@pytest.fixture(autouse=True)
def utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make child pytest processes write UTF-8 so the parent decodes their output on any platform.

    pytest-test-categories prints bullet characters; on Windows the child would write them in the
    locale code page (cp1252) and ``Pytester`` fails to decode that as UTF-8.
    """
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


def _write_project(pytester: pytest.Pytester, *, tests_dir: str = '') -> Path:
    """Write ``sample.py`` and its test under the pytester path; return the directory holding the test."""
    test_directory = pytester.path / tests_dir
    test_directory.mkdir(parents=True, exist_ok=True)
    (pytester.path / 'sample.py').write_text(SAMPLE, encoding='utf-8')
    (test_directory / 'test_sample.py').write_text(STRONG_TEST, encoding='utf-8')
    return test_directory


def _assert_stopped_before_any_gremlin(result: pytest.RunResult) -> None:
    assert result.ret == USAGE_ERROR_EXIT_CODE
    assert result.stderr.str().count(ROOTDIR_PHRASE) == 1
    assert 'Gremlin 1/' not in result.stdout.str()
    assert 'mutation report' not in result.stdout.str()


def _assert_scored_normally(result: pytest.RunResult) -> None:
    assert verdicts(result.stdout.str()) == SCORED_VERDICTS
    assert ROOTDIR_PHRASE not in result.stderr.str() + result.stdout.str()


@pytest.mark.medium
class DescribeARelativeArgumentFileOnlyTheSessionDirectoryHas:
    """#686: ``cd sub && pytest --gremlins ..`` reads ``sub/args.txt``; gremlin runs look for ``<rootdir>/args.txt``."""

    @pytest.fixture
    def session_directory(self, pytester_with_markers: pytest.Pytester) -> Path:
        pytester_with_markers.makeini('[pytest]\naddopts = @args.txt\n')
        _write_project(pytester_with_markers)
        sub = pytester_with_markers.mkdir('sub')
        (sub / 'args.txt').write_text(ARGUMENT_FILE_CONTENT, encoding='utf-8')
        return sub

    def it_stops_when_ini_addopts_names_a_file_the_rootdir_lacks(
        self, pytester_with_markers: pytest.Pytester, session_directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(session_directory)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '..')

        _assert_stopped_before_any_gremlin(result)

    def it_stops_when_pytest_addopts_names_a_file_the_rootdir_lacks(
        self, pytester_with_markers: pytest.Pytester, session_directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester_with_markers.makeini('[pytest]\n')
        monkeypatch.setenv('PYTEST_ADDOPTS', '@args.txt')
        monkeypatch.chdir(session_directory)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '..')

        _assert_stopped_before_any_gremlin(result)

    def it_stops_when_a_nested_argument_file_is_the_one_the_rootdir_lacks(
        self, pytester_with_markers: pytest.Pytester, session_directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (session_directory / 'args.txt').write_text('@inner.txt\n', encoding='utf-8')
        (session_directory / 'inner.txt').write_text(ARGUMENT_FILE_CONTENT, encoding='utf-8')
        (pytester_with_markers.path / 'args.txt').write_text('@inner.txt\n', encoding='utf-8')
        monkeypatch.chdir(session_directory)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '..')

        _assert_stopped_before_any_gremlin(result)

    def it_names_the_file_and_the_fix(
        self, pytester_with_markers: pytest.Pytester, session_directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(session_directory)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '..')

        message = result.stderr.str()
        assert '@args.txt' in message
        assert f'run pytest from {pytester_with_markers.path}' in message
        assert 'absolute path' in message


@pytest.mark.medium
class DescribeArgumentFileLayoutsThatKeepWorking:
    def it_scores_when_the_file_also_exists_in_the_rootdir(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = @args.txt\n')
        _write_project(pytester_with_markers)
        (pytester_with_markers.path / 'args.txt').write_text(ARGUMENT_FILE_CONTENT, encoding='utf-8')
        sub = pytester_with_markers.mkdir('sub')
        (sub / 'args.txt').write_text(ARGUMENT_FILE_CONTENT, encoding='utf-8')
        monkeypatch.chdir(sub)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '..')

        _assert_scored_normally(result)

    def it_scores_when_the_file_is_named_by_absolute_path(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sub = pytester_with_markers.mkdir('sub')
        absolute_file = sub / 'args.txt'
        absolute_file.write_text(ARGUMENT_FILE_CONTENT, encoding='utf-8')
        pytester_with_markers.makeini(f'[pytest]\naddopts = @{absolute_file.as_posix()}\n')
        _write_project(pytester_with_markers)
        monkeypatch.chdir(sub)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '..')

        _assert_scored_normally(result)

    def it_scores_when_the_session_starts_in_the_rootdir(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = @args.txt\n')
        _write_project(pytester_with_markers)
        (pytester_with_markers.path / 'args.txt').write_text(ARGUMENT_FILE_CONTENT, encoding='utf-8')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS)

        _assert_scored_normally(result)

    def it_scores_when_the_session_starts_in_a_subdirectory_with_no_argument_file(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester_with_markers.makeini('[pytest]\n')
        tests_directory = _write_project(pytester_with_markers, tests_dir='tests')
        (tests_directory / 'conftest.py').write_text(SYS_PATH_CONFTEST, encoding='utf-8')
        monkeypatch.chdir(tests_directory)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '.')

        _assert_scored_normally(result)


@pytest.mark.medium
class DescribeTestsWhoseNodeIdsDoNotResolveFromTheRootdir:
    """#690: a rootdir below the tests, or a ``-c`` file in a subdirectory, leaves the node ids unresolvable."""

    @pytest.fixture
    def absolute_target(self, pytester_with_markers: pytest.Pytester) -> str:
        _write_project(pytester_with_markers)
        pytester_with_markers.mkdir('sub')
        pytester_with_markers.mkdir('cfg')
        (pytester_with_markers.path / 'cfg' / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
        return f'--gremlin-targets={pytester_with_markers.path / "sample.py"}'

    def it_stops_when_rootdir_points_below_the_tests(
        self, pytester_with_markers: pytest.Pytester, absolute_target: str
    ) -> None:
        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, absolute_target, '--rootdir=sub', '.')

        _assert_stopped_before_any_gremlin(result)

    def it_stops_when_the_config_file_sits_in_a_subdirectory(
        self, pytester_with_markers: pytest.Pytester, absolute_target: str
    ) -> None:
        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, absolute_target, '-c', 'cfg/pytest.ini', '.')

        _assert_stopped_before_any_gremlin(result)

    def it_names_the_cause_and_the_fix(self, pytester_with_markers: pytest.Pytester, absolute_target: str) -> None:
        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, absolute_target, '--rootdir=sub', '.')

        message = result.stderr.str()
        assert 'test_sample.py::test_big' in message
        assert '--rootdir' in message

    def it_stops_when_xdist_distributes_the_tests(
        self, pytester_with_markers: pytest.Pytester, absolute_target: str
    ) -> None:
        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, absolute_target, '-c', 'cfg/pytest.ini', '-n', '2', '.'
        )

        _assert_stopped_before_any_gremlin(result)

    def it_leaves_an_xdist_run_that_finds_no_sources_to_report_that_instead(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        _write_project(pytester_with_markers)
        pytester_with_markers.mkdir('cfg')
        (pytester_with_markers.path / 'cfg' / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '-c', 'cfg/pytest.ini', '-n', '2', '.')

        assert result.ret == 0
        assert ROOTDIR_PHRASE not in result.stderr.str() + result.stdout.str()


@pytest.mark.medium
class DescribeNodeIdLayoutsThatKeepWorking:
    def it_scores_when_the_session_starts_in_a_subdirectory_of_the_rootdir(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester_with_markers.makeini('[pytest]\n')
        tests_directory = _write_project(pytester_with_markers, tests_dir='tests')
        (tests_directory / 'conftest.py').write_text(SYS_PATH_CONFTEST, encoding='utf-8')
        monkeypatch.chdir(tests_directory)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS)

        _assert_scored_normally(result)

    def it_scores_when_rootdir_is_given_and_holds_the_tests(self, pytester_with_markers: pytest.Pytester) -> None:
        _write_project(pytester_with_markers)

        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, f'--rootdir={pytester_with_markers.path}', '.'
        )

        _assert_scored_normally(result)

    def it_leaves_a_run_that_finds_no_sources_to_report_that_instead(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        _write_project(pytester_with_markers)
        pytester_with_markers.mkdir('cfg')
        (pytester_with_markers.path / 'cfg' / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '-c', 'cfg/pytest.ini', '.')

        assert result.ret == 0
        assert 'No gremlins found' in result.stdout.str()
        assert ROOTDIR_PHRASE not in result.stderr.str() + result.stdout.str()

    def it_scores_when_the_config_file_sits_in_a_subdirectory_that_holds_the_project(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        project = pytester_with_markers.mkdir('project')
        (project / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
        (project / 'sample.py').write_text(SAMPLE, encoding='utf-8')
        (project / 'test_sample.py').write_text(STRONG_TEST, encoding='utf-8')
        (project / 'conftest.py').write_text(
            (pytester_with_markers.path / 'conftest.py').read_text(encoding='utf-8'), encoding='utf-8'
        )

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, '-c', 'project/pytest.ini', 'project')

        _assert_scored_normally(result)
