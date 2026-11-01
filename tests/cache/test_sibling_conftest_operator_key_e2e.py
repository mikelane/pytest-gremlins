"""An operator a conftest.py defines reaches the key of gremlins covered by tests in sibling directories (#899)."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

ROOT_CONFTEST = textwrap.dedent(
    """
    import functools

    import pytest


    def pytest_configure(config):
        config.addinivalue_line('markers', 'small: fast tests')


    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(items):
        for item in items:
            item.add_marker(pytest.mark.small)


    def traced(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            return function(*args, **kwargs)

        return wrapper
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
DECORATED_OPERATOR_CONFTEST = textwrap.dedent(
    """
    import ast

    from conftest import traced
    from pytest_gremlins.instrumentation.transformer import get_default_registry

    OFFSET = {offset}


    class SiblingConstantOperator:
        name = 'sibling-constant'
        description = 'offsets integer literals'

        @traced
        def can_mutate(self, node):
            return isinstance(node, ast.Constant) and type(node.value) is int

        @traced
        def mutate(self, node):
            return [ast.Constant(value=node.value + OFFSET)]


    get_default_registry().register(SiblingConstantOperator)
    """
)
BORROWING_OPERATOR_CONFTEST = textwrap.dedent(
    """
    from b.conftest import int_can_mutate, offset_mutate
    from pytest_gremlins.instrumentation.transformer import get_default_registry


    class SiblingConstantOperator:
        name = 'sibling-constant'
        description = 'offsets integer literals'
        offset = {offset}
        can_mutate = int_can_mutate
        mutate = offset_mutate


    get_default_registry().register(SiblingConstantOperator)
    """
)
LENDING_CONFTEST = textwrap.dedent(
    """
    import ast


    def int_can_mutate(self, node):
        return isinstance(node, ast.Constant) and type(node.value) is int


    def offset_mutate(self, node):
        return [ast.Constant(value=node.value + self.offset)]
    """
)
PROTOCOL_ROOT_OPERATOR = textwrap.dedent(
    """
    import ast

    from pytest_gremlins.instrumentation.transformer import get_default_registry
    from pytest_gremlins.operators.protocol import GremlinOperator


    class RootConstantOperator(GremlinOperator):
        @property
        def name(self):
            return 'root-constant'

        @property
        def description(self):
            return 'offsets integer literals'

        def can_mutate(self, node):
            return isinstance(node, ast.Constant) and type(node.value) is int

        def mutate(self, node):
            return [ast.Constant(value=node.value + 1)]


    get_default_registry().register(RootConstantOperator)
    """
)
TARGET = 'def limit():\n    return 41\n'
TARGET_TEST = 'from target import limit\n\n\ndef test_limit():\n    assert limit() < 50\n'
SIBLING_TEST = 'def test_unrelated():\n    assert True\n'
PLAIN_CONFTEST = 'import pytest\n\n\n@pytest.fixture\ndef unrelated():\n    return 1\n'
GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=sibling-constant', '--gremlin-cache')
MISSED_EVERYTHING = 'Cache: 0 hits, 1 misses (0% hit rate)'
HIT_EVERYTHING = 'Cache: 1 hits, 0 misses (100% hit rate)'


def _sibling_layout(pytester: pytest.Pytester, *, as_packages: bool) -> None:
    pytester.makeconftest(ROOT_CONFTEST)
    pytester.makepyfile(target=TARGET)
    for directory in ('a', 'b'):
        pytester.mkdir(directory)
        if as_packages:
            (pytester.path / directory / '__init__.py').write_text('')
    (pytester.path / 'a' / 'test_sibling.py').write_text(SIBLING_TEST)
    (pytester.path / 'b' / 'test_target.py').write_text(TARGET_TEST)


@pytest.fixture
def operator_conftest(pytester: pytest.Pytester) -> Path:
    _sibling_layout(pytester, as_packages=False)
    path = pytester.path / 'a' / 'conftest.py'
    path.write_text(OPERATOR_CONFTEST.format(offset=1))
    return path


@pytest.fixture(params=[False, True], ids=['rootless', 'packages'])
def as_packages(request: pytest.FixtureRequest) -> bool:
    return bool(request.param)


@pytest.mark.medium
class DescribeSiblingConftestOperatorInCacheKey:
    @pytest.mark.usefixtures('operator_conftest')
    def it_hits_the_cache_on_a_warm_run_with_nothing_changed(self, pytester: pytest.Pytester) -> None:
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        warm = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        warm.stdout.fnmatch_lines([HIT_EVERYTHING])

    def it_misses_the_cache_after_the_sibling_operator_is_edited(
        self, pytester: pytest.Pytester, operator_conftest: Path
    ) -> None:
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')
        operator_conftest.write_text(OPERATOR_CONFTEST.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        edited.stdout.fnmatch_lines([MISSED_EVERYTHING])

    @pytest.mark.parametrize('argument_order', [('a', 'b'), ('b', 'a')])
    def it_misses_after_the_operator_conftest_is_edited_when_the_other_directory_has_its_own_conftest(
        self, pytester: pytest.Pytester, operator_conftest: Path, argument_order: tuple[str, str]
    ) -> None:
        (pytester.path / 'b' / 'conftest.py').write_text(PLAIN_CONFTEST)
        pytester.runpytest_subprocess(*GREMLIN_ARGS, *argument_order)
        operator_conftest.write_text(OPERATOR_CONFTEST.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, *argument_order)

        edited.stdout.fnmatch_lines([MISSED_EVERYTHING])

    def it_misses_after_editing_an_operator_whose_methods_a_rootdir_conftest_decorator_wraps(
        self, pytester: pytest.Pytester
    ) -> None:
        _sibling_layout(pytester, as_packages=True)
        operator = pytester.path / 'a' / 'conftest.py'
        operator.write_text(DECORATED_OPERATOR_CONFTEST.format(offset=1))
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')
        operator.write_text(DECORATED_OPERATOR_CONFTEST.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        edited.stdout.fnmatch_lines([MISSED_EVERYTHING])

    def it_misses_after_editing_an_operator_whose_methods_come_from_a_sibling_conftest(
        self, pytester: pytest.Pytester, as_packages: bool
    ) -> None:
        _sibling_layout(pytester, as_packages=as_packages)
        (pytester.path / 'b' / 'conftest.py').write_text(LENDING_CONFTEST)
        operator = pytester.path / 'a' / 'conftest.py'
        operator.write_text(BORROWING_OPERATOR_CONFTEST.format(offset=1))
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')
        operator.write_text(BORROWING_OPERATOR_CONFTEST.format(offset=100))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        edited.stdout.fnmatch_lines([MISSED_EVERYTHING])

    def it_misses_after_editing_the_conftest_a_borrowed_method_comes_from(
        self, pytester: pytest.Pytester, as_packages: bool
    ) -> None:
        _sibling_layout(pytester, as_packages=as_packages)
        lender = pytester.path / 'b' / 'conftest.py'
        lender.write_text(LENDING_CONFTEST)
        (pytester.path / 'a' / 'conftest.py').write_text(BORROWING_OPERATOR_CONFTEST.format(offset=1))
        pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')
        lender.write_text(LENDING_CONFTEST.replace('self.offset', 'self.offset + 1'))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS, 'a', 'b')

        edited.stdout.fnmatch_lines([MISSED_EVERYTHING])

    def it_hits_on_a_warm_run_for_a_rootdir_conftest_operator_that_subclasses_the_protocol(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makeconftest(ROOT_CONFTEST + PROTOCOL_ROOT_OPERATOR)
        pytester.makepyfile(target=TARGET, test_target=TARGET_TEST)
        args = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=root-constant', '--gremlin-cache')
        pytester.runpytest_subprocess(*args)

        warm = pytester.runpytest_subprocess(*args)

        warm.stdout.fnmatch_lines([HIT_EVERYTHING])
