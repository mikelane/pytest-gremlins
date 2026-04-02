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
import sqlite3
from types import SimpleNamespace
from unittest.mock import (
    MagicMock,
    patch,
)
import warnings

import coverage
import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _collect_coverage,
    _run_tests_with_coverage,
    pytest_configure,
    pytest_sessionfinish,
)


@pytest.mark.medium
class DescribeCoverageSubprocessClearsAddopts:
    """Verify the coverage subprocess includes -o addopts= to clear user config."""

    def it_includes_addopts_override_in_coverage_subprocess_command(self, tmp_path: Path) -> None:
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

    def it_places_addopts_override_before_test_node_ids(self, tmp_path: Path) -> None:
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
class DescribeEmptyCoverageWarning:
    """Verify a warning is emitted when coverage collection returns empty data."""

    def it_warns_when_coverage_data_is_empty(self, tmp_path: Path) -> None:
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

    def it_emits_no_warning_when_coverage_data_is_present(self, tmp_path: Path) -> None:
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
    mock_pluginmanager = MagicMock()  # PytestPluginManager: sets attrs dynamically; bare-mock: ok
    mock_pluginmanager.get_plugin.return_value = cov_plugin

    # spec=['rootdir', 'pluginmanager'] prevents workerinput from existing on the
    # mock, so _is_xdist_worker returns False (controller path, not worker path).
    mock_config = MagicMock(spec=['rootdir', 'pluginmanager'])
    mock_config.rootdir = tmp_path
    mock_config.pluginmanager = mock_pluginmanager

    mock_session = MagicMock(spec=pytest.Session)
    mock_session.config = mock_config

    # A minimal GremlinSession with one gremlin so pytest_sessionfinish
    # does not return early from the "no gremlins" guard.
    mock_gremlin = MagicMock()  # Gremlin is a frozen dataclass; spec= misses instance fields; bare-mock: ok
    mock_gremlin.file_path = str(tmp_path / 'src' / 'mod.py')

    gremlin_session = GremlinSession(
        enabled=True,
        gremlins=[mock_gremlin],
        test_node_ids={'tests/test_mod.py::test_foo': 'tests/test_mod.py::test_foo'},
    )

    return mock_session, gremlin_session


@pytest.mark.small
class DescribeCovReloadAfterPreScan:
    """Verify pytest-cov's coverage data is reloaded after the pre-scan completes."""

    def it_cov_load_called_when_cov_plugin_active(self, tmp_path: Path) -> None:
        """When _cov plugin is present with a cov attribute, cov.load() is called."""
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_cov_plugin = MagicMock()  # pytest-cov plugin: internal type, no public spec; bare-mock: ok
        mock_cov_plugin.cov = mock_cov

        mock_session, gremlin_session = _make_session_finish_mocks(tmp_path, cov_plugin=mock_cov_plugin)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=gremlin_session),
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]),
        ):
            pytest_sessionfinish(mock_session, exitstatus=0)

        mock_cov.load.assert_called_once()

    def it_cov_load_not_called_when_cov_plugin_absent(self, tmp_path: Path) -> None:
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

    def it_cov_load_not_called_when_cov_attribute_absent(self, tmp_path: Path) -> None:
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

    def it_cov_load_not_called_when_cov_attribute_is_none(self, tmp_path: Path) -> None:
        """When _cov plugin's cov attribute is None, no load is attempted."""
        mock_cov_plugin = MagicMock()  # pytest-cov plugin: internal type, no public spec; bare-mock: ok
        mock_cov_plugin.cov = None

        mock_session, gremlin_session = _make_session_finish_mocks(tmp_path, cov_plugin=mock_cov_plugin)

        with (
            patch('pytest_gremlins.plugin._get_session', return_value=gremlin_session),
            patch('pytest_gremlins.plugin._collect_coverage'),
            patch('pytest_gremlins.plugin._run_mutation_testing', return_value=[]),
        ):
            # If the `is not None` guard were removed, None.load() would raise AttributeError.
            pytest_sessionfinish(mock_session, exitstatus=0)  # no AttributeError = guard is active

    def it_cov_load_failure_propagates(self, tmp_path: Path) -> None:
        """When cov.load() raises, the exception propagates — a missing .coverage after pre-scan is a hard failure."""
        mock_cov = MagicMock(spec=coverage.Coverage)
        mock_cov.load.side_effect = Exception('coverage data missing')
        mock_cov_plugin = MagicMock()  # pytest-cov plugin: internal type, no public spec; bare-mock: ok
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
        gremlin_parallel=False,
        gremlin_workers=None,
        gremlin_batch=False,
        gremlin_batch_size=10,
        gremlin_max_pardons_pct=None,
        n=None,
        strict_pardons=False,
        gremlin_audit_pardons=False,
        gremlin_exclude=None,
    )
    config.pluginmanager = MagicMock()  # PytestPluginManager: sets attrs dynamically; bare-mock: ok
    config.pluginmanager.hasplugin.return_value = has_pytest_cov
    return config


