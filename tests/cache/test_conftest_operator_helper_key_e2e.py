"""A helper module a conftest-defined operator imports reaches the cache key (#924)."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

OPERATOR_BODY = textwrap.dedent(
    """
    import ast

    {import_line}
    from pytest_gremlins.instrumentation.transformer import get_default_registry


    class HelperConstantOperator:
        name = 'helper-constant'
        description = 'offsets integer literals'

        def can_mutate(self, node):
            return isinstance(node, ast.Constant) and type(node.value) is int

        def mutate(self, node):
            return [ast.Constant(value=node.value + OFFSET)]


    get_default_registry().register(HelperConstantOperator)
    """
)
HELPER = 'OFFSET = {offset}\n'
TARGET = 'def limit():\n    return 41\n'
TARGET_TEST = 'from target import limit\n\n\ndef test_limit():\n    assert limit() < 50\n'
SIBLING_TEST = 'def test_unrelated():\n    assert True\n'
GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=helper-constant', '--gremlin-cache')
MISSED_EVERYTHING = 'Cache: 0 hits, 1 misses (0% hit rate)'
HIT_EVERYTHING = 'Cache: 1 hits, 0 misses (100% hit rate)'


def _operator_conftest(import_line: str) -> str:
    return OPERATOR_BODY.format(import_line=import_line)


@pytest.fixture
def sibling_operator_helper(pytester: pytest.Pytester) -> Path:
    pytester.makepyfile(target=TARGET)
    pytester.mkdir('a')
    pytester.mkdir('b')
    (pytester.path / 'a' / 'conftest.py').write_text(_operator_conftest('from _offset_helper import OFFSET'))
    helper = pytester.path / 'a' / '_offset_helper.py'
    helper.write_text(HELPER.format(offset=1))
    (pytester.path / 'a' / 'test_sibling.py').write_text(SIBLING_TEST)
    (pytester.path / 'b' / 'test_target.py').write_text(TARGET_TEST)
    return helper


@pytest.fixture
def rootdir_operator_helper(pytester: pytest.Pytester) -> Path:
    pytester.makepyfile(target=TARGET)
    pytester.makeconftest(_operator_conftest('from helpers._offset_helper import OFFSET'))
    pytester.mkdir('helpers')
    helper = pytester.path / 'helpers' / '_offset_helper.py'
    helper.write_text(HELPER.format(offset=1))
    pytester.mkdir('tests_dir')
    (pytester.path / 'tests_dir' / 'test_target.py').write_text(TARGET_TEST)
    return helper


@pytest.mark.medium
class DescribeConftestOperatorHelperInCacheKey:
    @pytest.mark.usefixtures('sibling_operator_helper')
    def it_hits_on_a_warm_run_with_the_helper_unchanged(self, pytester: pytest.Pytester) -> None:
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        warm = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        warm.stdout.fnmatch_lines([HIT_EVERYTHING])

    def it_misses_after_the_helper_beside_a_sibling_operator_conftest_is_edited(
        self, pytester: pytest.Pytester, sibling_operator_helper: Path
    ) -> None:
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')
        sibling_operator_helper.write_text(HELPER.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        edited.stdout.fnmatch_lines([MISSED_EVERYTHING])

    def it_misses_after_a_helper_in_another_directory_of_the_rootdir_conftest_is_edited(
        self, pytester: pytest.Pytester, rootdir_operator_helper: Path
    ) -> None:
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'tests_dir')
        rootdir_operator_helper.write_text(HELPER.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'tests_dir')

        edited.stdout.fnmatch_lines([MISSED_EVERYTHING])

    def it_misses_after_editing_a_conftest_the_operator_conftest_imports_but_pytest_never_registers(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makepyfile(target=TARGET)
        pytester.mkdir('a')
        pytester.mkdir('b')
        (pytester.path / 'a' / '__init__.py').write_text('')
        (pytester.path / 'b' / '__init__.py').write_text('')
        lender = pytester.path / 'b' / 'conftest.py'
        lender.write_text(HELPER.format(offset=1))
        (pytester.path / 'a' / 'conftest.py').write_text(_operator_conftest('from b.conftest import OFFSET'))
        (pytester.path / 'a' / 'test_target.py').write_text(TARGET_TEST)
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a')
        lender.write_text(HELPER.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a')

        edited.stdout.fnmatch_lines([MISSED_EVERYTHING])
