"""Tests for _write_instrumented_sources future-import ordering fix."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from pytest_gremlins.plugin import _write_instrumented_sources


def _parse_final_source(tmp_path: Path, source: str) -> list[ast.stmt]:
    """Parse source, instrument it, and return the AST body of the result."""
    tree = ast.parse(source)
    original_path = str(tmp_path / 'mymod.py')
    result_dir = _write_instrumented_sources({original_path: tree}, tmp_path)
    sources = json.loads((result_dir / 'sources.json').read_text())
    parsed: list[ast.stmt] = ast.parse(sources['mymod']).body
    return parsed


def _node_names(nodes: list[ast.stmt]) -> list[str]:
    """Return a short label for each top-level statement to make assertions readable."""
    labels = []
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            labels.append('future_import')
        elif isinstance(node, ast.Import):
            labels.append('import')
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            labels.append(f'assign:{node.targets[0].id}')
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            labels.append('docstring')
        elif isinstance(node, ast.Delete):
            labels.append('del')
        else:
            labels.append(type(node).__name__)
    return labels


@pytest.mark.medium
class DescribeWriteInstrumentedSources:
    """_write_instrumented_sources places injection after future imports and docstrings."""

    def it_injects_gremlin_active_assignment_before_regular_code(self, tmp_path: Path) -> None:
        body = _parse_final_source(tmp_path, 'import os\nx = 1\n')
        labels = _node_names(body)

        # injection (assign:__gremlin_active__) must appear before user code (assign:x)
        assert 'assign:__gremlin_active__' in labels
        assert labels.index('assign:__gremlin_active__') < labels.index('assign:x')

    def it_places_injection_after_future_import(self, tmp_path: Path) -> None:
        body = _parse_final_source(tmp_path, 'from __future__ import annotations\nimport os\nx = 1\n')
        labels = _node_names(body)

        assert 'future_import' in labels
        assert 'assign:__gremlin_active__' in labels
        # future import must come before the injection
        assert labels.index('future_import') < labels.index('assign:__gremlin_active__')

    def it_produces_valid_syntax_when_source_has_future_import(self, tmp_path: Path) -> None:
        # The core regression: prepending before future import causes SyntaxError.
        # Asserting ast.parse succeeds (via _parse_final_source) AND that __future__ is still first.
        source = 'from __future__ import annotations\n\ndef foo(x: int) -> str:\n    return str(x)\n'
        labels = _node_names(_parse_final_source(tmp_path, source))
        assert labels[0] == 'future_import', f'Expected future_import first, got: {labels}'

    def it_places_module_docstring_before_future_import_and_injection(self, tmp_path: Path) -> None:
        body = _parse_final_source(
            tmp_path,
            '"""Module docstring."""\nfrom __future__ import annotations\nimport os\n',
        )
        labels = _node_names(body)

        assert labels[0] == 'docstring', f'Expected docstring first, got: {labels}'
        assert labels[1] == 'future_import', f'Expected future_import second, got: {labels}'
        assert 'assign:__gremlin_active__' in labels
        assert labels.index('future_import') < labels.index('assign:__gremlin_active__')

    def it_places_docstring_first_when_there_is_no_future_import(self, tmp_path: Path) -> None:
        body = _parse_final_source(tmp_path, '"""Just a docstring."""\nx = 1\n')
        labels = _node_names(body)

        assert labels[0] == 'docstring', f'Expected docstring first, got: {labels}'
        assert 'assign:__gremlin_active__' in labels
        assert labels.index('docstring') < labels.index('assign:__gremlin_active__')

    def it_handles_source_with_no_special_headers(self, tmp_path: Path) -> None:
        body = _parse_final_source(tmp_path, 'x = 42\n')
        labels = _node_names(body)

        # injection must be present and precede user code
        assert 'assign:__gremlin_active__' in labels
        assert labels.index('assign:__gremlin_active__') < labels.index('assign:x')

    def it_includes_gremlin_active_variable_in_output(self, tmp_path: Path) -> None:
        tree = ast.parse('from __future__ import annotations\nx = 1\n')
        original_path = str(tmp_path / 'mymod.py')
        result_dir = _write_instrumented_sources({original_path: tree}, tmp_path)
        sources = json.loads((result_dir / 'sources.json').read_text())
        assert '__gremlin_active__' in sources['mymod']

    def it_handles_empty_module_body(self, tmp_path: Path) -> None:
        body = _parse_final_source(tmp_path, '')
        labels = _node_names(body)

        # Empty source gets only the injection nodes -- no user code at all
        assert 'assign:__gremlin_active__' in labels
        assert labels[0] == 'import', f'Expected import (_gremlin_os) first, got: {labels}'

    def it_places_injection_after_multiple_future_imports(self, tmp_path: Path) -> None:
        source = 'from __future__ import annotations\nfrom __future__ import division\nimport os\n'
        body = _parse_final_source(tmp_path, source)
        labels = _node_names(body)

        future_indices = [i for i, label in enumerate(labels) if label == 'future_import']
        injection_index = labels.index('assign:__gremlin_active__')

        assert len(future_indices) == 2, f'Expected 2 future imports, got {len(future_indices)}: {labels}'
        assert all(fi < injection_index for fi in future_indices), (
            f'All future imports must precede injection: {labels}'
        )

    def it_places_injection_after_docstring_and_multiple_future_imports(self, tmp_path: Path) -> None:
        source = '"""Module docstring."""\nfrom __future__ import annotations\nfrom __future__ import division\nx = 1\n'
        body = _parse_final_source(tmp_path, source)
        labels = _node_names(body)

        assert labels[0] == 'docstring', f'Expected docstring first, got: {labels}'
        future_indices = [i for i, label in enumerate(labels) if label == 'future_import']
        injection_index = labels.index('assign:__gremlin_active__')
        user_code_index = labels.index('assign:x')

        assert len(future_indices) == 2, f'Expected 2 future imports, got {len(future_indices)}: {labels}'
        assert all(fi < injection_index for fi in future_indices), (
            f'All future imports must precede injection: {labels}'
        )
        assert injection_index < user_code_index, f'Injection must precede user code: {labels}'
