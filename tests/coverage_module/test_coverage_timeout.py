"""Tests for the configurable coverage pre-scan timeout (issue #503, part A)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import (
    MagicMock,
    patch,
)

from _pytest.config.argparsing import (
    OptionGroup,
    Parser,
)
import pytest

from pytest_gremlins.config import (
    GremlinConfig,
    load_config,
    merge_configs,
)
from pytest_gremlins.plugin import (
    CoveragePrescanTimeoutError,
    GremlinSession,
    _collect_coverage,
    _run_tests_with_coverage,
    pytest_addoption,
)

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 120


@pytest.mark.small
class DescribeCoverageTimeoutConfig:
    """GremlinConfig and merge_configs carry coverage_timeout."""

    def it_defaults_to_none(self) -> None:
        assert GremlinConfig().coverage_timeout is None

    def it_prefers_the_cli_value_over_the_file_value(self) -> None:
        merged = merge_configs(GremlinConfig(coverage_timeout=30), cli_coverage_timeout=600)

        assert merged.coverage_timeout == 600

    def it_falls_back_to_the_file_value(self) -> None:
        merged = merge_configs(GremlinConfig(coverage_timeout=30))

        assert merged.coverage_timeout == 30

    def it_is_none_when_neither_source_sets_it(self) -> None:
        assert merge_configs(GremlinConfig()).coverage_timeout is None


@pytest.mark.medium
class DescribeCoverageTimeoutToml:
    """load_config reads and validates [tool.pytest-gremlins].coverage_timeout."""

    def it_reads_the_value(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').write_text('[tool.pytest-gremlins]\ncoverage_timeout = 300\n')

        assert load_config(tmp_path).coverage_timeout == 300

    def it_defaults_to_none_when_absent(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').write_text('[tool.pytest-gremlins]\n')

        assert load_config(tmp_path).coverage_timeout is None

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
        (tmp_path / 'pyproject.toml').write_text(f'[tool.pytest-gremlins]\ncoverage_timeout = {raw}\n')

        with pytest.raises(ValueError, match=rf'coverage_timeout.*positive integer.*{shown}'):
            load_config(tmp_path)


@pytest.mark.small
class DescribeCoverageTimeoutCliOption:
    """--gremlin-coverage-timeout is registered as an integer option."""

    def it_registers_the_option(self) -> None:
        group = MagicMock(spec=OptionGroup)
        parser = MagicMock(spec=Parser)
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        options = {c.args[0]: c.kwargs for c in group.addoption.call_args_list if c.args}
        assert options['--gremlin-coverage-timeout']['type'] is int
        assert options['--gremlin-coverage-timeout']['default'] is None
        assert options['--gremlin-coverage-timeout']['dest'] == 'gremlin_coverage_timeout'


@pytest.mark.small
class DescribeCoverageTimeoutSession:
    """GremlinSession defaults the pre-scan timeout to 120 seconds."""

    def it_defaults_to_120_seconds(self) -> None:
        assert GremlinSession().coverage_timeout == DEFAULT_TIMEOUT_SECONDS


@pytest.mark.medium
class DescribeRunTestsWithCoverageTimeout:
    """_run_tests_with_coverage honours the timeout and reports expiry distinctly."""

    def it_defaults_the_subprocess_timeout_to_120_seconds(self, tmp_path: Path) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True) as run:
            _run_tests_with_coverage([], tmp_path)

        assert run.call_args.kwargs['timeout'] == DEFAULT_TIMEOUT_SECONDS

    @pytest.mark.parametrize('seconds', [1, 45, 900])
    def it_passes_the_configured_timeout_to_the_subprocess(self, tmp_path: Path, seconds: int) -> None:
        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True) as run:
            _run_tests_with_coverage([], tmp_path, timeout=seconds)

        assert run.call_args.kwargs['timeout'] == seconds

    def it_raises_a_distinct_error_naming_the_timeout_on_expiry(self, tmp_path: Path) -> None:
        expired = subprocess.TimeoutExpired(cmd='pytest', timeout=7)

        with (
            patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=expired),
            pytest.raises(CoveragePrescanTimeoutError) as excinfo,
        ):
            _run_tests_with_coverage([], tmp_path, timeout=7)

        assert excinfo.value.seconds == 7

    def it_removes_the_temporary_coveragerc_on_expiry(self, tmp_path: Path) -> None:
        expired = subprocess.TimeoutExpired(cmd='pytest', timeout=7)

        with (
            patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=expired),
            pytest.raises(CoveragePrescanTimeoutError),
        ):
            _run_tests_with_coverage([], tmp_path, timeout=7)

        assert not (tmp_path / '.coveragerc.gremlins').exists()


@pytest.mark.medium
class DescribeCollectCoverageTimeoutWarning:
    """_collect_coverage warns specifically about a timeout, not about 'no data'."""

    def _collect_with_timeout(self, tmp_path: Path, seconds: int, capsys: pytest.CaptureFixture[str]) -> list[str]:
        session = GremlinSession(enabled=True, coverage_timeout=seconds)
        with patch(
            'pytest_gremlins.plugin._run_tests_with_coverage',
            autospec=True,
            side_effect=CoveragePrescanTimeoutError(seconds),
        ):
            _collect_coverage(session, tmp_path)
        return capsys.readouterr().err.splitlines()

    def it_emits_the_timeout_warning_with_the_limit_and_the_remedy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        messages = self._collect_with_timeout(tmp_path, 45, capsys)

        assert messages == [
            'pytest-gremlins: coverage pre-scan exceeded 45s; coverage-guided test selection disabled '
            '(set coverage_timeout / --gremlin-coverage-timeout to raise it)'
        ]

    def it_names_the_per_attempt_and_the_rerun_scaled_limit(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        session = GremlinSession(enabled=True, coverage_timeout=400, coverage_attempt_timeout=120)
        with patch(
            'pytest_gremlins.plugin._run_tests_with_coverage',
            autospec=True,
            side_effect=CoveragePrescanTimeoutError(400),
        ):
            _collect_coverage(session, tmp_path)

        assert capsys.readouterr().err.splitlines() == [
            'pytest-gremlins: coverage pre-scan exceeded 400s (120s per attempt, scaled for the pytest-rerunfailures '
            'budget); coverage-guided test selection disabled '
            '(set coverage_timeout / --gremlin-coverage-timeout to raise the per-attempt limit)'
        ]

    def it_does_not_also_emit_the_no_data_warning(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        messages = self._collect_with_timeout(tmp_path, 45, capsys)

        all_text = ' '.join(messages)
        assert 'returned no data' not in all_text

    @staticmethod
    def _prescan_timeout_for(tmp_path: Path, flaky_test_count: int, *, reruns: int = 1) -> int:
        session = GremlinSession(
            enabled=True,
            coverage_timeout=19,
            coverage_attempt_timeout=6,
            rerun_budget=(reruns, 7.0),
            baseline_rerun_test_ids={f't.py::test_{n}' for n in range(flaky_test_count)},
        )
        with patch('pytest_gremlins.plugin._run_tests_with_coverage', autospec=True, return_value={'t': {}}) as run:
            _collect_coverage(session, tmp_path)
        timeout: int = run.call_args.kwargs['timeout']
        return timeout

    @pytest.mark.parametrize(('flaky_test_count', 'expected'), [(0, 19), (1, 19), (3, 33)])
    def it_pays_the_rerun_delay_for_each_test_the_baseline_reran(
        self, tmp_path: Path, flaky_test_count: int, expected: int
    ) -> None:
        assert self._prescan_timeout_for(tmp_path, flaky_test_count) == expected

    def it_leaves_the_pre_scan_timeout_alone_when_no_reruns_are_configured(self, tmp_path: Path) -> None:
        assert self._prescan_timeout_for(tmp_path, 3, reruns=0) == 6

    def it_does_not_advise_raising_the_limit_when_it_is_already_at_the_cap(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        session = GremlinSession(enabled=True, coverage_timeout=86400, coverage_attempt_timeout=30000)
        with patch(
            'pytest_gremlins.plugin._run_tests_with_coverage',
            autospec=True,
            side_effect=CoveragePrescanTimeoutError(86400),
        ):
            _collect_coverage(session, tmp_path)

        assert capsys.readouterr().err.splitlines() == [
            'pytest-gremlins: coverage pre-scan exceeded 86400s (30000s per attempt, scaled for the '
            'pytest-rerunfailures budget); coverage-guided test selection disabled '
            '(the limit is capped at 86400s; lower --reruns or --reruns-delay)'
        ]

    def it_forwards_the_session_timeout_to_the_pre_scan(self, tmp_path: Path) -> None:
        session = GremlinSession(enabled=True, coverage_timeout=45)

        with patch('pytest_gremlins.plugin._run_tests_with_coverage', autospec=True, return_value={'t': {}}) as run:
            _collect_coverage(session, tmp_path)

        assert run.call_args.kwargs['timeout'] == 45


_TARGET = 'def add(a, b):\n    return a + b\n'
_TEST = 'from target import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'


@pytest.mark.medium
class DescribeCoverageTimeoutEndToEnd:
    """The CLI flag and TOML key reach the pre-scan through the real pytest_configure."""

    @staticmethod
    def _prescan_timeout(pytester: pytest.Pytester, *args: str) -> int:
        pytester.makepyfile(target=_TARGET, test_target=_TEST)
        with patch('pytest_gremlins.plugin._run_tests_with_coverage', autospec=True, return_value={}) as run:
            pytester.runpytest('--gremlins', '--gremlin-targets=target.py', *args)
        return int(run.call_args.kwargs['timeout'])

    def it_uses_120_seconds_when_unconfigured(self, pytester_with_markers: pytest.Pytester) -> None:
        assert self._prescan_timeout(pytester_with_markers) == DEFAULT_TIMEOUT_SECONDS

    def it_reads_the_toml_key(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\ncoverage_timeout = 7\n')

        assert self._prescan_timeout(pytester_with_markers) == 7

    def it_reads_the_cli_flag(self, pytester_with_markers: pytest.Pytester) -> None:
        assert self._prescan_timeout(pytester_with_markers, '--gremlin-coverage-timeout=9') == 9

    def it_lets_the_cli_flag_win_over_the_toml_key(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\ncoverage_timeout = 7\n')

        assert self._prescan_timeout(pytester_with_markers, '--gremlin-coverage-timeout=9') == 9

    @pytest.mark.parametrize('value', ['0', '-3', '86401', '99999999999'])
    def it_rejects_an_out_of_range_cli_value_naming_the_flag_and_value(
        self, pytester_with_markers: pytest.Pytester, value: str
    ) -> None:
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest('--gremlins', f'--gremlin-coverage-timeout={value}')

        result.stderr.fnmatch_lines([f'*--gremlin-coverage-timeout must be a positive integer*{value}*'])
