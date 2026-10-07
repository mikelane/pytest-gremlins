"""Tests for _write_instrumented_sources future-import ordering fix."""

from __future__ import annotations

import ast
import base64
import json
import marshal
from pathlib import Path
import types
import warnings

import pytest

from pytest_gremlins.instrumentation.origin_finder import (
    InstrumentedSources,
    file_identity,
    normalize_origin,
)
from pytest_gremlins.plugin import (
    _add_source_file,
    _child_optimize_level,
    _encode_compiled,
    _inject_gremlin_active,
    _write_instrumented_sources,
)


def _parse_final_source(tmp_path: Path, source: str) -> list[ast.stmt]:  # noqa: ARG001
    """Parse source, inject the activation variable, and return the AST body of the result."""
    return _inject_gremlin_active(ast.parse(source)).body


def _written_code(tmp_path: Path, source: str, name: str = 'mymod.py') -> tuple[str, types.CodeType]:
    """Instrument ``source`` as ``name`` and return its origin and the code object shipped in sources.json."""
    original_path = str(tmp_path / name)
    result_dir = _write_instrumented_sources({original_path: ast.parse(source)}, tmp_path)
    entry = json.loads((result_dir / 'sources.json').read_text())[normalize_origin(original_path)]
    code: types.CodeType = marshal.loads(base64.b64decode(entry['code']))  # noqa: S302
    return entry['origin'], code


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

    def it_puts_the_injection_first_when_the_source_has_no_docstring_or_future_import(self, tmp_path: Path) -> None:
        body = _parse_final_source(tmp_path, 'x = 42\n')
        labels = _node_names(body)

        assert labels == ['import', 'assign:__gremlin_active__', 'del', 'assign:x']

    def it_includes_gremlin_active_variable_in_output(self, tmp_path: Path) -> None:
        _, code = _written_code(tmp_path, 'from __future__ import annotations\nx = 1\n')
        namespace: dict[str, object] = {}

        exec(code, namespace)  # noqa: S102

        assert '__gremlin_active__' in namespace

    def it_records_the_source_path_without_following_symlinks_as_the_origin(self, tmp_path: Path) -> None:
        real = tmp_path / 'real.py'
        real.write_text('x = 1\n')
        original_path = tmp_path / 'mymod.py'
        original_path.symlink_to(real)
        result_dir = _write_instrumented_sources({str(original_path): ast.parse('x = 1\n')}, tmp_path)
        sources = json.loads((result_dir / 'sources.json').read_text())
        assert sources[normalize_origin(str(real))]['origin'] == str(original_path)

    def it_emits_only_the_injection_for_an_empty_module(self, tmp_path: Path) -> None:
        body = _parse_final_source(tmp_path, '')
        labels = _node_names(body)

        assert labels == ['import', 'assign:__gremlin_active__', 'del']

    def it_places_injection_after_multiple_future_imports(self, tmp_path: Path) -> None:
        source = 'from __future__ import annotations\nfrom __future__ import division\nimport os\n'
        body = _parse_final_source(tmp_path, source)
        labels = _node_names(body)

        assert labels == ['future_import', 'future_import', 'import', 'assign:__gremlin_active__', 'del', 'import']

    def it_places_injection_after_docstring_and_multiple_future_imports(self, tmp_path: Path) -> None:
        source = '"""Module docstring."""\nfrom __future__ import annotations\nfrom __future__ import division\nx = 1\n'
        body = _parse_final_source(tmp_path, source)
        labels = _node_names(body)

        assert labels == [
            'docstring',
            'future_import',
            'future_import',
            'import',
            'assign:__gremlin_active__',
            'del',
            'assign:x',
        ]