@pytest.mark.medium
class DescribeOuterSessionCovNotSuppressed:
    """Verify --cov is NOT suppressed in the outer gremlins session.

    The correct behavior is to reload pytest-cov's data after the pre-scan,
    not to suppress --cov at configure time.
    """

    def it_preserves_cov_flag_when_gremlins_and_cov_both_active(self) -> None:
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

    def it_emits_no_suppression_warning_when_gremlins_and_cov_both_active(self) -> None:
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

    def it_preserves_cov_flag_when_gremlins_not_active(self) -> None:
        """When --gremlins is not active, --cov is untouched."""
        config = _make_configure_config(gremlins=False, has_pytest_cov=True, no_cov=False)

        with patch('pytest_gremlins.plugin._set_session'):
            pytest_configure(config)

        assert config.option.no_cov is False


def _write_coverage_sqlite(
    db_path: Path,
    contexts: list[tuple[int, str]],
    files: list[tuple[int, str]],
    line_bits: list[tuple[int, int, bytes]],
) -> None:
    """Write a minimal coverage.py SQLite .coverage file with the given data."""
    conn = sqlite3.connect(str(db_path))
    conn.execute('CREATE TABLE context (id INTEGER PRIMARY KEY, context TEXT)')
    conn.execute('CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)')
    conn.execute('CREATE TABLE line_bits (file_id INTEGER, context_id INTEGER, numbits BLOB)')
    conn.executemany('INSERT INTO context VALUES (?, ?)', contexts)
    conn.executemany('INSERT INTO file VALUES (?, ?)', files)
    conn.executemany('INSERT INTO line_bits VALUES (?, ?, ?)', line_bits)
    conn.commit()
    conn.close()


