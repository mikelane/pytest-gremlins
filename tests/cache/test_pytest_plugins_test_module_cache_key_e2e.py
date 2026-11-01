"""A warm run misses the cache after a test-named pytest_plugins module is edited (#910)."""

from __future__ import annotations

import pytest

pytest_plugins = ['pytester']

GREMLIN_ARGS = ('--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=comparison', '--gremlin-cache')
COLD = 'Cache: 0 hits, 2 misses (0% hit rate)'
TARGET = 'def limit(x):\n    return x > 41\n'
TEST_UTILS = 'import pytest\n\n\n@pytest.fixture\ndef value():\n    return {value}\n'
TEST_A = 'from target import limit\n\n\ndef test_a(value):\n    assert limit(value)\n'


@pytest.mark.medium
class DescribePytestPluginsTestModuleWarmRun:
    def it_misses_the_cache_after_editing_a_test_named_pytest_plugins_module(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        pytester.makepyfile(target=TARGET)
        pytester.mkdir('tests')
        (pytester.path / 'tests' / '__init__.py').write_text('')
        pytester.makeini('[pytest]\npythonpath = .\n')
        (pytester.path / 'tests' / 'conftest.py').write_text("pytest_plugins = ['tests.test_utils']\n")
        (pytester.path / 'tests' / 'test_utils.py').write_text(TEST_UTILS.format(value=42))
        (pytester.path / 'tests' / 'test_a.py').write_text(TEST_A)
        pytester.runpytest_subprocess(*GREMLIN_ARGS).stdout.fnmatch_lines([COLD])
        (pytester.path / 'tests' / 'test_utils.py').write_text(TEST_UTILS.format(value=43))

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS)

        result.stdout.fnmatch_lines([COLD])