@pytest.mark.medium
class DescribeLightweightRunnerDisabled:
    """The lightweight runner cannot reproduce pytest's environment, so it is not offered (issue #538)."""

    def it_writes_no_lightweight_runner_into_the_instrumented_directory(self, tmp_path: Path) -> None:
        asts = {str(tmp_path / 'mymod.py'): ast.parse('x = 1')}

        instrumented_dir = _write_instrumented_sources(asts, tmp_path)

        assert not (instrumented_dir / 'gremlin_lightweight_runner.py').exists()

    def it_still_writes_the_bootstrap_the_pytest_path_runs_through(self, tmp_path: Path) -> None:
        asts = {str(tmp_path / 'mymod.py'): ast.parse('x = 1')}

        instrumented_dir = _write_instrumented_sources(asts, tmp_path)

        assert (instrumented_dir / 'gremlin_bootstrap.py').exists()


def _written_entries(tmp_path: Path, relative_paths: list[str]) -> InstrumentedSources:
    """Instrument a trivial module at each relative path and return the sources.json entries by key."""
    asts = {str(tmp_path / relative): ast.parse('x = 1\n') for relative in relative_paths}
    result_dir = _write_instrumented_sources(asts, tmp_path)
    entries: InstrumentedSources = json.loads((result_dir / 'sources.json').read_text())
    return entries


@pytest.mark.medium
class DescribeWriteInstrumentedSourceKeys:
    """Entries are keyed by the file they came from; what the module is called is the import system's business."""

    @pytest.mark.parametrize(
        'relative_path',
        ['mymod.py', 'pkg/core.py', 'pkg/__init__.py', 'src/pkg/sub/__init__.py', '__init__.py'],
    )
    def it_keys_a_source_by_the_normalized_real_path_of_its_file(self, tmp_path: Path, relative_path: str) -> None:
        entries = _written_entries(tmp_path, [relative_path])

        assert list(entries) == [normalize_origin(str(tmp_path / relative_path))]

    def it_records_no_module_name(self, tmp_path: Path) -> None:
        entries = _written_entries(tmp_path, ['pkg/__init__.py'])

        assert sorted(next(iter(entries.values()))) == ['code', 'file_names', 'identity', 'origin']

    def it_ships_the_source_as_code_compiled_under_the_origin_path(self, tmp_path: Path) -> None:
        origin, code = _written_code(tmp_path, 'x = 1\n')

        assert code.co_filename == origin == str(tmp_path / 'mymod.py')

    def it_keeps_the_line_numbers_of_the_original_file(self, tmp_path: Path) -> None:
        padded = '# padding\n' * 30 + 'def f(x):\n    return x > 0\n'
        _, code = _written_code(tmp_path, padded)
        namespace: dict[str, object] = {}

        exec(code, namespace)  # noqa: S102

        assert namespace['f'].__code__.co_firstlineno == 31  # type: ignore[attr-defined]

    def it_records_the_device_and_inode_of_the_file(self, tmp_path: Path) -> None:
        tmp_path.joinpath('real_mod.py').write_text('x = 1\n')
        entries = _written_entries(tmp_path, ['real_mod.py'])

        assert next(iter(entries.values()))['identity'] == file_identity(str(tmp_path / 'real_mod.py'))

    def it_records_no_identity_for_a_file_that_is_not_on_disk(self, tmp_path: Path) -> None:
        entries = _written_entries(tmp_path, ['ghost_mod.py'])

        assert next(iter(entries.values()))['identity'] is None

    def it_lists_the_lowercased_file_name_the_file_may_be_imported_as(self, tmp_path: Path) -> None:
        entries = _written_entries(tmp_path, ['MixedCase.py'])

        assert next(iter(entries.values()))['file_names'] == ['mixedcase.py']

    def it_lists_the_file_names_of_the_dropped_spellings_of_a_file(self, tmp_path: Path) -> None:
        tree = ast.parse('x = 1\n')
        target = str(tmp_path / 'core.py')

        result_dir = _write_instrumented_sources({target: tree}, tmp_path, {target: [str(tmp_path / 'alias.py')]})
        entry = next(iter(json.loads((result_dir / 'sources.json').read_text()).values()))

        assert entry['file_names'] == ['alias.py', 'core.py']

    def it_keeps_every_file_even_when_the_import_system_would_serve_only_one_of_a_shared_name(
        self, tmp_path: Path
    ) -> None:
        entries = _written_entries(tmp_path, ['pkg/__init__.py', 'pkg.py'])

        assert sorted(entry['origin'] for entry in entries.values()) == sorted(
            [str(tmp_path / 'pkg' / '__init__.py'), str(tmp_path / 'pkg.py')]
        )

    def it_resolves_a_relative_path_against_the_rootdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        elsewhere = tmp_path / 'elsewhere'
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        result_dir = _write_instrumented_sources({'mymod.py': ast.parse('x = 1\n')}, tmp_path)

        assert list(json.loads((result_dir / 'sources.json').read_text())) == [
            normalize_origin(str(tmp_path / 'mymod.py'))
        ]


