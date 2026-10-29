"""A project-local operator helper module is part of the cache key (#882).

A conftest.py that imports an operator from a helper module under the rootdir registers it. The helper is neither a
mutation target nor a conftest, so its content hash has to join the key or editing it reuses stale verdicts.
"""

from __future__ import annotations

import textwrap

import pytest

OPERATOR_TEMPLATE = textwrap.dedent(
    """
    import ast


    class LocalConstantOperator:
        name = 'local-constant'
        description = 'rewrites integer literals'

        def can_mutate(self, node):
            return isinstance(node, ast.Constant) and type(node.value) is int

        def mutate(self, node):
            return [ast.Constant(value=node.value + {delta})]
    """
)
CONFTEST = textwrap.dedent(
    """
    import pytest
    from pytest_gremlins.instrumentation.transformer import get_default_registry
    from gremlin_ops import LocalConstantOperator

    get_default_registry().register(LocalConstantOperator)


    def pytest_configure(config):
        config.addinivalue_line('markers', 'small: fast tests')


    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(items):
        for item in items:
            item.add_marker(pytest.mark.small)
    """
)
TARGET = 'def limit():\n    return 41\n'
TARGET_TEST = 'from target import limit\n\n\ndef test_limit():\n    assert limit() == 41\n'
GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=local-constant', '--gremlin-cache')


@pytest.mark.medium
class DescribeProjectLocalOperatorHelperModule:
    def it_misses_the_cache_after_the_helper_module_changes(self, pytester: pytest.Pytester) -> None:
        pytester.makeconftest(CONFTEST)
        pytester.makepyfile(target=TARGET, test_target=TARGET_TEST, gremlin_ops=OPERATOR_TEMPLATE.format(delta=1))
        cold = pytester.runpytest_subprocess(*GREMLIN_ARGS)
        cold.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])
        # The operator now produces an equivalent mutant (41 + 0), which no test can zap.
        pytester.makepyfile(gremlin_ops=OPERATOR_TEMPLATE.format(delta=0))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS)

        edited.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])


PATH_LOADED_CONFTEST = textwrap.dedent(
    """
    import importlib.util
    import pathlib
    import pytest
    from pytest_gremlins.instrumentation.transformer import get_default_registry

    _spec = importlib.util.spec_from_file_location('gremlin_ops', pathlib.Path(__file__).parent / 'gremlin_ops.py')
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    get_default_registry().register(_module.LocalConstantOperator)


    def pytest_configure(config):
        config.addinivalue_line('markers', 'small: fast tests')


    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(items):
        for item in items:
            item.add_marker(pytest.mark.small)
    """
)


@pytest.mark.medium
class DescribePathLoadedOperatorHelperModule:
    def it_hits_the_cache_when_the_helper_module_is_unchanged(self, pytester: pytest.Pytester) -> None:
        pytester.makeconftest(PATH_LOADED_CONFTEST)
        pytester.makepyfile(target=TARGET, test_target=TARGET_TEST, gremlin_ops=OPERATOR_TEMPLATE.format(delta=1))
        cold = pytester.runpytest_subprocess(*GREMLIN_ARGS)
        cold.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])

        warm = pytester.runpytest_subprocess(*GREMLIN_ARGS)

        warm.stdout.fnmatch_lines(['Cache: 1 hits, 0 misses (100% hit rate)'])

    def it_misses_the_cache_after_the_helper_module_changes(self, pytester: pytest.Pytester) -> None:
        pytester.makeconftest(PATH_LOADED_CONFTEST)
        pytester.makepyfile(target=TARGET, test_target=TARGET_TEST, gremlin_ops=OPERATOR_TEMPLATE.format(delta=1))
        pytester.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])
        pytester.makepyfile(gremlin_ops=OPERATOR_TEMPLATE.format(delta=0))

        edited = pytester.runpytest_subprocess(*GREMLIN_ARGS)

        edited.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])
