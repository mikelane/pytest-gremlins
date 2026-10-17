"""Tests for scripts/profile_gremlins.py -- report files must satisfy the end-of-file-fixer hook."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'profile_gremlins.py'


MODULE_NAME = 'profile_gremlins_under_test'


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the script by path (``scripts/`` is not importable); dataclasses need it in ``sys.modules``."""
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, MODULE_NAME, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.medium
class DescribeWriteReportText:
    @pytest.mark.parametrize(
        'text',
        ['no trailing newline', 'one trailing newline\n', 'three trailing newlines\n\n\n'],
    )
    def it_ends_the_file_with_exactly_one_newline(self, script: ModuleType, tmp_path: Path, text: str) -> None:
        report = tmp_path / 'report.txt'

        script.write_report_text(report, text)

        written = report.read_text()
        assert written.endswith('\n')
        assert not written.endswith('\n\n')

    def it_preserves_the_text_before_the_trailing_newlines(self, script: ModuleType, tmp_path: Path) -> None:
        report = tmp_path / 'report.txt'

        script.write_report_text(report, 'first line\nsecond line\n\n')

        assert report.read_text() == 'first line\nsecond line\n'


@pytest.mark.medium
class DescribeReportWriters:
    def it_routes_both_the_stats_writer_and_the_json_writer_through_the_helper(self) -> None:
        calling_functions = {
            function.name
            for function in ast.walk(ast.parse(SCRIPT.read_text()))
            if isinstance(function, ast.FunctionDef)
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'write_report_text'
        }

        assert calling_functions == {'run_cprofile_analysis', 'main'}

    def it_writes_a_stats_report_with_one_trailing_newline(self, script: ModuleType, tmp_path: Path) -> None:
        target = tmp_path / 'target'
        target.mkdir()
        (target / 'module.py').write_text('def add(a, b):\n    return a + b\n')
        output_dir = tmp_path / 'out'
        output_dir.mkdir()

        stats_report = script.run_cprofile_analysis(target, output_dir)

        written = stats_report.read_text()
        assert written.endswith('\n')
        assert not written.endswith('\n\n')
