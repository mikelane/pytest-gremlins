"""Benchmark of the ``sources.json`` payload the parent ships to every gremlin child (#612).

The payload carries each instrumented module as a pickled AST (``tree``) plus unparsed ``source``. Sizes are
compared with the format of PR #610 (an uncompressed pickle) measured in the same run, so the numbers do not
depend on the machine or on the Python version. ``sources_json_baseline.json`` records the accepted ratios; a
metric that grows more than 20% above its baseline fails.
"""

import ast
import base64
import importlib
import inspect
import json
from pathlib import Path
import pickle
import time
from types import SimpleNamespace

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
TIMING_REPEATS = 5


def _instrumented_tree(module_name: str) -> tuple[str, ast.Module]:
    path = inspect.getsourcefile(importlib.import_module(module_name))
    assert path is not None
    _, tree = transform_source(Path(path).read_text(encoding='utf-8'), path)
    return path, tree


def _written_entries(tmp_path: Path) -> dict[str, dict[str, object]]:
    trees = dict(_instrumented_tree(name) for name in FIXTURE_MODULES)
    temp_dir = _write_instrumented_sources(trees, tmp_path)
    entries: dict[str, dict[str, object]] = json.loads((temp_dir / 'sources.json').read_text())
    return {entry['origin']: entry for entry in entries.values()}  # type: ignore[misc]


def _legacy_entry_size(entry: dict[str, object], tree: ast.Module) -> int:
    legacy_tree = base64.b64encode(pickle.dumps(ast.fix_missing_locations(tree))).decode('ascii')
    return len(json.dumps({**entry, 'tree': legacy_tree}))


def _best_decode_compile_seconds(encoded_tree: str, origin: str) -> float:
    module = SimpleNamespace(__spec__=SimpleNamespace(origin=origin), __name__='fixture')
    best = float('inf')
    for _ in range(TIMING_REPEATS):
        loader = GremlinLoader(encoded_tree, source='')
        started = time.perf_counter()
        assert loader._compile_tree(module) is not None  # type: ignore[arg-type]
        best = min(best, time.perf_counter() - started)
    return best


def _baseline() -> dict[str, dict[str, float]]:
    return json.loads(BASELINE_FILE.read_text())  # type: ignore[no-any-return]


@pytest.mark.medium
class DescribeSourcesJsonPayload:
    @pytest.mark.parametrize('module_name', FIXTURE_MODULES)
    def it_ships_each_module_at_most_half_the_size_of_the_uncompressed_pickle_format(self, tmp_path, module_name):
        path, _tree = _instrumented_tree(module_name)
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        assert len(json.dumps(entry)) * 2 <= _legacy_entry_size(entry, _instrumented_tree(module_name)[1])

    @pytest.mark.parametrize('module_name', FIXTURE_MODULES)
    def it_does_not_grow_more_than_20_percent_over_the_baseline_size_ratio(self, tmp_path, module_name):
        path, _ = _instrumented_tree(module_name)
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        ratio = len(json.dumps(entry)) / _legacy_entry_size(entry, _instrumented_tree(module_name)[1])
        assert ratio <= _baseline()[module_name]['size_ratio'] * ALLOWED_REGRESSION

    @pytest.mark.parametrize('module_name', FIXTURE_MODULES)
    def it_does_not_slow_decode_and_compile_more_than_20_percent_over_the_baseline_ratio(self, tmp_path, module_name):
        path, _ = _instrumented_tree(module_name)
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        legacy_tree = base64.b64encode(
            pickle.dumps(ast.fix_missing_locations(_instrumented_tree(module_name)[1]))
        ).decode('ascii')
        current = _best_decode_compile_seconds(entry['tree'], path)  # type: ignore[arg-type]
        legacy = _best_decode_compile_seconds(legacy_tree, path)
        assert current / legacy <= _baseline()[module_name]['decode_compile_ratio'] * ALLOWED_REGRESSION

    @pytest.mark.parametrize('module_name', FIXTURE_MODULES)
    def it_rebuilds_the_same_tree_the_parent_instrumented(self, tmp_path, module_name):
        path, tree = _instrumented_tree(module_name)
        entry = _written_entries(tmp_path)[str(Path(path).absolute())]
        rebuilt = GremlinLoader._unpickle_tree(entry['tree'])  # type: ignore[arg-type]
        assert rebuilt is not None
        assert ast.dump(rebuilt, include_attributes=True) == ast.dump(
            ast.fix_missing_locations(_inject(tree)), include_attributes=True
        )


def _inject(tree: ast.Module) -> ast.Module:
    return _inject_gremlin_active(tree)
