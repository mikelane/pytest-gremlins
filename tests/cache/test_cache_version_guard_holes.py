"""Code that has decided cached verdicts before must stay under the cache-version guard (#875).

Every symbol below lives in ``plugin.py``. Each one was edited by a past PR that had to raise
``RUNNER_FIDELITY_VERSION`` because the edit changed verdicts read from the cache, so an edit to any of them
must still change the guarded digests. These tests fail if ``plugin.py`` is added to ``EXCLUDED_FROM_GUARD``
while that code still lives there.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from .test_cache_version_guard import (
    PACKAGE_ROOT,
    _copy_package,
    _guarded_digests,
    guarded_sources,
)

if TYPE_CHECKING:
    from pathlib import Path

# Symbol -> the RUNNER_FIDELITY_VERSION bump an edit to it required on main.
VERDICT_AFFECTING_SYMBOLS = {
    '_get_bootstrap_script': 'rf5 (#552), rf11 (#616), rf14 (#663): in-subprocess exit-code-to-verdict mapping',
    '_hash_test_file_with_conftests': 'rf19 (#758): conftest.py folded into the cache key',
    '_selection_has_unhashed_test_file': 'rf19 (#758): unmatched tests kept out of the cache',
    '_build_test_hashes_for_gremlin': 'test-file part of the cache key built for every lookup and write',
    '_verify_suite_loads_unmutated': 'writes UNATTRIBUTABLE_MARKER and clears load_failures_attributable',
}
BOOTSTRAP_COLLECTION_KILL_MAPPING = '        exit_code = __COLLECTION_FAILED_EXIT_CODE__\n'


def _modules_defining(symbol: str) -> set[str]:
    trees = {
        source.relative_to(PACKAGE_ROOT).as_posix(): ast.parse(source.read_text(encoding='utf-8'))
        for source in PACKAGE_ROOT.rglob('*.py')
    }
    return {
        module
        for module, tree in trees.items()
        if any(isinstance(node, ast.FunctionDef) and node.name == symbol for node in tree.body)
    }


@pytest.mark.medium
class DescribeVerdictAffectingCodeStaysGuarded:
    """An edit to code that decided cached verdicts before changes the guarded digests."""

    @pytest.mark.parametrize('symbol', sorted(VERDICT_AFFECTING_SYMBOLS))
    def it_keeps_each_verdict_affecting_symbol_in_a_guarded_file(self, symbol: str) -> None:
        guarded = {source.relative_to(PACKAGE_ROOT).as_posix() for source in guarded_sources()}

        assert _modules_defining(symbol) <= guarded, (
            f'{symbol} is defined in an unguarded file; {VERDICT_AFFECTING_SYMBOLS[symbol]}'
        )

    @pytest.mark.parametrize('symbol', sorted(VERDICT_AFFECTING_SYMBOLS))
    def it_defines_each_verdict_affecting_symbol_somewhere(self, symbol: str) -> None:
        assert _modules_defining(symbol), f'{symbol} is not defined in any package module; update this list.'

    def it_changes_the_digest_when_the_bootstrap_collection_kill_mapping_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        package_copy = _copy_package(tmp_path, monkeypatch)
        before = _guarded_digests()

        plugin_source = package_copy / 'plugin.py'
        original = plugin_source.read_text(encoding='utf-8')
        assert BOOTSTRAP_COLLECTION_KILL_MAPPING in original
        plugin_source.write_text(
            original.replace(BOOTSTRAP_COLLECTION_KILL_MAPPING, '        exit_code = 1\n'), encoding='utf-8'
        )

        assert _guarded_digests() != before
