"""An operator a conftest.py registers reaches the key of gremlins covered by tests in sibling directories (#899)."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

ROOT_CONFTEST = textwrap.dedent(
    """
    import pytest


    def pytest_configure(config):
        config.addinivalue_line('markers', 'small: fast tests')


    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(items):
        for item in items:
            item.add_marker(pytest.mark.small)
    """
)
OPERATOR_CONFTEST = textwrap.dedent(
    """
    import ast

    from pytest_gremlins.instrumentation.transformer import get_default_registry

    OFFSET = {offset}


    class SiblingConstantOperator:
        name = 'sibling-constant'
        description = 'offsets integer literals'

        def can_mutate(self, node):
            return isinstance(node, ast.Constant) and type(node.value) is int

        def mutate(self, node):
            return [ast.Constant(value=node.value + OFFSET)]


    get_default_registry().register(SiblingConstantOperator)
    """
)
TARGET = 'def limit():\n    return 41\n'
TARGET_TEST = 'from target import limit\n\n\ndef test_limit():\n    assert limit() < 50\n'
SIBLING_TEST = 'def test_unrelated():\n    assert True\n'
PLAIN_CONFTEST = 'import pytest\n\n\n@pytest.fixture\ndef unrelated():\n    return 1\n'
GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=sibling-constant', '--gremlin-cache')


@pytest.fixture
def operator_conftest(pytester: pytest.Pytester) -> Path:
    pytester.makeconftest(ROOT_CONFTEST)
    pytester.makepyfile(target=TARGET)
    pytester.mkdir('a')
    pytester.mkdir('b')
    path = pytester.path / 'a' / 'conftest.py'
    path.write_text(OPERATOR_CONFTEST.format(offset=1))
    (pytester.path / 'a' / 'test_sibling.py').write_text(SIBLING_TEST)
    (pytester.path / 'b' / 'test_target.py').write_text(TARGET_TEST)
    return path


@pytest.mark.medium
class DescribeSiblingConftestOperatorInCacheKey:
    @pytest.mark.usefixtures('operator_conftest')
    def it_hits_the_cache_on_a_warm_run_with_nothing_changed(self, pytester: pytest.Pytester) -> None:
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        warm = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        warm.stdout.fnmatch_lines(['Cache: 1 hits, 0 misses (100% hit rate)'])

    def it_misses_the_cache_after_the_sibling_operator_is_edited(
        self, pytester: pytest.Pytester, operator_conftest: Path
    ) -> None:
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')
        operator_conftest.write_text(OPERATOR_CONFTEST.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        edited.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])

    @pytest.mark.parametrize('argument_order', [('a', 'b'), ('b', 'a')])
    def it_misses_after_the_operator_conftest_is_edited_when_the_other_directory_has_its_own_conftest(
        self, pytester: pytest.Pytester, operator_conftest: Path, argument_order: tuple[str, str]
    ) -> None:
        (pytester.path / 'b' / 'conftest.py').write_text(PLAIN_CONFTEST)
        pytester.runpytest_subprocess(*GREMLIN_ARGS, *argument_order)
        operator_conftest.write_text(OPERATOR_CONFTEST.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, *argument_order)

        edited.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])
