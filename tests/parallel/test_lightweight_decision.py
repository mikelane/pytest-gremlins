"""Tests for the single decision point that routes a gremlin to the lightweight runner."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from pytest_gremlins.parallel.lightweight import (
    build_lightweight_command,
    write_safe_tests,
)

SOURCES_ENV = 'PYTEST_GREMLINS_SOURCES_FILE'


def _instrumented_dir(tmp_path: Path, safe_ids: list[str] | None) -> dict[str, str]:
    (tmp_path / 'sources.json').write_text('{}')
    (tmp_path / 'gremlin_lightweight_runner.py').write_text('')
    if safe_ids is not None:
        write_safe_tests(tmp_path, safe_ids)
    return {SOURCES_ENV: str(tmp_path / 'sources.json')}


def _command(*node_ids: str) -> list[str]:
    return [sys.executable, 'bootstrap.py', '-x', *node_ids]


@pytest.mark.medium
class DescribeBuildLightweightCommand:
    """The lightweight runner is used only when every selected test is known to be safe."""

    def it_uses_the_runner_when_every_selected_test_is_safe(self, tmp_path: Path) -> None:
        env = _instrumented_dir(tmp_path, ['t.py::test_a', 't.py::test_b'])

        command = build_lightweight_command(_command('t.py::test_a', 't.py::test_b'), env)

        assert command == [
            sys.executable,
            str(tmp_path / 'gremlin_lightweight_runner.py'),
            't.py::test_a',
            't.py::test_b',
        ]

    def it_falls_back_when_any_selected_test_is_not_safe(self, tmp_path: Path) -> None:
        env = _instrumented_dir(tmp_path, ['t.py::test_a'])

        assert build_lightweight_command(_command('t.py::test_a', 't.py::test_param[1]'), env) is None

    def it_falls_back_when_the_safe_set_is_empty(self, tmp_path: Path) -> None:
        env = _instrumented_dir(tmp_path, [])

        assert build_lightweight_command(_command('t.py::test_a'), env) is None

    def it_falls_back_when_no_safe_set_was_recorded(self, tmp_path: Path) -> None:
        env = _instrumented_dir(tmp_path, None)

        assert build_lightweight_command(_command('t.py::test_a'), env) is None

    def it_falls_back_when_the_safe_set_file_is_corrupt(self, tmp_path: Path) -> None:
        env = _instrumented_dir(tmp_path, ['t.py::test_a'])
        (tmp_path / 'lightweight_safe_tests.json').write_text('not json')

        assert build_lightweight_command(_command('t.py::test_a'), env) is None
