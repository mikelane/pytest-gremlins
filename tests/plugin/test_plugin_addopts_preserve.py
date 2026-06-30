"""Tests for preserving non-cov ``addopts`` in gremlins subprocess runs.

The coverage pre-scan and the mutant-execution runs both override pytest
``addopts`` so pytest-cov cannot hijack coverage collection (issue #113). The
override must strip *only* the cov-related flags — collection-affecting options
such as ``--import-mode=importlib`` have to survive into the subprocess, or
coverage-guided test selection silently disengages (issue #424).

See: https://github.com/mikelane/pytest-gremlins/issues/424
See: https://github.com/mikelane/pytest-gremlins/issues/113
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import pytest_gremlins.plugin as plugin_module
from pytest_gremlins.plugin import (
    _addopts_without_cov,
    _build_test_command,
    _get_session,
    _run_tests_with_coverage,
    pytest_configure,
)


@pytest.mark.small
class DescribeAddoptsWithoutCov:
    """Verify pytest-cov flags are stripped while other addopts are preserved."""

    def it_returns_empty_string_for_no_addopts(self) -> None:
        assert _addopts_without_cov([]) == ''

    def it_preserves_import_mode(self) -> None:
        assert _addopts_without_cov(['--import-mode=importlib']) == '--import-mode=importlib'

    def it_drops_inline_cov_and_keeps_the_rest(self) -> None:
        result = _addopts_without_cov(['--cov=mypkg', '--import-mode=importlib', '-ra'])
        assert result == '--import-mode=importlib -ra'

    def it_drops_inline_cov_report_without_orphaning(self) -> None:
        result = _addopts_without_cov(['--cov-report=term-missing', '--strict-markers'])
        assert result == '--strict-markers'

    def it_drops_space_separated_cov_report_value(self) -> None:
        """``--cov-report term`` drops both the flag and its value token."""
        result = _addopts_without_cov(['--cov-report', 'term', '--import-mode=importlib'])
        assert result == '--import-mode=importlib'

    def it_drops_bare_cov_followed_by_a_path_value(self) -> None:
        result = _addopts_without_cov(['--cov', 'src', '--strict-markers'])
        assert result == '--strict-markers'

    def it_drops_space_separated_cov_precision_value(self) -> None:
        """An unknown/value-taking cov option drops its space-separated value too."""
        result = _addopts_without_cov(['--cov-precision', '2', '--import-mode=importlib'])
        assert result == '--import-mode=importlib'

    def it_keeps_unrelated_options_sharing_the_cov_prefix(self) -> None:
        """``--covariance-threshold`` is not a pytest-cov option and is preserved."""
        result = _addopts_without_cov(['--covariance-threshold=0.9', '-q'])
        assert result == '--covariance-threshold=0.9 -q'

    def it_keeps_following_option_after_a_valueless_cov_flag(self) -> None:
        """A bare ``--cov`` immediately followed by an option has no value to drop."""
        result = _addopts_without_cov(['--cov', '--strict-markers'])
        assert result == '--strict-markers'

    def it_drops_cov_only_flags(self) -> None:
        result = _addopts_without_cov(['--cov-branch', '--cov-append', '--no-cov-on-fail', '-q'])
        assert result == '-q'

    def it_keeps_a_positional_after_a_valueless_cov_reset(self) -> None:
        """``--cov-reset`` takes no value, so a following positional must survive."""
        result = _addopts_without_cov(['--cov-reset', 'tests', '--import-mode=importlib'])
        assert result == 'tests --import-mode=importlib'

    def it_drops_no_cov(self) -> None:
        assert _addopts_without_cov(['--no-cov', '-q']) == '-q'

    def it_quotes_tokens_containing_spaces(self) -> None:
        result = _addopts_without_cov(['-k', 'foo or bar'])
        assert result == "-k 'foo or bar'"


@pytest.mark.medium
class DescribeCoverageSubprocessPreservesAddopts:
    """The coverage pre-scan threads preserved addopts into ``-o addopts=``."""

    def it_passes_preserved_addopts_into_the_command(self, tmp_path: Path) -> None:
        captured_cmd: list[list[str]] = []

        def fake_subprocess_run(cmd: list[str], **_kwargs: object) -> object:
            captured_cmd.append(cmd)

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=fake_subprocess_run):
            _run_tests_with_coverage(
                ['tests/test_example.py::test_one'],
                tmp_path,
                preserved_addopts='--import-mode=importlib',
            )

        cmd = captured_cmd[0]
        addopts_idx = cmd.index('-o')
        assert cmd[addopts_idx + 1] == 'addopts=--import-mode=importlib'

    def it_clears_addopts_by_default(self, tmp_path: Path) -> None:
        """With no preserved addopts the historical clear-all behavior is kept."""
        captured_cmd: list[list[str]] = []

        def fake_subprocess_run(cmd: list[str], **_kwargs: object) -> object:
            captured_cmd.append(cmd)

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=fake_subprocess_run):
            _run_tests_with_coverage(['tests/test_example.py::test_one'], tmp_path)

        cmd = captured_cmd[0]
        addopts_idx = cmd.index('-o')
        assert cmd[addopts_idx + 1] == 'addopts='


@pytest.mark.small
class DescribeBuildTestCommandPreservesAddopts:
    """The mutant-execution command threads preserved addopts into ``-o addopts=``."""

    def it_passes_preserved_addopts_when_running_pytest_directly(self) -> None:
        cmd = _build_test_command(None, '--import-mode=importlib')
        addopts_idx = cmd.index('-o')
        assert cmd[addopts_idx + 1] == 'addopts=--import-mode=importlib'

    def it_passes_preserved_addopts_with_an_instrumented_dir(self, tmp_path: Path) -> None:
        cmd = _build_test_command(tmp_path, '--import-mode=importlib')
        addopts_idx = cmd.index('-o')
        assert cmd[addopts_idx + 1] == 'addopts=--import-mode=importlib'

    def it_clears_addopts_by_default(self) -> None:
        cmd = _build_test_command(None)
        addopts_idx = cmd.index('-o')
        assert cmd[addopts_idx + 1] == 'addopts='


@pytest.mark.medium
class DescribePytestConfigureStoresPreservedAddopts:
    """``pytest_configure`` stores the cov-filtered addopts on the session."""

    def it_strips_cov_and_keeps_import_mode_on_the_session(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_pytest_config: object,
    ) -> None:
        monkeypatch.setattr(plugin_module, '_gremlin_session', None)
        config = make_pytest_config(  # type: ignore[operator]
            tmp_path,
            addopts=['--cov=mypkg', '--import-mode=importlib'],
        )

        pytest_configure(config)  # type: ignore[arg-type]

        assert _get_session().preserved_addopts == '--import-mode=importlib'
