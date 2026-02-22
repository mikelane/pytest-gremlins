"""Tests for plugin helper functions.

These tests cover the utility functions in plugin.py that can be tested in isolation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from pytest_gremlins.plugin import (
    GREMLIN_SOURCES_ENV_VAR,
    GremlinSession,
    _add_source_file,
    _build_filtered_test_command,
    _build_test_command,
    _build_test_hashes_for_gremlin,
    _cache_gremlin_result,
    _check_cache_for_gremlin,
    _cleanup_instrumented_dir,
    _decode_numbits,
    _is_xdist_worker,
    _make_node_ids_relative,
    _path_to_module_name,
    _read_parallel_config,
    _resolve_parallel_from_xdist,
    _select_tests_for_gremlin_prioritized,
    _should_include_file,
    _test_gremlin,
)
from pytest_gremlins.reporting.results import (
    GremlinResult,
    GremlinResultStatus,
)


@pytest.mark.small
class TestShouldIncludeFile:
    """Tests for _should_include_file function."""

    def test_excludes_test_files_with_test_prefix(self, tmp_path: Path) -> None:
        """Files starting with test_ are excluded."""
        test_file = tmp_path / 'test_something.py'
        test_file.touch()
        assert _should_include_file(test_file) is False

    def test_excludes_test_files_with_test_suffix(self, tmp_path: Path) -> None:
        """Files ending with _test.py are excluded."""
        test_file = tmp_path / 'something_test.py'
        test_file.touch()
        assert _should_include_file(test_file) is False

    def test_excludes_conftest(self, tmp_path: Path) -> None:
        """conftest.py files are excluded."""
        conftest = tmp_path / 'conftest.py'
        conftest.touch()
        assert _should_include_file(conftest) is False

    def test_excludes_pycache_files(self, tmp_path: Path) -> None:
        """Files in __pycache__ are excluded."""
        pycache = tmp_path / '__pycache__'
        pycache.mkdir()
        cached_file = pycache / 'module.cpython-311.pyc'
        cached_file.touch()
        # The path contains __pycache__
        assert _should_include_file(cached_file) is False

    def test_includes_regular_source_files(self, tmp_path: Path) -> None:
        """Regular source files are included."""
        source_file = tmp_path / 'module.py'
        source_file.touch()
        assert _should_include_file(source_file) is True


@pytest.mark.small
class TestAddSourceFile:
    """Tests for _add_source_file function."""

    def test_adds_valid_python_file(self, tmp_path: Path) -> None:
        """Valid Python file is added to the collection."""
        source_file = tmp_path / 'module.py'
        source_file.write_text('x = 1\n')
        source_files: dict[str, str] = {}

        _add_source_file(source_file, source_files)

        assert str(source_file) in source_files
        assert source_files[str(source_file)] == 'x = 1\n'

    def test_skips_file_with_syntax_error(self, tmp_path: Path) -> None:
        """File with syntax error is silently skipped."""
        bad_file = tmp_path / 'bad.py'
        bad_file.write_text('def broken(\n')  # Syntax error
        source_files: dict[str, str] = {}

        _add_source_file(bad_file, source_files)

        assert str(bad_file) not in source_files

    def test_skips_nonexistent_file(self, tmp_path: Path) -> None:
        """Nonexistent file is silently skipped."""
        missing_file = tmp_path / 'missing.py'
        source_files: dict[str, str] = {}

        _add_source_file(missing_file, source_files)

        assert str(missing_file) not in source_files


@pytest.mark.small
class TestMakeNodeIdsRelative:
    """Tests for _make_node_ids_relative function."""

    def test_makes_absolute_paths_relative(self, tmp_path: Path) -> None:
        """Absolute paths in node IDs are made relative to rootdir."""
        rootdir = tmp_path
        node_ids = [f'{tmp_path}/tests/test_module.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def test_keeps_relative_paths_unchanged(self, tmp_path: Path) -> None:
        """Relative paths in node IDs are unchanged."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def test_strips_test_category_suffix(self, tmp_path: Path) -> None:
        """Plugin-added suffixes like [SMALL] are stripped."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py::test_func [SMALL]']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def test_handles_node_id_without_double_colon(self, tmp_path: Path) -> None:
        """Handles node IDs that are just file paths (no ::)."""
        rootdir = tmp_path
        abs_path = tmp_path / 'tests' / 'test_module.py'
        node_ids = [str(abs_path)]

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py']

    def test_handles_relative_path_without_double_colon(self, tmp_path: Path) -> None:
        """Handles relative paths without ::."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py']

    def test_handles_non_relative_absolute_path(self, tmp_path: Path) -> None:
        """Handles absolute paths that are not under rootdir."""
        rootdir = tmp_path
        node_ids = ['/some/other/path/test.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['/some/other/path/test.py::test_func']


@pytest.mark.small
class TestPathToModuleName:
    """Tests for _path_to_module_name function."""

    def test_converts_relative_path_to_module(self, tmp_path: Path) -> None:
        """Converts relative path to module name."""
        file_path = tmp_path / 'package' / 'module.py'
        result = _path_to_module_name(file_path, tmp_path)
        assert result == 'package.module'

    def test_strips_src_prefix(self, tmp_path: Path) -> None:
        """Strips src/ prefix from path since it's a layout convention."""
        file_path = tmp_path / 'src' / 'mypackage' / 'module.py'
        result = _path_to_module_name(file_path, tmp_path)
        assert result == 'mypackage.module'

    def test_file_not_relative_to_rootdir(self, tmp_path: Path) -> None:
        """When file is not under rootdir, uses just the filename.

        Covers lines 426-427: ValueError catch for relative_to.
        """
        rootdir = tmp_path / 'project'
        rootdir.mkdir()
        file_path = Path('/some/other/path/module.py')

        result = _path_to_module_name(file_path, rootdir)

        # Just returns the filename without .py extension
        assert result == 'module'


@pytest.mark.small
class TestBuildTestCommand:
    """Tests for _build_test_command function."""

    def test_with_instrumented_dir(self, tmp_path: Path) -> None:
        """When instrumented_dir provided, uses bootstrap script."""
        instrumented_dir = tmp_path / 'instrumented'
        instrumented_dir.mkdir()

        result = _build_test_command(instrumented_dir)

        assert 'gremlin_bootstrap.py' in result[1]
        assert '-x' in result
        assert '--tb=no' in result

    def test_without_instrumented_dir(self) -> None:
        """When instrumented_dir is None, runs pytest directly.

        Covers line 1321: return branch when instrumented_dir is None.
        """
        result = _build_test_command(None)

        assert '-m' in result
        assert 'pytest' in result
        assert '-x' in result
        assert '--tb=no' in result

    def test_with_instrumented_dir_suppresses_addopts(self, tmp_path: Path) -> None:
        """When instrumented_dir provided, resets addopts to prevent inherited flags."""
        instrumented_dir = tmp_path / 'instrumented'
        instrumented_dir.mkdir()

        result = _build_test_command(instrumented_dir)

        assert '-o' in result
        assert 'addopts=' in result

    def test_without_instrumented_dir_suppresses_addopts(self) -> None:
        """When instrumented_dir is None, resets addopts to prevent inherited flags."""
        result = _build_test_command(None)

        assert '-o' in result
        assert 'addopts=' in result

    def test_with_instrumented_dir_disables_coverage(self, tmp_path: Path) -> None:
        """When instrumented_dir provided, disables coverage to avoid exit code 2."""
        instrumented_dir = tmp_path / 'instrumented'
        instrumented_dir.mkdir()

        result = _build_test_command(instrumented_dir)

        assert '--no-cov' in result

    def test_without_instrumented_dir_disables_coverage(self) -> None:
        """When instrumented_dir is None, disables coverage to avoid exit code 2."""
        result = _build_test_command(None)

        assert '--no-cov' in result


@pytest.mark.small
class TestIsXdistWorker:
    """Tests for _is_xdist_worker function.

    Both True and False branches are tested so a hardcoded return value fails.
    """

    def test_returns_true_when_workerinput_present(self) -> None:
        """Config with workerinput attribute is an xdist worker."""
        config = MagicMock(spec=['workerinput'])
        config.workerinput = {'slaveid': 'gw0'}

        assert _is_xdist_worker(config) is True

    def test_returns_false_when_workerinput_absent(self) -> None:
        """Config without workerinput attribute is not an xdist worker."""
        config = MagicMock(spec=[])

        assert _is_xdist_worker(config) is False


@pytest.mark.small
class TestResolveParallelFromXdist:
    """Tests for _resolve_parallel_from_xdist function.

    All four branches tested so no single return value can pass all cases.
    """

    def test_none_returns_disabled(self) -> None:
        """None numprocesses means parallel is not enabled."""
        assert _resolve_parallel_from_xdist(None) == (False, None)

    def test_auto_returns_enabled_with_no_worker_count(self) -> None:
        """'auto' enables parallel with worker count deferred to xdist."""
        assert _resolve_parallel_from_xdist('auto') == (True, None)

    def test_positive_int_returns_enabled_with_worker_count(self) -> None:
        """Positive int enables parallel and sets explicit worker count."""
        assert _resolve_parallel_from_xdist(4) == (True, 4)

    def test_zero_returns_disabled(self) -> None:
        """Zero numprocesses disables parallel (non-positive int guard)."""
        assert _resolve_parallel_from_xdist(0) == (False, None)

    def test_negative_int_returns_disabled(self) -> None:
        """Negative numprocesses disables parallel."""
        assert _resolve_parallel_from_xdist(-1) == (False, None)


@pytest.mark.small
class TestReadParallelConfig:
    """Tests for _read_parallel_config function."""

    def test_returns_gremlin_parallel_flags_when_xdist_absent(self) -> None:
        """When xdist is not installed, gremlin_parallel flags are used as-is."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = True
        config.option.gremlin_workers = 2

        parallel_enabled, parallel_workers = _read_parallel_config(config)

        assert parallel_enabled is True
        assert parallel_workers == 2

    def test_xdist_numprocesses_overrides_gremlin_flags(self) -> None:
        """When xdist is available with numprocesses, it takes precedence."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers', 'numprocesses'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = None
        config.option.numprocesses = 'auto'

        parallel_enabled, parallel_workers = _read_parallel_config(config)

        assert parallel_enabled is True
        assert parallel_workers is None

    def test_emits_deprecation_warning_when_gremlin_flags_used_with_xdist(self) -> None:
        """Using --gremlin-parallel when xdist is available emits a deprecation warning."""
        config = MagicMock(spec=['option', 'issue_config_time_warning'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers', 'numprocesses'])
        config.option.gremlin_parallel = True
        config.option.gremlin_workers = None
        config.option.numprocesses = 'auto'

        _read_parallel_config(config)

        config.issue_config_time_warning.assert_called_once()

    def test_no_deprecation_warning_when_only_xdist_used(self) -> None:
        """No warning when only xdist -n is used (no --gremlin-parallel)."""
        config = MagicMock(spec=['option', 'issue_config_time_warning'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers', 'numprocesses'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = None
        config.option.numprocesses = 4

        _read_parallel_config(config)

        config.issue_config_time_warning.assert_not_called()

    def test_workers_alone_implies_parallel_enabled(self) -> None:
        """Passing --gremlin-workers=N without --gremlin-parallel still enables parallel mode."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = 4

        parallel_enabled, parallel_workers = _read_parallel_config(config)

        assert parallel_enabled is True
        assert parallel_workers == 4

    def test_workers_none_without_parallel_flag_stays_disabled(self) -> None:
        """When neither --gremlin-workers nor --gremlin-parallel is set, parallel stays disabled."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = None

        parallel_enabled, parallel_workers = _read_parallel_config(config)

        assert parallel_enabled is False
        assert parallel_workers is None

    def test_workers_implies_parallel_with_explicit_count(self) -> None:
        """--gremlin-workers=2 implies parallel with worker count preserved."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = 2

        parallel_enabled, parallel_workers = _read_parallel_config(config)

        assert parallel_enabled is True
        assert parallel_workers == 2


@pytest.mark.small
class TestSelectTestsForGremlinPrioritized:
    """Tests for _select_tests_for_gremlin_prioritized function."""

    def test_returns_all_tests_when_no_prioritized_selector(self) -> None:
        """Falls back to all test_node_ids keys when prioritized_selector is None."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        gremlin = MagicMock()

        result = _select_tests_for_gremlin_prioritized(gremlin, gs)

        assert set(result) == {'test_a', 'test_b'}

    def test_returns_all_tests_when_selector_returns_empty(self) -> None:
        """Falls back to all test_node_ids keys when selector finds no covering tests."""
        mock_selector = MagicMock()
        mock_selector.select_tests_prioritized.return_value = []
        gs = GremlinSession(
            enabled=True,
            prioritized_selector=mock_selector,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        gremlin = MagicMock()

        result = _select_tests_for_gremlin_prioritized(gremlin, gs)

        assert set(result) == {'test_a', 'test_b'}

    def test_returns_selector_result_when_covering_tests_found(self) -> None:
        """Returns prioritized list when selector finds covering tests."""
        mock_selector = MagicMock()
        mock_selector.select_tests_prioritized.return_value = ['test_a']
        gs = GremlinSession(
            enabled=True,
            prioritized_selector=mock_selector,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        gremlin = MagicMock()

        result = _select_tests_for_gremlin_prioritized(gremlin, gs)

        assert result == ['test_a']


@pytest.mark.small
class TestBuildFilteredTestCommand:
    """Tests for _build_filtered_test_command function."""

    def test_appends_node_ids_from_selected_tests(self) -> None:
        """Node IDs for selected tests are appended to the base command."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        base = ['python', '-m', 'pytest']

        result = _build_filtered_test_command(base, ['test_a', 'test_b'], gs)

        assert 'tests/test_m.py::test_a' in result
        assert 'tests/test_m.py::test_b' in result

    def test_preserves_order_of_selected_tests(self) -> None:
        """Order of node IDs in the command matches the selected_tests order."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        base = ['python', '-m', 'pytest']

        result = _build_filtered_test_command(base, ['test_b', 'test_a'], gs)

        test_a_pos = result.index('tests/test_m.py::test_a')
        test_b_pos = result.index('tests/test_m.py::test_b')
        assert test_b_pos < test_a_pos

    def test_skips_tests_not_in_node_ids(self) -> None:
        """Tests not present in test_node_ids are silently skipped."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={'test_a': 'tests/test_m.py::test_a'},
        )
        base = ['python', '-m', 'pytest']

        result = _build_filtered_test_command(base, ['test_a', 'test_missing'], gs)

        assert 'tests/test_m.py::test_a' in result
        assert 'test_missing' not in result

    def test_returns_base_command_unchanged_when_no_matching_tests(self) -> None:
        """When no selected tests exist in node_ids, base command is returned as-is."""
        gs = GremlinSession(enabled=True, test_node_ids={})
        base = ['python', '-m', 'pytest']

        result = _build_filtered_test_command(base, ['test_gone'], gs)

        assert result == base


@pytest.mark.small
class TestDecodeNumbits:
    """Tests for _decode_numbits — coverage.py bit-compressed line number decoder.

    Both directions (set bit → line present, clear bit → line absent) are tested
    so a hardcoded empty-list or all-lines return cannot pass all cases.
    """

    def test_single_line_one(self) -> None:
        """Byte 0x01 encodes line 0 (bit 0 of byte 0)."""
        assert _decode_numbits(bytes([0x01])) == [0]

    def test_single_line_two(self) -> None:
        """Byte 0x02 encodes line 1 (bit 1 of byte 0)."""
        assert _decode_numbits(bytes([0x02])) == [1]

    def test_multiple_lines_in_one_byte(self) -> None:
        """0x03 (bits 0 and 1 set) encodes lines 0 and 1."""
        assert _decode_numbits(bytes([0x03])) == [0, 1]

    def test_line_in_second_byte(self) -> None:
        """Bit 0 of byte 1 encodes line 8."""
        assert _decode_numbits(bytes([0x00, 0x01])) == [8]

    def test_empty_bytes_returns_no_lines(self) -> None:
        """Empty bytes produce an empty list."""
        assert _decode_numbits(b'') == []


@pytest.mark.small
class TestCleanupInstrumentedDir:
    """Tests for _cleanup_instrumented_dir.

    Both branches (None and existing path) tested so a hardcoded no-op fails.
    """

    def test_removes_existing_directory(self, tmp_path: Path) -> None:
        """When the directory exists, shutil.rmtree removes it."""
        instrumented = tmp_path / 'instrumented'
        instrumented.mkdir()
        (instrumented / 'file.py').write_text('x = 1\n')

        _cleanup_instrumented_dir(instrumented)

        assert not instrumented.exists()

    def test_does_nothing_when_path_is_none(self) -> None:
        """None path causes the function to return without error."""
        _cleanup_instrumented_dir(None)  # must not raise

    def test_does_nothing_when_directory_does_not_exist(self, tmp_path: Path) -> None:
        """Non-existent path causes the function to return without error."""
        missing = tmp_path / 'not_here'
        _cleanup_instrumented_dir(missing)  # must not raise
        assert not missing.exists()


@pytest.mark.small
class TestBuildTestHashesForGremlin:
    """Tests for _build_test_hashes_for_gremlin function.

    Tests the dotted-name fallback path (lines 1467-1468) where a test name
    like 'SomeClass.test_method' is resolved to 'test_method' to find its node ID.
    """

    def test_resolves_dotted_name_via_simple_name_fallback(self) -> None:
        """'Module.test_method' falls back to 'test_method' when the full name is not in test_node_ids."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={'test_method': 'tests/test_m.py::test_method'},
            test_hashes={'tests/test_m.py': 'abc123'},
        )

        result = _build_test_hashes_for_gremlin(['Module.test_method'], gs)

        assert 'Module.test_method' in result
        assert result['Module.test_method'] == 'abc123'

    def test_returns_empty_when_node_id_not_found_even_after_fallback(self) -> None:
        """Test names with no matching node ID (even via simple name) produce no entry."""
        gs = GremlinSession(enabled=True, test_node_ids={}, test_hashes={})

        result = _build_test_hashes_for_gremlin(['unknown.test_func'], gs)

        assert result == {}


@pytest.mark.small
class TestCheckCacheForGremlin:
    """Tests for _check_cache_for_gremlin function (lines 1498-1519).

    Both the None-return paths and the hit path are tested so no single
    hardcoded return value satisfies all cases.
    """

    def test_returns_none_when_cache_disabled(self) -> None:
        """Returns None immediately when cache_enabled is False."""
        gs = GremlinSession(enabled=True, cache_enabled=False)
        gremlin = MagicMock()

        result = _check_cache_for_gremlin(gremlin, [], gs)

        assert result is None

    def test_returns_none_when_source_hash_missing(self) -> None:
        """Returns None when gremlin's file_path has no entry in source_hashes."""
        mock_cache = MagicMock()
        gs = GremlinSession(enabled=True, cache_enabled=True, cache=mock_cache, source_hashes={})
        gremlin = MagicMock()
        gremlin.file_path = 'src/module.py'

        result = _check_cache_for_gremlin(gremlin, [], gs)

        assert result is None
        mock_cache.get_cached_result.assert_not_called()

    def test_returns_gremlin_result_on_cache_hit(self) -> None:
        """Returns a GremlinResult constructed from cached data when cache has a hit."""
        mock_cache = MagicMock()
        mock_cache.get_cached_result.return_value = {'status': 'zapped', 'killing_test': 'test_foo'}
        gs = GremlinSession(
            enabled=True,
            cache_enabled=True,
            cache=mock_cache,
            source_hashes={'src/module.py': 'hash123'},
        )
        gremlin = MagicMock()
        gremlin.file_path = 'src/module.py'

        result = _check_cache_for_gremlin(gremlin, [], gs)

        assert result is not None
        assert result.status == GremlinResultStatus.ZAPPED


@pytest.mark.small
class TestCacheGremlinResult:
    """Tests for _cache_gremlin_result function (lines 1536-1555).

    Verifies that cache.cache_result_deferred is called when a source hash exists,
    and skipped when it does not.
    """

    def test_calls_cache_deferred_when_source_hash_exists(self) -> None:
        """cache_result_deferred is called when gremlin's file has a source hash."""
        mock_cache = MagicMock()
        gs = GremlinSession(
            enabled=True,
            cache_enabled=True,
            cache=mock_cache,
            source_hashes={'src/module.py': 'hash123'},
        )
        gremlin = MagicMock()
        gremlin.file_path = 'src/module.py'
        gremlin.gremlin_id = 'g001'
        result = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED)

        _cache_gremlin_result(gremlin, [], result, gs)

        mock_cache.cache_result_deferred.assert_called_once()

    def test_skips_caching_when_source_hash_missing(self) -> None:
        """cache_result_deferred is NOT called when gremlin's file has no source hash."""
        mock_cache = MagicMock()
        gs = GremlinSession(
            enabled=True,
            cache_enabled=True,
            cache=mock_cache,
            source_hashes={},
        )
        gremlin = MagicMock()
        gremlin.file_path = 'src/module.py'
        result = GremlinResult(gremlin=gremlin, status=GremlinResultStatus.ZAPPED)

        _cache_gremlin_result(gremlin, [], result, gs)

        mock_cache.cache_result_deferred.assert_not_called()


@pytest.mark.small
class TestTestGremlin:
    """Tests for _test_gremlin function (lines 1737-1739).

    Verifies that GREMLIN_SOURCES_ENV_VAR is injected into the subprocess env
    when instrumented_dir is not None, but not when it is None.
    """

    def test_sets_sources_env_var_when_instrumented_dir_provided(self, tmp_path: Path) -> None:
        """GREMLIN_SOURCES_ENV_VAR is set to '<instrumented_dir>/sources.json' in env."""
        gremlin = MagicMock()
        gremlin.gremlin_id = 'g001'
        captured_env: dict[str, str] = {}

        def capture_env(_cmd: list[str], **kwargs: object) -> object:
            env = kwargs.get('env')
            if isinstance(env, dict):
                captured_env.update(env)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=capture_env):
            _test_gremlin(gremlin, ['pytest'], tmp_path, instrumented_dir=tmp_path)

        assert GREMLIN_SOURCES_ENV_VAR in captured_env
        assert captured_env[GREMLIN_SOURCES_ENV_VAR] == str(tmp_path / 'sources.json')

    def test_omits_sources_env_var_when_instrumented_dir_is_none(self, tmp_path: Path) -> None:
        """GREMLIN_SOURCES_ENV_VAR is NOT set when instrumented_dir is None."""
        gremlin = MagicMock()
        gremlin.gremlin_id = 'g001'
        captured_env: dict[str, str] = {}

        def capture_env(_cmd: list[str], **kwargs: object) -> object:
            env = kwargs.get('env')
            if isinstance(env, dict):
                captured_env.update(env)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch('pytest_gremlins.plugin.subprocess.run', side_effect=capture_env):
            _test_gremlin(gremlin, ['pytest'], tmp_path, instrumented_dir=None)

        assert GREMLIN_SOURCES_ENV_VAR not in captured_env