@pytest.mark.medium
class DescribeCoverageSQLiteReading:
    """Verify _run_tests_with_coverage reads per-test data from the .coverage SQLite DB."""

    def it_returns_coverage_data_indexed_by_test_name(self, tmp_path: Path) -> None:
        """When subprocess produces a .coverage file, its per-test data is returned."""
        # Bit 0 of byte 0 = line 0; bit 1 of byte 0 = line 1
        numbits = bytes([0x03])  # lines 0 and 1 covered

        def create_coverage_file(cmd: list[str], **_kwargs: object) -> object:  # noqa: ARG001
            _write_coverage_sqlite(
                tmp_path / '.coverage',
                contexts=[(1, 'tests/test_mod.py::test_foo|run')],
                files=[(1, 'src/module.py')],
                line_bits=[(1, 1, numbits)],
            )

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=create_coverage_file):
            result = _run_tests_with_coverage(['tests/test_mod.py::test_foo'], tmp_path)

        assert 'tests/test_mod.py::test_foo' in result
        assert 'src/module.py' in result['tests/test_mod.py::test_foo']
        assert 0 in result['tests/test_mod.py::test_foo']['src/module.py']
        assert 1 in result['tests/test_mod.py::test_foo']['src/module.py']

    def it_returns_empty_dict_when_coverage_file_absent(self, tmp_path: Path) -> None:
        """When subprocess runs but produces no .coverage file, an empty dict is returned."""

        def no_coverage_run(cmd: list[str], **_kwargs: object) -> object:  # noqa: ARG001
            class FakeResult:
                returncode = 1

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=no_coverage_run):
            result = _run_tests_with_coverage([], tmp_path)

        assert result == {}

    def it_accumulates_lines_across_multiple_rows_for_same_test_and_file(self, tmp_path: Path) -> None:
        """Multiple line_bits rows for the same test+file are accumulated (exercises already-seen branches)."""

        def create_multi_row_db(cmd: list[str], **_kwargs: object) -> object:  # noqa: ARG001
            # Two rows with the same context_id=1 and file_id=1 — second row hits the
            # 'test_name in result' and 'file_path in result[test_name]' branches.
            _write_coverage_sqlite(
                tmp_path / '.coverage',
                contexts=[(1, 'tests/test_mod.py::test_foo|run')],
                files=[(1, 'src/module.py')],
                line_bits=[
                    (1, 1, bytes([0x01])),  # line 0
                    (1, 1, bytes([0x02])),  # line 1 — same context/file, second pass
                ],
            )

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=create_multi_row_db):
            result = _run_tests_with_coverage([], tmp_path)

        assert 0 in result['tests/test_mod.py::test_foo']['src/module.py']
        assert 1 in result['tests/test_mod.py::test_foo']['src/module.py']

    def it_skips_line_bits_rows_with_orphaned_context_or_file_id(self, tmp_path: Path) -> None:
        """line_bits rows whose context_id or file_id are not in their tables are skipped (hits continue)."""

        def create_orphan_row_db(cmd: list[str], **_kwargs: object) -> object:  # noqa: ARG001
            _write_coverage_sqlite(
                tmp_path / '.coverage',
                contexts=[(1, 'tests/test_mod.py::test_bar|run')],
                files=[(1, 'src/module.py')],
                line_bits=[
                    (1, 1, bytes([0x01])),  # valid row
                    (1, 99, bytes([0x01])),  # context_id=99 not in contexts → hits continue
                    (99, 1, bytes([0x01])),  # file_id=99 not in files → hits continue
                ],
            )

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=create_orphan_row_db):
            result = _run_tests_with_coverage([], tmp_path)

        # Only the valid row contributes; orphaned rows are silently skipped
        assert 'tests/test_mod.py::test_bar' in result
        assert 0 in result['tests/test_mod.py::test_bar']['src/module.py']

    def it_expands_bare_function_names_to_full_node_ids(self, tmp_path: Path) -> None:
        """When coverage context uses old format (bare name), expand via reverse index."""
        numbits = bytes([0x03])  # lines 0 and 1

        def create_bare_name_db(cmd: list[str], **_kwargs: object) -> object:  # noqa: ARG001
            _write_coverage_sqlite(
                tmp_path / '.coverage',
                contexts=[(1, 'test_eq')],  # old format: bare function name
                files=[(1, 'src/module.py')],
                line_bits=[(1, 1, numbits)],
            )

            class FakeResult:
                returncode = 0

            return FakeResult()

        name_to_node_ids = {
            'test_eq': [
                'tests/test_attrs.py::test_eq',
                'tests/test_other.py::test_eq',
            ],
        }

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=create_bare_name_db):
            result = _run_tests_with_coverage([], tmp_path, name_to_node_ids=name_to_node_ids)

        # Bare name 'test_eq' should be expanded to both full node IDs
        assert 'test_eq' not in result
        assert 'tests/test_attrs.py::test_eq' in result
        assert 'tests/test_other.py::test_eq' in result
        assert 0 in result['tests/test_attrs.py::test_eq']['src/module.py']
        assert 0 in result['tests/test_other.py::test_eq']['src/module.py']

    def it_keeps_full_node_ids_unchanged_when_expanding(self, tmp_path: Path) -> None:
        """When coverage context already has full node IDs, they pass through unchanged."""
        numbits = bytes([0x01])

        def create_full_node_db(cmd: list[str], **_kwargs: object) -> object:  # noqa: ARG001
            _write_coverage_sqlite(
                tmp_path / '.coverage',
                contexts=[(1, 'tests/test_foo.py::test_bar|run')],
                files=[(1, 'src/module.py')],
                line_bits=[(1, 1, numbits)],
            )

            class FakeResult:
                returncode = 0

            return FakeResult()

        name_to_node_ids = {'test_bar': ['tests/test_foo.py::test_bar']}

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=create_full_node_db):
            result = _run_tests_with_coverage([], tmp_path, name_to_node_ids=name_to_node_ids)

        assert 'tests/test_foo.py::test_bar' in result
        assert 0 in result['tests/test_foo.py::test_bar']['src/module.py']

    def it_falls_back_to_bare_name_when_not_in_reverse_index(self, tmp_path: Path) -> None:
        """When a bare name has no reverse index entry, it is kept as-is."""
        numbits = bytes([0x01])

        def create_unknown_bare_db(cmd: list[str], **_kwargs: object) -> object:  # noqa: ARG001
            _write_coverage_sqlite(
                tmp_path / '.coverage',
                contexts=[(1, 'test_unknown')],  # bare name not in index
                files=[(1, 'src/module.py')],
                line_bits=[(1, 1, numbits)],
            )

            class FakeResult:
                returncode = 0

            return FakeResult()

        name_to_node_ids: dict[str, list[str]] = {}  # empty index

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=create_unknown_bare_db):
            result = _run_tests_with_coverage([], tmp_path, name_to_node_ids=name_to_node_ids)

        # Falls back to the bare name since reverse index has no entry
        assert 'test_unknown' in result
        assert 0 in result['test_unknown']['src/module.py']

    def it_does_not_expand_when_no_reverse_index_provided(self, tmp_path: Path) -> None:
        """When name_to_node_ids is None (default), bare names pass through unchanged."""
        numbits = bytes([0x01])

        def create_bare_no_index_db(cmd: list[str], **_kwargs: object) -> object:  # noqa: ARG001
            _write_coverage_sqlite(
                tmp_path / '.coverage',
                contexts=[(1, 'test_bare')],
                files=[(1, 'src/module.py')],
                line_bits=[(1, 1, numbits)],
            )

            class FakeResult:
                returncode = 0

            return FakeResult()

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=create_bare_no_index_db):
            result = _run_tests_with_coverage([], tmp_path)  # no name_to_node_ids

        assert 'test_bare' in result
        assert 0 in result['test_bare']['src/module.py']
