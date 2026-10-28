"""Type and shape validation of every ``[tool.pytest-gremlins]`` key (issue #566)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pytest_gremlins.config import load_config
from pytest_gremlins.instrumentation.transformer import get_default_registry
from pytest_gremlins.operators.comparison import ComparisonOperator

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, toml_line: str) -> None:
    (tmp_path / 'pyproject.toml').write_text(f'[tool.pytest-gremlins]\n{toml_line}\n', encoding='utf-8')


@pytest.mark.medium
class DescribeListKeyValidation:
    """``operators``, ``paths`` and ``exclude`` are lists of strings; anything else is a ValueError."""

    @pytest.mark.parametrize(
        ('toml_line', 'message'),
        [
            ('exclude = 5', r'\[tool\.pytest-gremlins\]\.exclude must be a list of strings.*got 5'),
            ('exclude = [5]', r'\[tool\.pytest-gremlins\]\.exclude must be a list of strings.*got \[5\]'),
            ('operators = 5', r'\[tool\.pytest-gremlins\]\.operators must be a list of strings.*got 5'),
            ('paths = 5', r'\[tool\.pytest-gremlins\]\.paths must be a list of strings.*got 5'),
            ('paths = [true]', r'\[tool\.pytest-gremlins\]\.paths must be a list of strings.*got \[True\]'),
            ('operators = [""]', r'\[tool\.pytest-gremlins\]\.operators must be a list of strings.*got \[\'\'\]'),
        ],
    )
    def it_rejects_a_wrong_typed_value_naming_the_key_and_value(self, tmp_path: Path, toml_line: str, message: str):
        _write(tmp_path, toml_line)

        with pytest.raises(ValueError, match=message):
            load_config(tmp_path)

    @pytest.mark.parametrize('key', ['operators', 'paths', 'exclude'])
    def it_rejects_a_bare_string_with_a_use_a_list_hint(self, tmp_path: Path, key: str):
        _write(tmp_path, f'{key} = "tests/*"')

        with pytest.raises(ValueError, match=rf'{key} must be a list of strings.*use a list.*got \'tests/\*\''):
            load_config(tmp_path)

    def it_rejects_a_bogus_operator_listing_the_valid_names(self, tmp_path: Path):
        _write(tmp_path, 'operators = ["comparison", "bogus"]')

        with pytest.raises(ValueError, match=r"unknown operator 'bogus'.*arithmetic.*boundary.*comparison") as caught:
            load_config(tmp_path)

        assert '[tool.pytest-gremlins].operators' in str(caught.value)

    def it_accepts_a_registered_operator_that_is_not_built_in(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setitem(get_default_registry()._operators, 'third-party', ComparisonOperator)
        _write(tmp_path, 'operators = ["third-party"]')

        assert load_config(tmp_path).operators == ['third-party']

    def it_loads_valid_lists(self, tmp_path: Path):
        _write(tmp_path, 'operators = ["comparison", "boundary"]\npaths = ["src"]\nexclude = ["tests/*"]')

        config = load_config(tmp_path)

        assert (config.operators, config.paths, config.exclude) == (['comparison', 'boundary'], ['src'], ['tests/*'])


@pytest.mark.medium
class DescribeKeySpelling:
    """Every hyphenated key also accepts its underscore spelling and vice versa."""

    @pytest.mark.parametrize(
        ('toml_line', 'field', 'expected'),
        [
            ('max_pardons_pct = 5.0', 'max_pardons_pct', 5.0),
            ('max-pardons-pct = 5.0', 'max_pardons_pct', 5.0),
            ('max-pardons = 3', 'max_pardons', 3),
            ('max_pardons = 3', 'max_pardons', 3),
            ('batch-size = 7', 'batch_size', 7),
            ('batch_size = 7', 'batch_size', 7),
            ('coverage-timeout = 9', 'coverage_timeout', 9),
            ('mutant-timeout = 11', 'mutant_timeout', 11),
        ],
    )
    def it_reads_either_spelling(self, tmp_path: Path, toml_line: str, field: str, expected: object):
        _write(tmp_path, toml_line)

        assert getattr(load_config(tmp_path), field) == expected

    def it_rejects_both_spellings_of_one_key(self, tmp_path: Path):
        _write(tmp_path, 'max-pardons-pct = 5.0\nmax_pardons_pct = 6.0')

        with pytest.raises(ValueError, match=r"sets both 'max-pardons-pct' and 'max_pardons_pct'.*only one"):
            load_config(tmp_path)

    def it_names_the_hyphen_spelling_in_the_error_for_a_bad_max_pardons_pct(self, tmp_path: Path):
        _write(tmp_path, 'max_pardons_pct = 500')

        with pytest.raises(ValueError, match=r'max-pardons-pct must be between 0 and 100'):
            load_config(tmp_path)


@pytest.mark.medium
class DescribeUnknownKeys:
    """An unknown key warns, naming the closest valid key, and does not stop the load."""

    @pytest.mark.parametrize(
        ('toml_line', 'unknown', 'closest'),
        [
            ('exlcude = ["x"]', 'exlcude', 'exclude'),
            ('max_pardon_pct = 5', 'max_pardon_pct', 'max-pardons-pct'),
            ('operater = ["comparison"]', 'operater', 'operators'),
        ],
    )
    def it_warns_naming_the_key_and_the_closest_valid_key(
        self, tmp_path: Path, toml_line: str, unknown: str, closest: str
    ):
        _write(tmp_path, toml_line)
        warned: list[str] = []

        load_config(tmp_path, on_warning=warned.append)

        assert len(warned) == 1
        assert f"unknown key '{unknown}'" in warned[0]
        assert f"did you mean '{closest}'?" in warned[0]

    def it_lists_the_valid_keys_when_nothing_is_close(self, tmp_path: Path):
        _write(tmp_path, 'zzzzzzzz = 1')
        warned: list[str] = []

        load_config(tmp_path, on_warning=warned.append)

        assert "unknown key 'zzzzzzzz'" in warned[0]
        assert 'valid keys:' in warned[0]
        assert 'batch_size' in warned[0]

    def it_keeps_loading_the_valid_keys(self, tmp_path: Path):
        _write(tmp_path, 'bogus = 1\nbatch_size = 7')

        assert load_config(tmp_path, on_warning=lambda _message: None).batch_size == 7

    def it_warns_rather_than_rejects_an_unknown_key_given_in_both_spellings(self, tmp_path: Path):
        _write(tmp_path, 'future-key = 1\nfuture_key = 2')
        warned: list[str] = []

        load_config(tmp_path, on_warning=warned.append)

        assert len(warned) == 2
        assert "unknown key 'future-key'" in warned[0]
        assert "unknown key 'future_key'" in warned[1]

    def it_escapes_control_characters_in_an_unknown_key_name(self, tmp_path: Path):
        (tmp_path / 'pyproject.toml').write_text('[tool.pytest-gremlins]\n"x\\npytest-gremlins: forged" = 1\n')
        warned: list[str] = []

        load_config(tmp_path, on_warning=warned.append)

        assert len(warned) == 1
        assert '\n' not in warned[0]
        assert 'x\\npytest-gremlins: forged' in warned[0]

    def it_escapes_control_characters_in_an_unknown_operator_name(self, tmp_path: Path):
        (tmp_path / 'pyproject.toml').write_text('[tool.pytest-gremlins]\noperators = ["x\\nforged"]\n')

        with pytest.raises(ValueError, match='unknown operator') as raised:
            load_config(tmp_path)

        assert '\n' not in str(raised.value).split('Valid operators')[0]

    def it_does_not_warn_for_a_valid_config(self, tmp_path: Path):
        _write(tmp_path, 'batch-size = 7\nmax_pardons_pct = 1.0')
        warned: list[str] = []

        load_config(tmp_path, on_warning=warned.append)

        assert warned == []


@pytest.mark.medium
class DescribeNonTableSection:
    """A ``pytest-gremlins`` entry that is not a table is a ValueError, not an AttributeError."""

    def it_rejects_a_scalar_section(self, tmp_path: Path):
        (tmp_path / 'pyproject.toml').write_text('[tool]\npytest-gremlins = 5\n', encoding='utf-8')

        with pytest.raises(ValueError, match=r'\[tool\.pytest-gremlins\] must be a table'):
            load_config(tmp_path)