@pytest.mark.medium
class DescribeAddSourceFileSkipsUncompilableFiles:
    """A file that parses but cannot compile is skipped, as it never was an importable module."""

    @pytest.mark.parametrize('source', ['return 1 > 0\n', 'break\n', 'nonlocal x\n', 'await x\n'])
    def it_skips_a_file_that_parses_but_does_not_compile(self, tmp_path: Path, source: str) -> None:
        path = tmp_path / 'template.py'
        path.write_text(source)
        source_files: dict[str, str] = {}

        _add_source_file(path, source_files)

        assert source_files == {}

    def it_keeps_a_file_that_compiles(self, tmp_path: Path) -> None:
        path = tmp_path / 'real.py'
        path.write_text('x = 1 > 0\n')
        source_files: dict[str, str] = {}

        _add_source_file(path, source_files)

        assert list(source_files) == [str(path)]


_ASSERTING_SOURCE = 'def f(x):\n    assert x\n    return x\n'
_SYNTAX_WARNING_SOURCE = 'def f(x):\n    return x is 1\n'


def _has_assert(code: types.CodeType) -> bool:
    """Run the shipped code and report whether its ``assert`` still fires."""
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    try:
        namespace['f'](0)  # type: ignore[operator]
    except AssertionError:
        return True
    return False


@pytest.mark.small
class DescribeChildOptimizeLevel:
    """The optimize level the gremlin subprocess will run with comes from its inherited PYTHONOPTIMIZE."""

    @pytest.mark.parametrize(
        ('value', 'expected'),
        [(None, 0), ('', 0), ('0', 0), ('1', 1), ('2', 2), ('7', 2), ('yes', 1), ('-3', 1)],
    )
    def it_reads_the_level_from_the_environment_the_child_inherits(
        self, monkeypatch: pytest.MonkeyPatch, value: str | None, expected: int
    ) -> None:
        if value is None:
            monkeypatch.delenv('PYTHONOPTIMIZE', raising=False)
        else:
            monkeypatch.setenv('PYTHONOPTIMIZE', value)

        assert _child_optimize_level() == expected


@pytest.mark.small
class DescribeEncodedOptimizeLevel:
    """Shipped code is compiled at the child's optimize level, not the parent's."""

    def _encode(self, source: str) -> types.CodeType:
        encoded = _encode_compiled(ast.parse(source), 'mod.py')
        return marshal.loads(base64.b64decode(encoded))  # noqa: S302

    def it_keeps_asserts_when_the_child_has_no_pythonoptimize(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv('PYTHONOPTIMIZE', raising=False)

        code = self._encode(_ASSERTING_SOURCE)

        assert _has_assert(code)

    def it_strips_asserts_when_the_child_inherits_pythonoptimize(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('PYTHONOPTIMIZE', '1')

        code = self._encode(_ASSERTING_SOURCE)

        assert not _has_assert(code)


@pytest.mark.medium
class DescribeCompileWarningsAreIgnored:
    """A compile-time warning promoted to an error by the session must not drop or break the target."""

    def it_keeps_a_source_whose_compile_warning_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / 'warn.py'
        path.write_text(_SYNTAX_WARNING_SOURCE)
        source_files: dict[str, str] = {}

        with warnings.catch_warnings():
            warnings.simplefilter('error')
            _add_source_file(path, source_files)

        assert list(source_files) == [str(path)]

    def it_encodes_a_module_whose_compile_warning_is_an_error(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            encoded = _encode_compiled(ast.parse(_SYNTAX_WARNING_SOURCE), 'warn.py')

        assert encoded
