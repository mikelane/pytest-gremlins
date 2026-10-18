"""Drift check 1c: the default in each ``Default`` column of configuration.md equals the default in the code.

Format the docs must use in a ``Default`` cell:

* a single backticked literal, such as ``10``, ``false`` or ``"console"``, when the code has a concrete default;
* otherwise a plain phrase from ``UNSET_PHRASES`` (or the default the option's own help text states).

The code default comes from the parser (a non-``None`` argparse default), from a named constant or session field in
``plugin.py``, or, for options whose default is computed, from the ``(default: ...)`` in the option's help text.
"""

from __future__ import annotations

import pytest

from pytest_gremlins.config import CONFIG_KEYS
from pytest_gremlins.plugin import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_COVERAGE_TIMEOUT_SECONDS,
    DEFAULT_MUTANT_TIMEOUT_SECONDS,
    DEFAULT_REPORT_FORMATS,
)

from .docs_facts import (
    default_cells,
    registered_help_defaults,
    registered_options,
)

UNSET_PHRASES: frozenset[str] = frozenset({'none', 'all', 'auto-discovered', 'not set', 'no limit', 'disabled', '[]'})

CONFIG_KEY_TO_FLAG: dict[str, str] = {
    'operators': '--gremlin-operators',
    'paths': '--gremlin-targets',
    'exclude': '--gremlin-exclude',
    'workers': '--gremlin-workers',
    'cache': '--gremlin-cache',
    'report': '--gremlin-report',
    'batch_size': '--gremlin-batch-size',
    'max_pardons': '--max-pardons',
    'max-pardons-pct': '--gremlin-max-pardons-pct',
    'coverage_timeout': '--gremlin-coverage-timeout',
    'mutant_timeout': '--gremlin-mutant-timeout',
}


def _as_text(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list | tuple):
        return ','.join(value)
    return str(value)


def _normalize(cell: str) -> str:
    return cell.strip().strip('`').strip('"').lower()


CODE_DEFAULTS: dict[str, object] = {
    '--gremlin-batch-size': DEFAULT_BATCH_SIZE,
    '--gremlin-report': DEFAULT_REPORT_FORMATS,
    '--gremlin-coverage-timeout': DEFAULT_COVERAGE_TIMEOUT_SECONDS,
    '--gremlin-mutant-timeout': DEFAULT_MUTANT_TIMEOUT_SECONDS,
}


def _hard_code_defaults() -> dict[str, str]:
    """Return the concrete default of each option that has one, as text."""
    parser_defaults = {option.flag: option.default for option in registered_options() if option.default is not None}
    return {flag: _as_text(value) for flag, value in {**parser_defaults, **CODE_DEFAULTS}.items()}


def _default_mismatches(documented: dict[str, str], expected_by_name: dict[str, str | None]) -> list[str]:
    """Describe each name whose documented default is not its code default."""
    problems: list[str] = []
    for name, cell in documented.items():
        expected = expected_by_name.get(name)
        shown = _normalize(cell)
        if expected is not None and shown != expected.lower():
            problems.append(f'{name}: documented {shown!r}, code default {expected!r}')
        elif expected is None and shown not in UNSET_PHRASES:
            problems.append(
                f'{name}: documented {shown!r}, but the code has no default (use one of {sorted(UNSET_PHRASES)})'
            )
    return problems


def _flag_defaults_in_docs() -> dict[str, str]:
    return {name: cell for name, cell in default_cells().items() if name.startswith('--')}


def _key_defaults_in_docs() -> dict[str, str]:
    return {name: cell for name, cell in default_cells().items() if not name.startswith('--')}


def _expected_flag_defaults() -> dict[str, str | None]:
    hard = _hard_code_defaults()
    return {flag: hard.get(flag, registered_help_defaults().get(flag)) for flag in _flag_defaults_in_docs()}


def _expected_key_defaults() -> dict[str, str | None]:
    hard = _hard_code_defaults()
    return {key: hard.get(CONFIG_KEY_TO_FLAG.get(key, '')) for key in _key_defaults_in_docs()}


@pytest.mark.medium
class DescribeDocumentedDefaults:
    """Every default stated in configuration.md is the default the code applies."""

    def it_states_each_flags_code_default_in_the_options_tables(self):
        mismatches = _default_mismatches(_flag_defaults_in_docs(), _expected_flag_defaults())

        assert not mismatches, 'Flag defaults in configuration.md differ from the code:\n' + '\n'.join(mismatches)

    def it_states_each_keys_code_default_in_the_configuration_table(self):
        mismatches = _default_mismatches(_key_defaults_in_docs(), _expected_key_defaults())

        assert not mismatches, 'Key defaults in configuration.md differ from the code:\n' + '\n'.join(mismatches)

    def it_maps_every_config_key_to_the_flag_that_overrides_it(self):
        assert set(CONFIG_KEY_TO_FLAG) == CONFIG_KEYS
