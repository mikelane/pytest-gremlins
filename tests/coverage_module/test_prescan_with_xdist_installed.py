"""Tests for issue #502: the real pre-scan in a project that has pytest-xdist installed.

Each test runs the real ``coverage run -m pytest`` pre-scan subprocess against a
throwaway project that has pytest-xdist installed (it is in this repo's dev deps)
and asserts the coverage map still contains every test that executes the target.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.plugin import _run_tests_with_coverage

if TYPE_CHECKING:
    from pathlib import Path

_TARGET = 'def is_big(x):\n    return x > 10\n\n\ndef is_small(x):\n    return x < 3\n'
_NODE_IDS = ['test_target.py::test_big', 'test_target.py::test_small']


def _write_project(rootdir: Path, test_source: str, conftest_source: str = '') -> None:
    (rootdir / 'target.py').write_text(_TARGET)
    (rootdir / 'test_target.py').write_text(test_source)
    if conftest_source:
        (rootdir / 'conftest.py').write_text(conftest_source)


def _prescan(rootdir: Path) -> dict[str, dict[str, list[int]]]:
    return _run_tests_with_coverage(
        list(_NODE_IDS),
        rootdir,
        coverage_include=[str((rootdir / 'target.py').resolve())],
    )


_PLAIN_TESTS = (
    'from target import is_big, is_small\n\n\n'
    'def test_big():\n    assert is_big(11)\n\n\n'
    'def test_small():\n    assert is_small(1)\n'
)


@pytest.mark.medium
class DescribePrescanWithXdistInstalled:
    """The pre-scan must not lose tests that run fine under plain pytest."""

    def it_maps_tests_that_use_the_xdist_worker_id_fixture(self, tmp_path: Path) -> None:
        _write_project(
            tmp_path,
            'from target import is_big, is_small\n\n\n'
            'def test_big():\n    assert is_big(11)\n\n\n'
            'def test_small(worker_id):\n    assert is_small(1)\n',
        )

        assert sorted(_prescan(tmp_path)) == _NODE_IDS

    def it_maps_tests_when_conftest_implements_an_xdist_hook(self, tmp_path: Path) -> None:
        _write_project(tmp_path, _PLAIN_TESTS, conftest_source='def pytest_configure_node(node):\n    pass\n')

        assert sorted(_prescan(tmp_path)) == _NODE_IDS

    def it_maps_tests_when_pytest_addopts_env_requests_workers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_project(tmp_path, _PLAIN_TESTS)
        monkeypatch.setenv('PYTEST_ADDOPTS', '-n 2')

        assert sorted(_prescan(tmp_path)) == _NODE_IDS

    def it_maps_tests_in_a_plain_project_control(self, tmp_path: Path) -> None:
        """Negative control: with nothing xdist-specific, the real pre-scan maps both tests."""
        _write_project(tmp_path, _PLAIN_TESTS)

        assert sorted(_prescan(tmp_path)) == _NODE_IDS
