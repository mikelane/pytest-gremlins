"""The plugin records which collected tests the lightweight runner may execute."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.parallel.lightweight import write_safe_tests

TARGET = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

TESTS = """
import pytest
from sample import classify

def test_plain():
    assert classify(11) == 'big'

class TestGroup:
    def test_method(self):
        assert classify(1) == 'small'

@pytest.mark.parametrize('n', [1, 2])
def test_param(n):
    assert classify(n) == 'small'

def test_fixture(tmp_path):
    assert classify(1) == 'small'

async def test_async():
    assert classify(1) == 'small'
"""


@pytest.mark.medium
class DescribeLightweightSafeWiring:
    """Only plain tests reach the safe-tests file, with node IDs as they appear in test commands."""

    def it_records_only_plain_tests_for_the_runner(
        self,
        pytester_with_markers: pytest.Pytester,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        recorded: list[list[str]] = []

        def spy(instrumented_dir: Path, safe_node_ids: Iterable[str]) -> None:
            recorded.append(sorted(safe_node_ids))
            write_safe_tests(instrumented_dir, safe_node_ids)

        monkeypatch.setattr(plugin, 'write_safe_tests', spy)
        pytester_with_markers.makepyfile(sample=TARGET)
        pytester_with_markers.makepyfile(test_sample=TESTS)

        pytester_with_markers.runpytest_inprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '-p',
            'no:cacheprovider',
        )

        assert recorded == [['test_sample.py::TestGroup::test_method', 'test_sample.py::test_plain']]
