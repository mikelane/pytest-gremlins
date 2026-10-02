"""Tests for the configurable per-mutant test timeout."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
import pytest

from pytest_gremlins.cache.incremental import IncrementalCache
from pytest_gremlins.config import (
    GremlinConfig,
    load_config,
    merge_configs,
)
from pytest_gremlins.plugin import (
    GremlinSession,
    pytest_addoption,
)

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 30


@pytest.fixture(autouse=True)
def _utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every pytest child these tests spawn write its output as UTF-8."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


@pytest.mark.small
class DescribeMutantTimeoutConfig:
    """GremlinConfig and merge_configs carry mutant_timeout."""

    def it_defaults_to_none(self) -> None:
        assert GremlinConfig().mutant_timeout is None

    def it_prefers_the_cli_value_over_the_file_value(self) -> None:
        merged = merge_configs(GremlinConfig(mutant_timeout=5), cli_mutant_timeout=600)

        assert merged.mutant_timeout == 600

    def it_falls_back_to_the_file_value(self) -> None:
        merged = merge_configs(GremlinConfig(mutant_timeout=5))

        assert merged.mutant_timeout == 5

    def it_is_none_when_neither_source_sets_it(self) -> None:
        assert merge_configs(GremlinConfig()).mutant_timeout is None


@pytest.mark.medium
class DescribeMutantTimeoutToml:
    """load_config reads and validates [tool.pytest-gremlins].mutant_timeout."""

    def it_reads_the_value(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').write_text('[tool.pytest-gremlins]\nmutant_timeout = 300\n')

        assert load_config(tmp_path).mutant_timeout == 300

    def it_defaults_to_none_when_absent(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').write_text('[tool.pytest-gremlins]\n')

        assert load_config(tmp_path).mutant_timeout is None

    @pytest.mark.parametrize(
        ('raw', 'shown'),
        [
            ('0', '0'),
            ('-5', '-5'),
            ('"soon"', 'soon'),
            ('1.5', '1.5'),
            ('true', 'True'),
            ('86401', '86401'),
            ('99999999999', '99999999999'),
        ],
    )
    def it_rejects_non_positive_non_integer_and_oversized_values(self, tmp_path: Path, raw: str, shown: str) -> None:
        (tmp_path / 'pyproject.toml').write_text(f'[tool.pytest-gremlins]\nmutant_timeout = {raw}\n')

        with pytest.raises(ValueError, match=rf'mutant_timeout.*positive integer.*{shown}'):
            load_config(tmp_path)


@pytest.mark.small
class DescribeMutantTimeoutCliOption:
    """--gremlin-mutant-timeout is registered as an integer option."""

    def it_registers_the_option(self) -> None:
        group = MagicMock(spec=OptionGroup)
        parser = MagicMock(spec=Parser)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        options = {c.args[0]: c.kwargs for c in group.addoption.call_args_list if c.args}
        assert options['--gremlin-mutant-timeout']['type'] is int
        assert options['--gremlin-mutant-timeout']['default'] is None
        assert options['--gremlin-mutant-timeout']['dest'] == 'gremlin_mutant_timeout'


@pytest.mark.small
class DescribeMutantTimeoutSession:
    """GremlinSession defaults the per-mutant timeout to 30 seconds."""

    def it_defaults_to_30_seconds(self) -> None:
        assert GremlinSession().mutant_timeout == DEFAULT_TIMEOUT_SECONDS


@pytest.mark.medium
class DescribeMutantTimeoutCacheKey:
    """A verdict cached under one per-mutant timeout is not reused under another."""

    def it_misses_when_the_timeout_differs(self, tmp_path: Path) -> None:
        cache = IncrementalCache(tmp_path / 'cache')
        cache.cache_result('g001', 'src', {'test_a': 'h'}, {'status': 'timeout'}, mutant_timeout=1)

        try:
            assert cache.get_cached_result('g001', 'src', {'test_a': 'h'}, mutant_timeout=60) is None
        finally:
            cache.close()

    def it_hits_when_the_timeout_matches(self, tmp_path: Path) -> None:
        cache = IncrementalCache(tmp_path / 'cache')
        cache.cache_result('g001', 'src', {'test_a': 'h'}, {'status': 'timeout'}, mutant_timeout=1)

        try:
            assert cache.get_cached_result('g001', 'src', {'test_a': 'h'}, mutant_timeout=1) == {'status': 'timeout'}
        finally:
            cache.close()


_TARGET = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

_SLOW_UNDER_A_MUTANT = """
import os
import time

