"""Known limits of the coarse helper-module cache key (#760), pinned as strict xfails.

The coarse rule hashes every non-test ``.py`` file under the test root. A collected test file is never a
helper, so two cases fall outside it. Each test here fails today; when a fix lands, the strict xfail turns
into a failure and the marker must come off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins import plugin

GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=comparison', '--gremlin-cache')
COLD = 'Cache: 0 hits, 2 misses (0% hit rate)'
TARGET = 'def limit(x):\n    return x > 41\n'
TEST_B_MAKING = 'def make():\n    return {value}\n\n\ndef test_b():\n    pass\n'
TEST_A_IMPORTING_TEST_B = (
    'from target import limit\nfrom tests.test_b import make\n\n\ndef test_a():\n    assert limit(make())\n'
)


def _test_hash(rootdir: Path, *collected: str) -> str:
    session = plugin.GremlinSession(enabled=True, cache_enabled=True)
    node_ids = [f'{name}::test_x' for name in ('tests/test_a.py', *collected)]
    session.test_node_ids = {node_id: node_id for node_id in node_ids}
    plugin._hash_sources_and_tests_for_cache(session, {}, rootdir)
    return session.test_hashes['tests/test_a.py']


@pytest.fixture
def project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """Make the child pytest sessions these tests spawn write UTF-8, so Windows cp1252 bullets decode."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
    pytester.makepyfile(target=TARGET)
    pytester.mkdir('tests')
    (pytester.path / 'tests' / '__init__.py').write_text('')
    pytester.makeini('[pytest]\npythonpath = .\n')
    return pytester


@pytest.mark.medium
class DescribeCollectedTestFileUsedAsHelper:
    @pytest.mark.xfail(
        strict=True,
        reason='#760 coarse rule: a collected test file is never hashed as a helper, so a helper it defines '
        'that another test imports replays a stale verdict when edited',
    )
    def it_misses_the_cache_after_editing_a_helper_defined_in_another_collected_test_file(
        self, project: pytest.Pytester
    ) -> None:
        (project.path / 'tests' / 'test_b.py').write_text(TEST_B_MAKING.format(value=42))
        (project.path / 'tests' / 'test_a.py').write_text(TEST_A_IMPORTING_TEST_B)
        project.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([COLD])
        (project.path / 'tests' / 'test_b.py').write_text(TEST_B_MAKING.format(value=43))

        project.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([COLD])


@pytest.mark.medium
class DescribeTestSelectionAndTheKey:
    @pytest.mark.xfail(
        strict=True,
        reason='#760 coarse rule: whether test_b.py counts as a helper depends on whether pytest collected it, '
        'so running one test file and then the whole suite gives the same unchanged test_a.py two keys',
    )
    def it_keeps_the_key_when_only_the_selection_of_collected_files_changes(self, tmp_path: Path) -> None:
        (tmp_path / 'tests').mkdir()
        (tmp_path / 'tests' / 'test_a.py').write_text('def test_a(): pass\n')
        (tmp_path / 'tests' / 'test_b.py').write_text('def test_b(): pass\n')

        assert _test_hash(tmp_path) == _test_hash(tmp_path, 'tests/test_b.py')
