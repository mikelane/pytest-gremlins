"""Tests for pytest-cov conflict prevention in coverage subprocess.

Verifies that pytest-gremlins clears user-configured addopts when running
the coverage subprocess, preventing pytest-cov from hijacking coverage
collection. Also verifies a warning is emitted when coverage returns
empty data. Also verifies that after the pre-scan completes, pytest-cov's
in-memory coverage data is reloaded from the updated .coverage file.

See: https://github.com/mikelane/pytest-gremlins/issues/113
See: https://github.com/mikelane/pytest-gremlins/issues/180
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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
    pytest_sessionfinish,
)


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


def _make_session_finish_mocks(
    tmp_path: Path,
    *,
    cov_plugin: object = None,
) -> tuple[MagicMock, GremlinSession]:
    """Build mock session and GremlinSession for pytest_sessionfinish tests.

    Args:
        tmp_path: Temporary directory used as rootdir.
        cov_plugin: The object returned by pluginmanager.get_plugin('_cov').
            None means --cov is not active.

    Returns:
        A tuple of (mock_session, gremlin_session).
    """
    mock_pluginmanager = MagicMock()
    mock_pluginmanager.get_plugin.return_value = cov_plugin

    mock_config = MagicMock()
    mock_config.rootdir = tmp_path
    mock_config.pluginmanager = mock_pluginmanager

    mock_session = MagicMock()
    mock_session.config = mock_config

    # A minimal GremlinSession with one gremlin so pytest_sessionfinish
    # does not return early from the "no gremlins" guard.
    mock_gremlin = MagicMock()
    mock_gremlin.file_path = str(tmp_path / 'src' / 'mod.py')

    gremlin_session = GremlinSession(
        enabled=True,
        gremlins=[mock_gremlin],
        test_node_ids={'test_foo': 'tests/test_mod.py::test_foo'},
    )

    return mock_session, gremlin_session


@pytest.mark.small
class TestCovReloadAfterPreScan:
    """Verify pytest-cov's coverage data is reloaded after the pre-scan completes."""

    def test_cov_load_called_when_cov_plugin_active(self, tmp_path: Path) -> None:
        """When _cov plugin is present with a cov attribute, cov.load() is called."""
        mock_cov = MagicMock()
        mock_cov_plugin = MagicMock()
        mock_cov_plugin.cov = mock_cov

        mock_session, gremlin_session = _make_session_finish_mocks(tmp_path, cov_plugin=mock_cov_plugin)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=gremlin_session),
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]),
        ):
            pytest_sessionfinish(mock_session, exitstatus=0)

        mock_cov.load.assert_called_once()

    def test_cov_load_not_called_when_cov_plugin_absent(self, tmp_path: Path) -> None:
        """When _cov plugin is absent (--cov not passed), no load is attempted."""
        mock_session, gremlin_session = _make_session_finish_mocks(tmp_path, cov_plugin=None)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=gremlin_session),
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]),
        ):
            # Should complete without raising AttributeError or TypeError
            pytest_sessionfinish(mock_session, exitstatus=0)

        # Verify get_plugin was called with the correct key
        mock_session.config.pluginmanager.get_plugin.assert_called_once_with('_cov')

    def test_cov_load_not_called_when_cov_attribute_absent(self, tmp_path: Path) -> None:
        """When _cov plugin has no cov attribute, no load is attempted."""
        # spec=[] means any attribute access raises AttributeError. If the hasattr guard
        # were removed, accessing .cov on this mock would raise — failing this test.
        mock_cov_plugin = MagicMock(spec=[])

        mock_session, gremlin_session = _make_session_finish_mocks(tmp_path, cov_plugin=mock_cov_plugin)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=gremlin_session),
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]),
        ):
            pytest_sessionfinish(mock_session, exitstatus=0)  # no AttributeError = guard is active

    def test_cov_load_not_called_when_cov_attribute_is_none(self, tmp_path: Path) -> None:
        """When _cov plugin's cov attribute is None, no load is attempted."""
        mock_cov_plugin = MagicMock()
        mock_cov_plugin.cov = None

        mock_session, gremlin_session = _make_session_finish_mocks(tmp_path, cov_plugin=mock_cov_plugin)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=gremlin_session),
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]),
        ):
            # If the `is not None` guard were removed, None.load() would raise AttributeError.
            pytest_sessionfinish(mock_session, exitstatus=0)  # no AttributeError = guard is active

    def test_cov_load_failure_propagates(self, tmp_path: Path) -> None:
        """When cov.load() raises, the exception propagates — a missing .coverage after pre-scan is a hard failure."""
        mock_cov = MagicMock()
        mock_cov.load.side_effect = Exception('coverage data missing')
        mock_cov_plugin = MagicMock()
        mock_cov_plugin.cov = mock_cov

        mock_session, gremlin_session = _make_session_finish_mocks(tmp_path, cov_plugin=mock_cov_plugin)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=gremlin_session),
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]),
            pytest.raises(Exception, match='coverage data missing'),
        ):
            pytest_sessionfinish(mock_session, exitstatus=0)


def _make_configure_config(*, gremlins: bool, has_pytest_cov: bool, no_cov: bool) -> MagicMock:
    """Build a mock pytest.Config for outer-session configure tests."""
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
class TestOuterSessionCovNotSuppressed:
    """Verify --cov is NOT suppressed in the outer gremlins session.

    The correct behavior is to reload pytest-cov's data after the pre-scan,
    not to suppress --cov at configure time.
    """

    def test_no_cov_flag_not_set_when_gremlins_and_cov_both_active(self) -> None:
        """When --gremlins and --cov are both active, --cov is NOT suppressed."""
        config = _make_configure_config(gremlins=True, has_pytest_cov=True, no_cov=False)

        with (
            patch('pytest_gremlins.plugin.load_config'),
            patch('pytest_gremlins.plugin.merge_configs') as mock_merge,
            patch('pytest_gremlins.plugin.get_default_registry'),
            patch('pytest_gremlins.plugin.discover_source_paths', return_value=[]),
            patch('pytest_gremlins.plugin._read_parallel_config', return_value=(False, None)),
            patch('pytest_gremlins.plugin._set_session'),
        ):
            mock_merge.return_value = SimpleNamespace(operators=None, paths=None)
            config.rootdir = '.'
            pytest_configure(config)

        # no_cov must remain False — gremlins must not suppress cov at configure time
        assert config.option.no_cov is False

    def test_no_suppression_warning_emitted_when_gremlins_and_cov_both_active(self) -> None:
        """No suppression UserWarning is emitted when --gremlins and --cov are active."""
        config = _make_configure_config(gremlins=True, has_pytest_cov=True, no_cov=False)

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

        suppression_warnings = [w for w in caught if 'suppressed --cov' in str(w.message)]
        assert len(suppression_warnings) == 0

    def test_no_cov_flag_not_set_when_gremlins_not_active(self) -> None:
        """When --gremlins is not active, --cov is untouched."""
        config = _make_configure_config(gremlins=False, has_pytest_cov=True, no_cov=False)

        with patch('pytest_gremlins.plugin._set_session'):
            pytest_configure(config)

        assert config.option.no_cov is False