import pytest
from sample import classify


@pytest.mark.medium
def test_classify():
    if os.environ.get('ACTIVE_GREMLIN'):
        time.sleep(3)
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

_COMMON_ARGS = ('--gremlins', '--gremlin-targets=sample.py', '--gremlin-operators=comparison', '-p', 'no:cacheprovider')

_EXECUTION_MODES = {
    'default': (),
    'parallel': ('--gremlin-parallel', '--gremlin-workers=2'),
    'batch': ('--gremlin-batch',),
}


def _verdicts(output: str) -> dict[str, int]:
    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Timeout', 'Error')}


def _run(pytester: pytest.Pytester, *args: str) -> pytest.RunResult:
    pytester.makepyfile(sample=_TARGET, test_sample=_SLOW_UNDER_A_MUTANT)
    return pytester.runpytest_subprocess(*_COMMON_ARGS, *args)


@pytest.mark.medium
class DescribeMutantTimeoutEndToEnd:
    """The TOML key and CLI flag bound each mutant's test run through the real entry point."""

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_times_out_a_mutant_run_longer_than_the_toml_value(
        self, pytester_with_markers: pytest.Pytester, mode: str
    ) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\nmutant_timeout = 1\n')

        verdicts = _verdicts(_run(pytester_with_markers, *_EXECUTION_MODES[mode]).stdout.str())

        assert verdicts['Timeout'] > 0
        assert verdicts['Zapped'] == 0

    @pytest.mark.parametrize('mode', list(_EXECUTION_MODES))
    def it_lets_the_cli_flag_win_over_the_toml_key(self, pytester_with_markers: pytest.Pytester, mode: str) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\nmutant_timeout = 1\n')

        verdicts = _verdicts(
            _run(pytester_with_markers, '--gremlin-mutant-timeout=20', *_EXECUTION_MODES[mode]).stdout.str()
        )

        assert verdicts['Timeout'] == 0
        assert verdicts['Zapped'] > 0

    def it_times_out_a_mutant_run_longer_than_the_cli_value(self, pytester_with_markers: pytest.Pytester) -> None:
        verdicts = _verdicts(_run(pytester_with_markers, '--gremlin-mutant-timeout=1').stdout.str())

        assert verdicts['Timeout'] > 0

    def it_judges_a_cached_verdict_again_under_a_different_timeout(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        first = _run(pytester_with_markers, '--gremlin-cache', '--gremlin-mutant-timeout=1')
        second = _run(pytester_with_markers, '--gremlin-cache', '--gremlin-mutant-timeout=20')
        third = _run(pytester_with_markers, '--gremlin-cache', '--gremlin-mutant-timeout=20')

        assert _verdicts(first.stdout.str())['Timeout'] > 0
        assert _verdicts(second.stdout.str())['Zapped'] > 0
        assert 'cache hit' not in second.stdout.str()
        assert third.stdout.str().count('cache hit (skipping)') == 2

    @pytest.mark.parametrize('value', ['0', '-3', '86401', '99999999999'])
    def it_rejects_an_out_of_range_cli_value_naming_the_flag_and_value(
        self, pytester_with_markers: pytest.Pytester, value: str
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET, test_sample=_SLOW_UNDER_A_MUTANT)

        result = pytester_with_markers.runpytest('--gremlins', f'--gremlin-mutant-timeout={value}')

        result.stderr.fnmatch_lines([f'*--gremlin-mutant-timeout must be a positive integer*{value}*'])

    def it_rejects_a_non_integer_cli_value_naming_the_flag_and_value(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(sample=_TARGET, test_sample=_SLOW_UNDER_A_MUTANT)

        result = pytester_with_markers.runpytest('--gremlins', '--gremlin-mutant-timeout=soon')

        result.stderr.fnmatch_lines(["*--gremlin-mutant-timeout*invalid int value: 'soon'*"])
