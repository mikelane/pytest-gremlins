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
import subprocess
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

    def it_drops_a_bare_cov_that_is_the_final_token(self) -> None:
        """A value-taking cov option with nothing after it must not raise IndexError."""
        assert _addopts_without_cov(['--cov']) == ''

    def it_drops_a_value_taking_cov_option_that_is_the_final_token(self) -> None:
        """``--cov-report`` as the last token has no value to consume; must not raise IndexError."""
        result = _addopts_without_cov(['--strict-markers', '--cov-report'])
        assert result == '--strict-markers'

    def it_drops_a_negative_cov_fail_under_value(self) -> None:
        """``--cov-fail-under`` always requires a value, even one that looks like a flag."""
        result = _addopts_without_cov(['--cov-fail-under', '-1', '--import-mode=importlib'])
        assert result == '--import-mode=importlib'

    def it_drops_a_dash_prefixed_cov_report_value(self) -> None:
        """``--cov-report`` always requires a value; a dash-prefixed one must not leak."""
        result = _addopts_without_cov(['--cov-report', '-x', '--strict-markers'])
        assert result == '--strict-markers'

    def it_drops_values_for_consecutive_required_value_cov_options(self) -> None:
        """Two required-value cov options in sequence each drop only their own value,
        even when one of those values is dash-prefixed."""
        result = _addopts_without_cov(['--cov-report', 'term', '--cov-fail-under', '-1', '--import-mode=importlib'])
        assert result == '--import-mode=importlib'


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


@pytest.mark.medium
class DescribeReinjectedAddoptsHonoredByRealPytest:
    """Regression lock for #424: a real pytest subprocess honors ``-o addopts=<...>``.

    Every other test in this module stubs ``subprocess.run`` and asserts on the
    constructed command string, so none of them prove that pytest's own
    ``shlex.split`` of the injected ini value actually re-enables the option at
    runtime. This spawns a real subprocess against a throwaway project with
    duplicate test basenames across packages -- something the default (prepend)
    import mode cannot collect, and ``--import-mode=importlib`` can -- so the
    test result itself is proof the re-injected addopts took effect.
    """

    @staticmethod
    def _write_duplicate_basename_project(rootdir: Path) -> None:
        for package in ('package_a', 'package_b'):
            package_dir = rootdir / package
            package_dir.mkdir()
            (package_dir / 'test_shared_name.py').write_text('def test_it_passes():\n    assert True\n')

    def it_collects_duplicate_basenames_when_importlib_mode_is_preserved(self, tmp_path: Path) -> None:
        self._write_duplicate_basename_project(tmp_path)
        preserved_addopts = _addopts_without_cov(['--cov=mypkg', '--import-mode=importlib'])
        cmd = _build_test_command(None, preserved_addopts)

        result = subprocess.run(  # Intentional: exercises the real subprocess boundary
            cmd,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr

    def it_fails_the_same_collection_when_addopts_are_cleared(self, tmp_path: Path) -> None:
        """Negative control: without re-injection, pytest's default import mode cannot collect."""
        self._write_duplicate_basename_project(tmp_path)
        cmd = _build_test_command(None, '')

        result = subprocess.run(  # Intentional: exercises the real subprocess boundary
            cmd,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode != 0
        assert 'error during collection' in result.stdout
