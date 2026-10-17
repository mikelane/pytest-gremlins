"""A warm ``--gremlin-cache`` must hit under xdist ``-n N`` just as it does without it (refs #598)."""

from __future__ import annotations

import re

import pytest

_SAMPLE = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

_CATCHES = """
from sample import classify


def test_big():
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

_WEAKER = """
from sample import classify


def test_big():
    assert classify(11) == 'big'
"""

_UNRELATED = """
def test_unrelated():
    assert True
"""

_GREMLIN_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=comparison',
    '--gremlin-cache',
    '-p',
    'no:cacheprovider',
)


def _count(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


def _from_cache(output: str) -> int:
    match = re.search(r'(\d+) gremlins from cache', output)
    return int(match.group(1)) if match else 0


@pytest.fixture
def project(pytester_with_markers: pytest.Pytester) -> pytest.Pytester:
    pytester_with_markers.makepyfile(sample=_SAMPLE)
    pytester_with_markers.makepyfile(test_sample=_CATCHES)
    return pytester_with_markers


@pytest.mark.medium
class DescribeAWarmCacheUnderXdist:
    def it_starts_cold_with_nothing_from_cache(self, project: pytest.Pytester) -> None:
        output = project.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2').stdout.str()

        assert _from_cache(output) == 0

    def it_serves_every_gremlin_from_cache_on_the_second_run(self, project: pytest.Pytester) -> None:
        first = project.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2').stdout.str()

        second = project.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2').stdout.str()

        assert _from_cache(second) == _count(first, 'Zapped') + _count(first, 'Survived')
        assert _from_cache(second) > 0

    def it_replays_the_verdicts_of_the_first_run(self, project: pytest.Pytester) -> None:
        first = project.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2').stdout.str()

        second = project.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2').stdout.str()

        assert _count(second, 'Zapped') == _count(first, 'Zapped')
        assert _count(second, 'Survived') == _count(first, 'Survived')

    def it_misses_after_a_covering_test_changes(self, project: pytest.Pytester) -> None:
        project.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2')
        project.makepyfile(test_sample=_WEAKER)

        second = project.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2').stdout.str()

        assert _from_cache(second) == 0
        assert _count(second, 'Survived') > 0

    def it_misses_after_a_covering_test_changes_when_another_test_file_shares_its_name(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(test_a=_CATCHES)
        (pytester_with_markers.path / 'sub').mkdir()
        (pytester_with_markers.path / 'sub' / '__init__.py').write_text('')
        (pytester_with_markers.path / 'sub' / 'test_a.py').write_text(_UNRELATED)
        pytester_with_markers.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2')
        pytester_with_markers.makepyfile(test_a=_WEAKER)

        second = pytester_with_markers.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2').stdout.str()

        assert _from_cache(second) == 0

    def it_shares_the_cache_with_a_run_without_xdist(self, project: pytest.Pytester) -> None:
        first = project.runpytest_subprocess(*_GREMLIN_ARGS).stdout.str()

        second = project.runpytest_subprocess(*_GREMLIN_ARGS, '-n', '2').stdout.str()

        assert _from_cache(second) == _count(first, 'Zapped') + _count(first, 'Survived')


@pytest.fixture
def project_with_a_test_outside_rootdir(
    pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> pytest.Pytester:
    project_dir = pytester_with_markers.path / 'proj'
    project_dir.mkdir()
    (project_dir / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (project_dir / 'sample.py').write_text(_SAMPLE)
    (project_dir / 'test_in.py').write_text('def test_in():\n    assert True\n')
    (pytester_with_markers.path / 'outside').mkdir()
    (pytester_with_markers.path / 'outside' / 'test_ext.py').write_text(_CATCHES)
    monkeypatch.chdir(project_dir)
    return pytester_with_markers


@pytest.mark.medium
class DescribeATestOutsideRootdirWithTheCache:
    @pytest.mark.parametrize('xdist_args', [(), ('-n', '2')])
    def it_does_not_crash(
        self, project_with_a_test_outside_rootdir: pytest.Pytester, xdist_args: tuple[str, ...]
    ) -> None:
        result = project_with_a_test_outside_rootdir.runpytest_subprocess(
            *_GREMLIN_ARGS, *xdist_args, '../outside/test_ext.py', 'test_in.py'
        )

        assert result.ret != pytest.ExitCode.INTERNAL_ERROR
        assert 'IsADirectoryError' not in result.stdout.str() + result.stderr.str()

    @pytest.mark.parametrize('xdist_args', [(), ('-n', '2')])
    def it_never_replays_a_verdict_it_could_not_key(
        self, project_with_a_test_outside_rootdir: pytest.Pytester, xdist_args: tuple[str, ...]
    ) -> None:
        args = (*_GREMLIN_ARGS, *xdist_args, '../outside/test_ext.py', 'test_in.py')
        project_with_a_test_outside_rootdir.runpytest_subprocess(*args)

        second = project_with_a_test_outside_rootdir.runpytest_subprocess(*args).stdout.str()

        assert _from_cache(second) == 0
