"""A rootdir above the project scores normally; a symlinked rootdir stops with one clear error (#947).

With ``--rootdir`` above the project and the project's own ini file found from the arguments, the pre-scan
used to rediscover the project directory as its rootdir.  It recorded coverage under node ids relative to the
project, while the node ids of the session were relative to the rootdir above it, so no selected test matched
a node id and every gremlin scored ERROR.
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

SCORED_VERDICTS = {'Zapped': 2, 'Survived': 0, 'Error': 0}
USAGE_ERROR_EXIT_CODE = 4


@pytest.fixture(autouse=True)
def utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make child pytest processes write UTF-8 so the parent decodes their output on any platform."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


@pytest.fixture
def project(pytester_with_markers: pytest.Pytester) -> Path:
    """A project directory below the pytester path, with its own ini file that puts it on ``sys.path``."""
    directory = pytester_with_markers.mkdir('project')
    (directory / 'pytest.ini').write_text('[pytest]\npythonpath = .\n', encoding='utf-8')
    (directory / 'sample.py').write_text(SAMPLE, encoding='utf-8')
    tests = directory / 'tests'
    tests.mkdir()
    (tests / 'test_sample.py').write_text(STRONG_TEST, encoding='utf-8')
    return directory


def _target(project: Path) -> str:
    return f'--gremlin-targets={(project / "sample.py").as_posix()}'


@pytest.mark.medium
class DescribeARootdirAboveTheProject:
    def it_scores_normally_when_started_in_the_project(
        self, pytester_with_markers: pytest.Pytester, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(project)

        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, _target(project), f'--rootdir={pytester_with_markers.path.as_posix()}', 'tests'
        )

        assert verdicts(result.stdout.str()) == SCORED_VERDICTS, result.stdout.str() + result.stderr.str()

    def it_scores_normally_when_started_in_the_rootdir(
        self, pytester_with_markers: pytest.Pytester, project: Path
    ) -> None:
        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, _target(project), f'--rootdir={pytester_with_markers.path.as_posix()}', 'project/tests'
        )

        assert verdicts(result.stdout.str()) == SCORED_VERDICTS, result.stdout.str() + result.stderr.str()


@pytest.mark.medium
class DescribeALayoutWithoutARootdirOption:
    def it_scores_normally_when_started_in_the_project(
        self, pytester_with_markers: pytest.Pytester, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(project)

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, _target(project), 'tests')

        assert verdicts(result.stdout.str()) == SCORED_VERDICTS, result.stdout.str() + result.stderr.str()

    def it_scores_normally_when_started_in_a_subdirectory(
        self, pytester_with_markers: pytest.Pytester, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(project / 'tests')

        result = pytester_with_markers.runpytest_subprocess(*GREMLIN_ARGS, _target(project), '.')

        assert verdicts(result.stdout.str()) == SCORED_VERDICTS, result.stdout.str() + result.stderr.str()


@pytest.mark.medium
class DescribeASymlinkedRootdir:
    def it_stops_with_one_clear_error(
        self, pytester_with_markers: pytest.Pytester, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = pytester_with_markers.path / 'link'
        try:
            link.symlink_to(project, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip('symlinks cannot be created here')
        monkeypatch.chdir(project)

        result = pytester_with_markers.runpytest_subprocess(
            *GREMLIN_ARGS, _target(project), f'--rootdir={link.as_posix()}', 'tests'
        )

        assert result.ret == USAGE_ERROR_EXIT_CODE
        assert result.stderr.str().count('gremlin runs start in the rootdir') == 1
        assert 'Gremlin 1/' not in result.stdout.str()
