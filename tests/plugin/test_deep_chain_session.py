"""A chain the transformer instruments but ast.unparse cannot render must skip that file, not the session (#814).

``transform_source`` now accepts a long left-leaning operator chain. The instrumented tree is still as deep as
the chain, and ``ast.unparse`` recurses once per level, so writing it can raise ``RecursionError``. That file
joins the skipped files; the rest of the run continues.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.instrumentation.transformer import transform_source

pytest.importorskip('xdist')

RunPytestIsolated = Callable[..., pytest.RunResult]

CHAIN_TERMS = 200
CHAIN_SOURCE = 'def big(x):\n    return ' + ' + '.join(['x'] * CHAIN_TERMS) + '\n'
AGE_SOURCE = 'def is_adult(age):\n    return age >= 18\n'
PROJECT_TESTS = (
    'from demo.age import is_adult\n'
    'from demo.chain import big\n\n\n'
    'def test_big():\n    assert big(1) == 200\n\n\n'
    'def test_is_adult():\n    assert is_adult(20)\n    assert not is_adult(17)\n'
)


@pytest.mark.medium
class DescribeWriteInstrumentedSourcesWithUnrenderableTree:
    """A tree too deep to unparse is reported, not raised."""

    def it_reports_the_file_it_could_not_write(self, tmp_path: Path) -> None:
        _, tree = transform_source(CHAIN_SOURCE, 'chain.py')
        unwritable: dict[str, str] = {}

        plugin._write_instrumented_sources({'chain.py': tree}, tmp_path, unwritable=unwritable)

        assert list(unwritable) == ['chain.py']
        assert unwritable['chain.py'].startswith('RecursionError')

    def it_still_writes_the_files_it_could_render(self, tmp_path: Path) -> None:
        _, deep_tree = transform_source(CHAIN_SOURCE, 'chain.py')
        _, shallow_tree = transform_source(AGE_SOURCE, 'age.py')
        unwritable: dict[str, str] = {}

        instrumented_dir = plugin._write_instrumented_sources(
            {'chain.py': deep_tree, 'age.py': shallow_tree}, tmp_path, unwritable=unwritable
        )

        written = (instrumented_dir / 'sources.json').read_text()
        assert 'age.py' in written
        assert 'chain.py' not in written


@pytest.mark.medium
class DescribeGremlinRunWithDeepChain:
    """A 200-term chain next to an ordinary module does not crash the session."""

    def it_finishes_the_run_and_tests_the_ordinary_module(
        self, pytester: pytest.Pytester, run_pytest_isolated: RunPytestIsolated
    ) -> None:
        pytester.makepyprojecttoml('[tool.pytest.ini_options]\npythonpath = ["src"]\n')
        pytester.mkdir('src')
        pytester.mkdir('src/demo')
        pytester.path.joinpath('src', 'demo', '__init__.py').write_text('')
        pytester.path.joinpath('src', 'demo', 'chain.py').write_text(CHAIN_SOURCE)
        pytester.path.joinpath('src', 'demo', 'age.py').write_text(AGE_SOURCE)
        pytester.mkdir('tests')
        pytester.path.joinpath('tests', 'test_demo.py').write_text(PROJECT_TESTS)

        result = run_pytest_isolated(pytester, '--gremlins', '--gremlin-targets', 'src/demo')

        output = result.stdout.str() + result.stderr.str()
        assert 'INTERNALERROR' not in output
        result.stdout.fnmatch_lines(['*Zapped: * gremlins*'])
