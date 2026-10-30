"""Upgrading a package whose operator a conftest.py registers retires cached verdicts, end to end (#873)."""

from __future__ import annotations

import importlib
import os
import shutil
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

OPERATOR_MODULE = textwrap.dedent(
    """
    import ast


    class ConftestConstantOperator:
        name = 'conftest-constant'
        description = 'increments integer literals'

        def can_mutate(self, node):
            return isinstance(node, ast.Constant) and type(node.value) is int

        def mutate(self, node):
            return [ast.Constant(value=node.value + 1)]
    """
)
CONFTEST = textwrap.dedent(
    """
    import pytest
    from pytest_gremlins.instrumentation.transformer import get_default_registry
    from conftest_ops import ConftestConstantOperator

    get_default_registry().register(ConftestConstantOperator)


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
GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=conftest-constant', '--gremlin-cache')


def _install_dist(site: Path, version: str) -> None:
    dist_info = site / f'conftest_ops_dist-{version}.dist-info'
    dist_info.mkdir(parents=True)
    (dist_info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: conftest_ops_dist\nVersion: {version}\n')
    (dist_info / 'top_level.txt').write_text('conftest_ops\n')
    (dist_info / 'RECORD').write_text('conftest_ops.py,,\n')
    (site / 'conftest_ops.py').write_text(OPERATOR_MODULE)
    importlib.invalidate_caches()


@pytest.fixture
def project(pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    site = tmp_path / 'operator_site'
    site.mkdir()
    _install_dist(site, '1.0')
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(filter(None, [str(site), os.environ.get('PYTHONPATH', '')])))
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(target=TARGET, test_target=TARGET_TEST)
    return site


@pytest.mark.medium
class DescribeConftestOperatorDistributionInCacheKey:
    @pytest.mark.usefixtures('project')
    def it_hits_the_cache_on_a_warm_run_with_nothing_changed(self, pytester: pytest.Pytester) -> None:
        cold = pytester.runpytest_subprocess(*GREMLIN_ARGS)
        cold.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])

        warm = pytester.runpytest_subprocess(*GREMLIN_ARGS)

        warm.stdout.fnmatch_lines(['Cache: 1 hits, 0 misses (100% hit rate)'])

    def it_misses_the_cache_after_the_operator_package_is_upgraded(
        self, pytester: pytest.Pytester, project: Path
    ) -> None:
        cold = pytester.runpytest_subprocess(*GREMLIN_ARGS)
        cold.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])
        shutil.rmtree(project / 'conftest_ops_dist-1.0.dist-info')
        _install_dist(project, '2.0')

        upgraded = pytester.runpytest_subprocess(*GREMLIN_ARGS)

        upgraded.stdout.fnmatch_lines(['Cache: 0 hits, 1 misses (0% hit rate)'])
