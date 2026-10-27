"""Benchmark of the ``sources.json`` payload the parent ships to every gremlin child (#612).

The payload carries each instrumented module as a pickled AST (``tree``) plus unparsed ``source``. Sizes are
compared with the format of PR #610 (an uncompressed pickle) measured in the same run, so the numbers do not
depend on the machine or on the Python version. ``sources_json_baseline.json`` records the accepted ratios; a
metric that grows more than 20% above its baseline fails.
"""

import ast
import base64
import importlib
import importlib.machinery
import inspect
import json
from pathlib import Path
import pickle
import subprocess
import sys
import time
from types import ModuleType
from typing import Any

import pytest

from pytest_gremlins.instrumentation.origin_finder import GremlinLoader
from pytest_gremlins.instrumentation.transformer import transform_source
from pytest_gremlins.plugin import (
    _inject_gremlin_active,
    _write_instrumented_sources,
)

FIXTURE_MODULES = ('argparse', 'textwrap', 'shlex')
BASELINE_FILE = Path(__file__).with_name('sources_json_baseline.json')
ALLOWED_REGRESSION = 1.20
TIMING_REPEATS = 25


def _instrumented_tree(module_name: str) -> tuple[str, ast.Module]:
    path = inspect.getsourcefile(importlib.import_module(module_name))
    assert path is not None
    _, tree = transform_source(Path(path).read_text(encoding='utf-8'), path)
    return path, tree


def _written_entries(tmp_path: Path) -> dict[str, dict[str, Any]]:
    trees = dict(_instrumented_tree(name) for name in FIXTURE_MODULES)
    temp_dir = _write_instrumented_sources(trees, tmp_path)
    entries: dict[str, dict[str, Any]] = json.loads((temp_dir / 'sources.json').read_text())
    return {entry['origin']: entry for entry in entries.values()}


def _legacy_tree(tree: ast.Module) -> str:
    """Return ``tree`` encoded as PR #610 shipped it: a base64 of the uncompressed pickle."""
    return base64.b64encode(pickle.dumps(ast.fix_missing_locations(tree))).decode('ascii')


def _legacy_entry_size(entry: dict[str, Any], tree: ast.Module) -> int:
    return len(json.dumps({**entry, 'tree': _legacy_tree(tree)}))


def _legacy_import(legacy_tree: str, origin: str) -> None:
    """Import a module the way PR #610 children did: unpickle, compile and run the bare pickle."""
    code = compile(pickle.loads(base64.b64decode(legacy_tree)), origin, 'exec', dont_inherit=True)  # noqa: S301
    exec(code, {'__name__': 'fixture'})  # noqa: S102


def _loader_import(encoded_tree: str, origin: str) -> None:
    """Import a module through ``GremlinLoader.exec_module``, as a gremlin child does."""
    loader = GremlinLoader(encoded_tree, source='')
    module = ModuleType('fixture')
    module.__spec__ = importlib.machinery.ModuleSpec('fixture', loader, origin=origin)
    loader.exec_module(module)


def _import_time_ratio_to_legacy(encoded_tree: str, legacy_tree: str, origin: str) -> float:
    """Return the best loader import time over the best PR #610 import time, the two measured alternately.

    Both import the same module on the same machine, and the best of many alternating runs drops the runs that
    CPU contention slowed, so the ratio reflects the cost of the compressed format and not the load on the machine.
    """
    best_loader = best_legacy = float('inf')
    for _ in range(TIMING_REPEATS):
        started = time.perf_counter()
        _loader_import(encoded_tree, origin)
        best_loader = min(best_loader, time.perf_counter() - started)
        started = time.perf_counter()
        _legacy_import(legacy_tree, origin)
        best_legacy = min(best_legacy, time.perf_counter() - started)
    return best_loader / best_legacy


def _baseline() -> dict[str, dict[str, float]]:
    baseline: dict[str, dict[str, float]] = json.loads(BASELINE_FILE.read_text())
    return baseline


@pytest.mark.medium
class DescribeSourcesJsonPayload:
    @pytest.mark.parametrize('module_name', FIXTURE_MODULES)
    def it_ships_each_module_at_most_half_the_size_of_the_uncompressed_pickle_format(self, tmp_path, module_name):
        path, tree = _instrumented_tree(module_name)
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        assert len(json.dumps(entry)) * 2 <= _legacy_entry_size(entry, tree)

    @pytest.mark.parametrize('module_name', FIXTURE_MODULES)
    def it_does_not_grow_more_than_20_percent_over_the_baseline_size_ratio(self, tmp_path, module_name):
        path, tree = _instrumented_tree(module_name)
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        ratio = len(json.dumps(entry)) / _legacy_entry_size(entry, tree)
        assert ratio <= _baseline()[module_name]['size_ratio'] * ALLOWED_REGRESSION

    @pytest.mark.parametrize('module_name', FIXTURE_MODULES)
    def it_does_not_slow_decode_and_compile_more_than_20_percent_over_the_baseline_ratio(
        self, tmp_path, module_name, record_property
    ):
        path, tree = _instrumented_tree(module_name)
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        record_property('sources_json_bytes', len(json.dumps(entry)))
        ratio = _import_time_ratio_to_legacy(entry['tree'], _legacy_tree(_inject(tree)), path)
        record_property('decode_compile_ratio', ratio)
        assert ratio <= _baseline()[module_name]['decode_compile_ratio'] * ALLOWED_REGRESSION

    def it_records_the_per_module_numbers_in_a_junit_xml_report(self, tmp_path):
        report = tmp_path / 'report.xml'
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'pytest',
                f'{Path(__file__)}::DescribeSourcesJsonPayload',
                '-k',
                'does_not_slow_decode_and_compile',
                '-p',
                'no:cacheprovider',
                f'--junitxml={report}',
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout[-2000:]
        assert report.read_text().count('decode_compile_ratio') == len(FIXTURE_MODULES)

    def it_detects_a_loader_import_that_became_3x_slower(self, tmp_path, monkeypatch):
        path, tree = _instrumented_tree('textwrap')
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        original = GremlinLoader.exec_module

        def slowed(self, module):
            for _ in range(3):
                original(self, module)

        monkeypatch.setattr(GremlinLoader, 'exec_module', slowed)
        ratio = _import_time_ratio_to_legacy(entry['tree'], _legacy_tree(_inject(tree)), path)
        assert ratio > _baseline()['textwrap']['decode_compile_ratio'] * ALLOWED_REGRESSION

    @pytest.mark.parametrize('module_name', FIXTURE_MODULES)
    def it_imports_the_same_module_the_parent_instrumented(self, tmp_path, module_name):
        path, tree = _instrumented_tree(module_name)
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        expected: dict[str, Any] = {'__name__': 'fixture'}
        exec(compile(ast.fix_missing_locations(_inject(tree)), path, 'exec', dont_inherit=True), expected)  # noqa: S102
        loader = GremlinLoader(entry['tree'], source='')
        module = ModuleType('fixture')
        module.__spec__ = importlib.machinery.ModuleSpec('fixture', loader, origin=path)

        loader.exec_module(module)

        assert {name for name in vars(module) if not name.startswith('__')} == {
            name for name in expected if not name.startswith('__')
        }


def _inject(tree: ast.Module) -> ast.Module:
    return _inject_gremlin_active(tree)
