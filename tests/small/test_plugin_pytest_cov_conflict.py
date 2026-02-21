"""Tests for pytest-cov conflict prevention in coverage subprocess.

Verifies that pytest-gremlins clears user-configured addopts when running
the coverage subprocess, preventing pytest-cov from hijacking coverage
collection. Also verifies a warning is emitted when coverage returns
empty data. Also verifies that --cov is suppressed in the outer session
when --gremlins is active.

See: https://github.com/mikelane/pytest-gremlins/issues/113
See: https://github.com/mikelane/pytest-gremlins/issues/180
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import (
    MagicMock,
    patch,
)
import warnings

import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _collect_coverage,
    _run_tests_with_coverage,
    pytest_configure,
)


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.small
class TestCoverageSubprocessClearsAddopts:
    """Verify the coverage subprocess includes -o addopts= to clear user config."""

    def test_coverage_subprocess_command_includes_addopts_override(self, tmp_path: Path) -> None:
        """The subprocess command clears pytest addopts to prevent pytest-cov interference."""
        captured_cmd: list[list[str]] = []

        def fake_subprocess_run(cmd: list[str], **_kwargs: object) -> object:
            captured_cmd.append(cmd)

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=fake_subprocess_run):
            _run_tests_with_coverage(['tests/test_example.py::test_one'], tmp_path)

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        assert '-o' in cmd
        addopts_idx = cmd.index('-o')
        assert cmd[addopts_idx + 1] == 'addopts='

    def test_addopts_override_appears_before_test_node_ids(self, tmp_path: Path) -> None:
        """The -o addopts= flag appears before the test node IDs in the command."""
        captured_cmd: list[list[str]] = []

        def fake_subprocess_run(cmd: list[str], **_kwargs: object) -> object:
            captured_cmd.append(cmd)

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=fake_subprocess_run):
            _run_tests_with_coverage(
                ['tests/test_a.py::test_one', 'tests/test_b.py::test_two'],
                tmp_path,
            )

        cmd = captured_cmd[0]
        addopts_idx = cmd.index('-o')
        test_id_positions = [cmd.index(tid) for tid in ['tests/test_a.py::test_one', 'tests/test_b.py::test_two']]
        for pos in test_id_positions:
            assert addopts_idx < pos


@pytest.mark.small
class TestEmptyCoverageWarning:
    """Verify a warning is emitted when coverage collection returns empty data."""

    def test_warns_when_coverage_data_is_empty(self, tmp_path: Path) -> None:
        """A warning fires when _run_tests_with_coverage returns an empty dict."""
        session = GremlinSession(
            enabled=True,
            gremlins=[],
            test_node_ids={},
        )

        with (
            patch(
                'pytest_gremlins.plugin._run_tests_with_coverage',
                return_value={},
            ),
            pytest.warns(
                UserWarning,
                match='Coverage collection returned no data',
            ),
        ):
            _collect_coverage(session, tmp_path)

    def test_no_warning_when_coverage_data_is_present(self, tmp_path: Path) -> None:
        """No warning fires when coverage data contains entries."""
        session = GremlinSession(
            enabled=True,
            gremlins=[],
            test_node_ids={},
        )

        coverage_data = {
            'test_func': {
                'src/module.py': [1, 2, 3],
            },
        }

        with (
            patch(
                'pytest_gremlins.plugin._run_tests_with_coverage',
                return_value=coverage_data,
            ),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter('always')
            _collect_coverage(session, tmp_path)

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 0


def _make_config(*, gremlins: bool, has_pytest_cov: bool, no_cov: bool) -> MagicMock:
    """Build a mock pytest.Config for outer-session suppression tests."""
    config = MagicMock(spec=pytest.Config)
    config.option = SimpleNamespace(
        gremlins=gremlins,
        no_cov=no_cov,
        gremlin_operators=None,
        gremlin_targets=None,
        gremlin_cache=False,
        gremlin_clear_cache=False,
        gremlin_report='console',
        gremlin_batch=False,
        gremlin_batch_size=10,
        n=None,
    )
    config.pluginmanager = MagicMock()
    config.pluginmanager.hasplugin.return_value = has_pytest_cov
    return config


@pytest.mark.small
class TestOuterSessionCovSuppression:
    """Verify --cov is suppressed in the outer gremlins session."""

    def test_outer_session_cov_suppressed_when_gremlins_active(self) -> None:
        """When --gremlins and --cov are both active, --cov is suppressed with a warning."""
        config = _make_config(gremlins=True, has_pytest_cov=True, no_cov=False)

        with (
            patch('pytest_gremlins.plugin.load_config'),
            patch('pytest_gremlins.plugin.merge_configs') as mock_merge,
            patch('pytest_gremlins.plugin.get_default_registry'),
            patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            patch('pytest_gremlins.plugin._read_parallel_config', return_value=(False, None)),
            patch('pytest_gremlins.plugin._set_session'),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter('always')
            mock_merge.return_value = SimpleNamespace(operators=None, paths=None)
            config.rootdir = '.'
            pytest_configure(config)

        assert config.option.no_cov is True
        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 1
        assert 'pytest-gremlins suppressed --cov' in str(user_warnings[0].message)

    def test_outer_session_cov_not_suppressed_when_no_cov_already_set(self) -> None:
        """When --no-cov is already set, no additional warning is emitted."""
        config = _make_config(gremlins=True, has_pytest_cov=True, no_cov=True)

        with (
            patch('pytest_gremlins.plugin.load_config'),
            patch('pytest_gremlins.plugin.merge_configs') as mock_merge,
            patch('pytest_gremlins.plugin.get_default_registry'),
            patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            patch('pytest_gremlins.plugin._read_parallel_config', return_value=(False, None)),
            patch('pytest_gremlins.plugin._set_session'),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter('always')
            mock_merge.return_value = SimpleNamespace(operators=None, paths=None)
            config.rootdir = '.'
            pytest_configure(config)

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 0

    def test_outer_session_cov_not_suppressed_when_gremlins_not_active(self) -> None:
        """When --gremlins is not active, --cov suppression does not fire."""
        config = _make_config(gremlins=False, has_pytest_cov=True, no_cov=False)

        with (
            patch('pytest_gremlins.plugin._set_session'),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter('always')
            pytest_configure(config)

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 0
        assert config.option.no_cov is False

    def test_outer_session_cov_not_suppressed_when_pytest_cov_not_installed(self) -> None:
        """When pytest-cov is not installed, no suppression or warning fires."""
        config = _make_config(gremlins=True, has_pytest_cov=False, no_cov=False)

        with (
            patch('pytest_gremlins.plugin.load_config'),
            patch('pytest_gremlins.plugin.merge_configs') as mock_merge,
            patch('pytest_gremlins.plugin.get_default_registry'),
            patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            patch('pytest_gremlins.plugin._read_parallel_config', return_value=(False, None)),
            patch('pytest_gremlins.plugin._set_session'),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter('always')
            mock_merge.return_value = SimpleNamespace(operators=None, paths=None)
            config.rootdir = '.'
            pytest_configure(config)

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 0
        assert config.option.no_cov is False
