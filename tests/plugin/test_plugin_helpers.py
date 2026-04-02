"""Tests for plugin helper functions.

These tests cover the utility functions in plugin.py that can be tested in isolation.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from unittest.mock import (
    MagicMock,
    patch,
)

from _pytest.outcomes import Exit
import pytest

from pytest_gremlins.coverage.prioritized_selector import PrioritizedSelector
from pytest_gremlins.plugin import (
    GremlinSession,
    _add_source_file,
    _build_filtered_test_command,
    _build_test_command,
    _cleanup_instrumented_dir,
    _decode_numbits,
    _extract_test_name_from_context,
    _generate_gremlins,
    _is_excluded,
    _is_xdist_worker,
    _make_node_ids_relative,
    _parse_cli_report_formats,
    _path_to_module_name,
    _pytest_cov_available,
    _read_parallel_config,
    _select_tests_for_gremlin_prioritized,
    _should_include_file,
    _workers_type,
)


@pytest.mark.small
class DescribeGremlinSessionExcludePatterns:
    """Tests for exclude_patterns field on GremlinSession.

    Both the default and an explicit value are tested so a hardcoded
    return cannot pass both.
    """

    def it_defaults_to_empty_list(self) -> None:
        session = GremlinSession(enabled=True)
        assert session.exclude_patterns == []

    def it_stores_provided_patterns(self) -> None:
        session = GremlinSession(enabled=True, exclude_patterns=['**/migrations/*', 'vendor/**'])
        assert session.exclude_patterns == ['**/migrations/*', 'vendor/**']


@pytest.mark.small
class DescribeIsExcluded:
    """Tests for _is_excluded function.

    Both True and False branches are tested so a hardcoded return value fails.
    Multiple pattern tests ensure the function iterates over all patterns.
    """

    def it_excludes_file_matching_migrations_glob(self) -> None:
        path = Path('/project/src/app/migrations/0001_initial.py')
        rootdir = Path('/project')
        assert _is_excluded(path, rootdir, ['**/migrations/*']) is True

    def it_does_not_exclude_file_matching_no_patterns(self) -> None:
        path = Path('/project/src/app/models.py')
        rootdir = Path('/project')
        assert _is_excluded(path, rootdir, ['**/migrations/*']) is False

    def it_returns_false_for_empty_exclude_list(self) -> None:
        path = Path('/project/src/app/migrations/0001_initial.py')
        rootdir = Path('/project')
        assert _is_excluded(path, rootdir, []) is False

    def it_matches_second_pattern_in_list(self) -> None:
        path = Path('/project/src/app/generated/schema.py')
        rootdir = Path('/project')
        patterns = ['**/migrations/*', '**/generated/*']
        assert _is_excluded(path, rootdir, patterns) is True

    def it_matches_exact_relative_path(self) -> None:
        path = Path('/project/src/app/legacy.py')
        rootdir = Path('/project')
        assert _is_excluded(path, rootdir, ['src/app/legacy.py']) is True

    def it_does_not_exclude_partial_filename_match(self) -> None:
        path = Path('/project/src/app/legacy_utils.py')
        rootdir = Path('/project')
        assert _is_excluded(path, rootdir, ['src/app/legacy.py']) is False

    def it_matches_doublestar_when_dir_is_directly_under_rootdir(self) -> None:
        """``**/migrations/*`` must match even when migrations/ is at the top level."""
        path = Path('/project/migrations/0001_initial.py')
        rootdir = Path('/project')
        assert _is_excluded(path, rootdir, ['**/migrations/*']) is True

    def it_matches_doublestar_in_middle_with_zero_intermediate_dirs(self) -> None:
        """``src/**/migrations/*`` must match ``src/migrations/0001.py`` (zero dirs between)."""
        path = Path('/project/src/migrations/0001.py')
        rootdir = Path('/project')
        assert _is_excluded(path, rootdir, ['src/**/migrations/*']) is True

    def it_returns_false_when_path_is_outside_rootdir(self) -> None:
        """When the path is not under rootdir, _is_excluded returns False (not ValueError)."""
        path = Path('/other/project/migrations/0001.py')
        rootdir = Path('/project')
        assert _is_excluded(path, rootdir, ['**/migrations/*']) is False


@pytest.mark.small
class DescribeShouldIncludeFile:
    """Tests for _should_include_file function."""

    def it_excludes_test_files_with_test_prefix(self) -> None:
        assert _should_include_file(Path('test_something.py')) is False

    def it_excludes_test_files_with_test_suffix(self) -> None:
        assert _should_include_file(Path('something_test.py')) is False

    def it_excludes_conftest(self) -> None:
        assert _should_include_file(Path('conftest.py')) is False

    def it_includes_regular_source_files(self) -> None:
        assert _should_include_file(Path('module.py')) is True

    def it_excludes_pycache_files(self) -> None:
        assert _should_include_file(Path('__pycache__/module.cpython-311.pyc')) is False


@pytest.mark.medium
class DescribeAddSourceFile:
    """Tests for _add_source_file function."""

    def it_adds_valid_python_file(self, tmp_path: Path) -> None:
        """Valid Python file is added to the collection."""
        source_file = tmp_path / 'module.py'
        source_file.write_text('x = 1\n')
        source_files: dict[str, str] = {}

        _add_source_file(source_file, source_files)

        assert str(source_file) in source_files
        assert source_files[str(source_file)] == 'x = 1\n'

    def it_skips_file_with_syntax_error(self, tmp_path: Path) -> None:
        """File with syntax error is silently skipped."""
        bad_file = tmp_path / 'bad.py'
        bad_file.write_text('def broken(\n')  # Syntax error
        source_files: dict[str, str] = {}

        _add_source_file(bad_file, source_files)

        assert str(bad_file) not in source_files

    def it_skips_nonexistent_file(self, tmp_path: Path) -> None:
        """Nonexistent file is silently skipped."""
        missing_file = tmp_path / 'missing.py'
        source_files: dict[str, str] = {}

        _add_source_file(missing_file, source_files)

        assert str(missing_file) not in source_files


@pytest.mark.small
class DescribeMakeNodeIdsRelative:
    """Tests for _make_node_ids_relative function."""

    def it_makes_absolute_paths_relative(self, tmp_path: Path) -> None:
        """Absolute paths in node IDs are made relative to rootdir."""
        rootdir = tmp_path
        node_ids = [f'{tmp_path}/tests/test_module.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def it_keeps_relative_paths_unchanged(self, tmp_path: Path) -> None:
        """Relative paths in node IDs are unchanged."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def it_strips_test_category_suffix(self, tmp_path: Path) -> None:
        """Plugin-added suffixes like [SMALL] are stripped."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py::test_func [SMALL]']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py::test_func']

    def it_strips_rootdir_from_absolute_path_without_double_colon(self, tmp_path: Path) -> None:
        """Strips rootdir prefix from node IDs that are just file paths (no ::)."""
        rootdir = tmp_path
        abs_path = tmp_path / 'tests' / 'test_module.py'
        node_ids = [str(abs_path)]

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py']

    def it_preserves_relative_path_without_double_colon(self, tmp_path: Path) -> None:
        """Preserves relative paths without :: unchanged."""
        rootdir = tmp_path
        node_ids = ['tests/test_module.py']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['tests/test_module.py']

    def it_preserves_absolute_path_outside_rootdir(self, tmp_path: Path) -> None:
        """Preserves absolute paths that are not under rootdir unchanged."""
        rootdir = tmp_path
        node_ids = ['/some/other/path/test.py::test_func']

        result = _make_node_ids_relative(node_ids, rootdir)

        assert result == ['/some/other/path/test.py::test_func']


@pytest.mark.small
class DescribePathToModuleName:
    """Tests for _path_to_module_name function."""

    def it_converts_relative_path_to_module(self, tmp_path: Path) -> None:
        """Converts relative path to module name."""
        file_path = tmp_path / 'package' / 'module.py'
        result = _path_to_module_name(file_path, tmp_path)
        assert result == 'package.module'

    def it_strips_src_prefix(self, tmp_path: Path) -> None:
        """Strips src/ prefix from path since it's a layout convention."""
        file_path = tmp_path / 'src' / 'mypackage' / 'module.py'
        result = _path_to_module_name(file_path, tmp_path)
        assert result == 'mypackage.module'


@pytest.mark.medium
class DescribePathToModuleNameFileIO:
    """Filesystem tests for _path_to_module_name — require real directory creation."""

    def it_handles_file_not_relative_to_rootdir(self, tmp_path: Path) -> None:
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
class DescribeBuildTestCommand:
    """Tests for _build_test_command function."""

    def it_builds_command_without_instrumented_dir(self) -> None:
        """When instrumented_dir is None, runs pytest directly.

        Covers line 1321: return branch when instrumented_dir is None.
        """
        result = _build_test_command(None)

        assert '-m' in result
        assert 'pytest' in result
        assert '-x' in result
        assert '--tb=no' in result

    def it_suppresses_addopts_when_instrumented_dir_is_none(self) -> None:
        """When instrumented_dir is None, resets addopts to prevent inherited flags."""
        result = _build_test_command(None)

        assert '-o' in result
        assert 'addopts=' in result

    def it_includes_no_cov_when_pytest_cov_is_available(self) -> None:
        """When pytest-cov is importable, --no-cov is appended."""
        with patch('pytest_gremlins.plugin._pytest_cov_available', return_value=True):
            result = _build_test_command(None)

        assert '--no-cov' in result

    def it_omits_no_cov_when_pytest_cov_is_unavailable(self) -> None:
        """When pytest-cov is not importable, --no-cov is omitted."""
        with patch('pytest_gremlins.plugin._pytest_cov_available', return_value=False):
            result = _build_test_command(None)

        assert '--no-cov' not in result


@pytest.mark.medium
class DescribeBuildTestCommandFileIO:
    """Filesystem tests for _build_test_command — require real directory creation."""

    def it_builds_command_with_instrumented_dir(self, tmp_path: Path) -> None:
        """When instrumented_dir provided, uses bootstrap script."""
        instrumented_dir = tmp_path / 'instrumented'
        instrumented_dir.mkdir()

        result = _build_test_command(instrumented_dir)

        assert 'gremlin_bootstrap.py' in result[1]
        assert '-x' in result
        assert '--tb=no' in result

    def it_suppresses_addopts_when_instrumented_dir_provided(self, tmp_path: Path) -> None:
        """When instrumented_dir provided, resets addopts to prevent inherited flags."""
        instrumented_dir = tmp_path / 'instrumented'
        instrumented_dir.mkdir()

        result = _build_test_command(instrumented_dir)

        assert '-o' in result
        assert 'addopts=' in result

    def it_includes_no_cov_when_pytest_cov_is_available_with_instrumented_dir(self, tmp_path: Path) -> None:
        """When pytest-cov is importable with instrumented_dir, --no-cov is appended."""
        instrumented_dir = tmp_path / 'instrumented'
        instrumented_dir.mkdir()

        with patch('pytest_gremlins.plugin._pytest_cov_available', return_value=True):
            result = _build_test_command(instrumented_dir)

        assert '--no-cov' in result

    def it_omits_no_cov_when_pytest_cov_is_unavailable_with_instrumented_dir(self, tmp_path: Path) -> None:
        """When pytest-cov is not importable with instrumented_dir, --no-cov is omitted."""
        instrumented_dir = tmp_path / 'instrumented'
        instrumented_dir.mkdir()

        with patch('pytest_gremlins.plugin._pytest_cov_available', return_value=False):
            result = _build_test_command(instrumented_dir)

        assert '--no-cov' not in result


@pytest.mark.small
class DescribePytestCovAvailable:
    """Tests for _pytest_cov_available helper.

    Both True and False branches are tested so a hardcoded return value fails.
    """

    def it_returns_true_when_pytest_cov_is_importable(self) -> None:
        """Returns True when pytest_cov can be imported."""
        result = _pytest_cov_available()

        # In our dev environment, pytest-cov is installed
        assert result is True

    def it_returns_false_when_pytest_cov_import_fails(self) -> None:
        """Returns False when pytest_cov import raises ImportError."""
        import builtins  # noqa: PLC0415

        original_import = builtins.__import__

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == 'pytest_cov':
                raise ImportError('No module named pytest_cov')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            result = _pytest_cov_available()

        assert result is False


@pytest.mark.small
class DescribeIsXdistWorker:
    """Tests for _is_xdist_worker function.

    Both True and False branches are tested so a hardcoded return value fails.
    """

    def it_returns_true_when_workerinput_present(self) -> None:
        """Config with workerinput attribute is an xdist worker."""
        config = MagicMock(spec=['workerinput'])
        config.workerinput = {'slaveid': 'gw0'}

        assert _is_xdist_worker(config) is True

    def it_returns_false_when_workerinput_absent(self) -> None:
        """Config without workerinput attribute is not an xdist worker."""
        config = MagicMock(spec=[])

        assert _is_xdist_worker(config) is False


@pytest.mark.small
class DescribeReadParallelConfig:
    """Tests for _read_parallel_config function."""

    def it_workers_alone_implies_parallel_enabled(self) -> None:
        """Passing --gremlin-workers=N without --gremlin-parallel still enables parallel mode."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = 4

        parallel_enabled, parallel_workers = _read_parallel_config(config)

        assert parallel_enabled is True
        assert parallel_workers == 4

    def it_workers_none_without_parallel_flag_stays_disabled(self) -> None:
        """When neither --gremlin-workers nor --gremlin-parallel is set, parallel stays disabled."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = None

        parallel_enabled, parallel_workers = _read_parallel_config(config)

        assert parallel_enabled is False
        assert parallel_workers is None

    def it_workers_implies_parallel_with_explicit_count(self) -> None:
        """--gremlin-workers=2 implies parallel with worker count preserved."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = 2

        parallel_enabled, parallel_workers = _read_parallel_config(config)

        assert parallel_enabled is True
        assert parallel_workers == 2

    @pytest.mark.small
    def it_uses_xdist_int_worker_count_when_no_cli_workers(self) -> None:
        """When xdist provides an int worker count and --gremlin-workers is unset, use it."""
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = None

        parallel_enabled, parallel_workers = _read_parallel_config(config, xdist_workers=4)

        assert parallel_enabled is True
        assert parallel_workers == 4


@pytest.mark.small
class DescribeSelectTestsForGremlinPrioritized:
    """Tests for _select_tests_for_gremlin_prioritized function."""

    def it_returns_all_tests_when_no_prioritized_selector(self) -> None:
        """Falls back to all test_node_ids keys when prioritized_selector is None."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        gremlin = MagicMock()  # Gremlin is a frozen dataclass; spec= misses instance fields; bare-mock: ok

        result = _select_tests_for_gremlin_prioritized(gremlin, gs)

        assert set(result) == {'test_a', 'test_b'}

    def it_returns_all_tests_when_selector_returns_empty(self) -> None:
        """Falls back to all test_node_ids keys when selector finds no covering tests."""
        mock_selector = MagicMock(spec=PrioritizedSelector)
        mock_selector.select_tests_prioritized.return_value = []
        gs = GremlinSession(
            enabled=True,
            prioritized_selector=mock_selector,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        gremlin = MagicMock()  # Gremlin is a frozen dataclass; spec= misses instance fields; bare-mock: ok

        result = _select_tests_for_gremlin_prioritized(gremlin, gs)

        assert set(result) == {'test_a', 'test_b'}

    def it_returns_selector_result_when_covering_tests_found(self) -> None:
        """Returns prioritized list when selector finds covering tests."""
        mock_selector = MagicMock(spec=PrioritizedSelector)
        mock_selector.select_tests_prioritized.return_value = ['test_a']
        gs = GremlinSession(
            enabled=True,
            prioritized_selector=mock_selector,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        gremlin = MagicMock()  # Gremlin is a frozen dataclass; spec= misses instance fields; bare-mock: ok

        result = _select_tests_for_gremlin_prioritized(gremlin, gs)

        assert result == ['test_a']


@pytest.mark.small
class DescribeBuildFilteredTestCommand:
    """Tests for _build_filtered_test_command function."""

    def it_appends_node_ids_from_selected_tests(self) -> None:
        """Node IDs for selected tests are appended to the base command."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={'test_a': 'tests/test_m.py::test_a', 'test_b': 'tests/test_m.py::test_b'},
        )
        base = ['python', '-m', 'pytest']

        result = _build_filtered_test_command(base, ['test_a', 'test_b'], gs)

        assert 'tests/test_m.py::test_a' in result
        assert 'tests/test_m.py::test_b' in result

    def it_preserves_order_of_selected_tests(self) -> None:
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

    def it_skips_tests_not_in_node_ids(self) -> None:
        """Tests not present in test_node_ids are silently skipped."""
        gs = GremlinSession(
            enabled=True,
            test_node_ids={'test_a': 'tests/test_m.py::test_a'},
        )
        base = ['python', '-m', 'pytest']

        result = _build_filtered_test_command(base, ['test_a', 'test_missing'], gs)

        assert 'tests/test_m.py::test_a' in result
        assert 'test_missing' not in result

    def it_returns_base_command_unchanged_when_no_matching_tests(self) -> None:
        """When no selected tests exist in node_ids, base command is returned as-is."""
        gs = GremlinSession(enabled=True, test_node_ids={})
        base = ['python', '-m', 'pytest']

        result = _build_filtered_test_command(base, ['test_gone'], gs)

        assert result == base


@pytest.mark.small
class DescribeDecodeNumbits:
    """Tests for _decode_numbits — coverage.py bit-compressed line number decoder.

    Both directions (set bit → line present, clear bit → line absent) are tested
    so a hardcoded empty-list or all-lines return cannot pass all cases.
    """

    def it_decodes_single_line_zero_from_bit_zero(self) -> None:
        """Byte 0x01 encodes line 0 (bit 0 of byte 0)."""
        assert _decode_numbits(bytes([0x01])) == [0]

    def it_decodes_single_line_one_from_bit_one(self) -> None:
        """Byte 0x02 encodes line 1 (bit 1 of byte 0)."""
        assert _decode_numbits(bytes([0x02])) == [1]

    def it_decodes_multiple_lines_from_one_byte(self) -> None:
        """0x03 (bits 0 and 1 set) encodes lines 0 and 1."""
        assert _decode_numbits(bytes([0x03])) == [0, 1]

    def it_decodes_line_from_second_byte(self) -> None:
        """Bit 0 of byte 1 encodes line 8."""
        assert _decode_numbits(bytes([0x00, 0x01])) == [8]

    def it_returns_no_lines_for_empty_bytes(self) -> None:
        """Empty bytes produce an empty list."""
        assert _decode_numbits(b'') == []


@pytest.mark.small
class DescribeCleanupInstrumentedDir:
    """Tests for _cleanup_instrumented_dir.

    Both branches (None and existing path) tested so a hardcoded no-op fails.
    """

    def it_does_nothing_when_path_is_none(self) -> None:
        """None path causes the function to return without error."""
        _cleanup_instrumented_dir(None)  # must not raise

    def it_does_nothing_when_directory_does_not_exist(self) -> None:
        _cleanup_instrumented_dir(Path('/nonexistent/path/not_here'))  # must not raise


@pytest.mark.medium
class DescribeCleanupInstrumentedDirFileIO:
    """Filesystem tests for _cleanup_instrumented_dir — require real directory creation."""

    def it_removes_existing_directory(self, tmp_path: Path) -> None:
        """When the directory exists, shutil.rmtree removes it."""
        instrumented = tmp_path / 'instrumented'
        instrumented.mkdir()
        (instrumented / 'file.py').write_text('x = 1\n')

        _cleanup_instrumented_dir(instrumented)

        assert not instrumented.exists()


@pytest.mark.small
class DescribeWorkersType:
    """Tests for _workers_type — argument parser for --gremlin-workers.

    Four distinct branches: 'auto', valid positive integer, non-integer string
    (raises), and zero/negative integer (raises). A hardcoded return value
    cannot survive all four branches simultaneously.
    """

    def it_returns_cpu_count_or_four_for_auto(self) -> None:
        # ARRANGE / ACT
        result = _workers_type('auto')

        # ASSERT — must be a positive integer; cannot be hardcoded to a fixed
        # value because os.cpu_count() is environment-dependent.
        assert isinstance(result, int)
        assert result >= 1

    def it_returns_integer_for_valid_positive_string(self) -> None:
        # ARRANGE / ACT
        result = _workers_type('4')

        # ASSERT — specific value proves the int() conversion path ran.
        assert result == 4

    def it_raises_for_non_integer_string(self) -> None:
        # ARRANGE / ACT / ASSERT
        with pytest.raises(argparse.ArgumentTypeError, match='Invalid workers value'):
            _workers_type('banana')

    def it_raises_for_zero(self) -> None:
        # ARRANGE / ACT / ASSERT — zero is not a positive integer.
        with pytest.raises(argparse.ArgumentTypeError, match='positive integer'):
            _workers_type('0')

    def it_raises_for_negative_integer(self) -> None:
        # ARRANGE / ACT / ASSERT — negative values must also be rejected.
        with pytest.raises(argparse.ArgumentTypeError, match='positive integer'):
            _workers_type('-1')


@pytest.mark.small
class DescribeExtractTestNameFromContext:
    """Tests for _extract_test_name_from_context.

    Three branches exist in production:
      1. Pipe-format (new GremlinContextPlugin): 'nodeid|when'
      2. Double-colon format (old coverage): 'path::test_name'
      3. Plain name or dot-separated class: 'TestClass.test_method' or 'test_name'

    Hardcoding 'test_bar' passes most cases but fails on the dot-only and
    single-name-only branches — both are tested explicitly.
    """

    def it_extracts_function_name_from_pipe_format_with_colons(self) -> None:
        # ARRANGE
        context = 'tests/test_foo.py::TestFoo::test_bar|run'

        # ACT
        result = _extract_test_name_from_context(context)

        # ASSERT — full node ID preserved, only |when stripped
        assert result == 'tests/test_foo.py::TestFoo::test_bar'

    def it_extracts_function_name_from_pipe_format_setup_phase(self) -> None:
        # ARRANGE — 'setup' phase; the when-segment must be stripped.
        context = 'tests/test_foo.py::test_bar|setup'

        # ACT
        result = _extract_test_name_from_context(context)

        # ASSERT — full node ID preserved, only |setup stripped
        assert result == 'tests/test_foo.py::test_bar'

    def it_returns_raw_nodeid_when_pipe_format_has_no_colons(self) -> None:
        # ARRANGE — nodeid contains no '::'; returned as-is after stripping '|when'.
        context = 'test_bar|run'

        # ACT
        result = _extract_test_name_from_context(context)

        # ASSERT — the full nodeid portion (before '|') is returned.
        assert result == 'test_bar'

    def it_extracts_function_name_from_double_colon_format(self) -> None:
        # ARRANGE — old coverage format: path::function_name
        context = 'tests/test_foo.py::test_func'

        # ACT
        result = _extract_test_name_from_context(context)

        # ASSERT — full identifier preserved
        assert result == 'tests/test_foo.py::test_func'

    def it_returns_full_dot_separated_context(self) -> None:
        # ARRANGE — old coverage format: ClassName.method_name
        context = 'TestClass.test_method'

        # ACT
        result = _extract_test_name_from_context(context)

        # ASSERT — full context preserved (no longer strips to bare function name)
        assert result == 'TestClass.test_method'

    def it_returns_plain_name_unchanged(self) -> None:
        # ARRANGE — bare function name with no separators.
        context = 'test_bar'

        # ACT
        result = _extract_test_name_from_context(context)

        # ASSERT — rsplit('.', maxsplit=1)[-1] on a name with no dot returns the name.
        assert result == 'test_bar'


@pytest.mark.small
class DescribeReadParallelConfigMissingBranches:
    """Additional branch coverage for _read_parallel_config.

    The existing suite misses two branches:
      - gremlin_parallel=True with no cli_workers (flag alone enables parallel).
      - xdist_workers=0 with no cli_workers (zero is not None, so the xdist
        fallback branch fires and returns (True, 0)).

    A hardcoded '(False, None)' return fails both; a hardcoded '(True, N)'
    fails the first existing test that expects (False, None).
    """

    def it_enables_parallel_when_gremlin_parallel_flag_set_and_no_workers(self) -> None:
        # ARRANGE
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = True
        config.option.gremlin_workers = None

        # ACT
        parallel_enabled, parallel_workers = _read_parallel_config(config)

        # ASSERT — flag alone must enable parallel; worker count stays None (use CPU count).
        assert parallel_enabled is True
        assert parallel_workers is None

    def it_uses_xdist_workers_zero_as_fallback_count(self) -> None:
        # ARRANGE — xdist_workers=0 means xdist ran with -n 0 (no distribution).
        # The function does not interpret zero specially; it forwards it as-is.
        config = MagicMock(spec=['option'])
        config.option = MagicMock(spec=['gremlin_parallel', 'gremlin_workers'])
        config.option.gremlin_parallel = False
        config.option.gremlin_workers = None

        # ACT
        parallel_enabled, parallel_workers = _read_parallel_config(config, xdist_workers=0)

        # ASSERT — xdist_workers=0 is not None, so the early-return branch fires.
        assert parallel_enabled is True
        assert parallel_workers == 0


@pytest.mark.small
class DescribeGenerateGremlins:
    """Tests for _generate_gremlins error-handling path."""

    def it_skips_file_and_logs_exception_when_transform_source_raises(self, caplog: pytest.LogCaptureFixture) -> None:
        gs = GremlinSession(enabled=True)
        source_files = {'bad_file.py': 'x = 1'}

        with (
            caplog.at_level(logging.ERROR, logger='pytest_gremlins.plugin'),
            patch('pytest_gremlins.plugin.transform_source', side_effect=ValueError('boom')),
        ):
            _generate_gremlins(gs, source_files, Path('/fake/root'))

        # File is skipped: no gremlins collected.
        assert gs.gremlins == []
        # Exception is logged (logger.exception emits at ERROR level).
        assert any('Failed to transform bad_file.py' in r.message for r in caplog.records)


@pytest.mark.small
class DescribeParseCliReportFormats:
    """Tests for _parse_cli_report_formats helper.

    Covers: None passthrough, single string, list from action='append',
    comma-separated within list elements, deduplication, empty-after-filter,
    and unknown format rejection.
    """

    def it_returns_none_when_raw_is_none(self) -> None:
        result = _parse_cli_report_formats(None)

        assert result is None

    def it_parses_single_string_value(self) -> None:
        result = _parse_cli_report_formats('html')

        assert result == ['html']

    def it_parses_comma_separated_string(self) -> None:
        result = _parse_cli_report_formats('html,json')

        assert result == ['html', 'json']

    def it_parses_list_from_repeated_flags(self) -> None:
        result = _parse_cli_report_formats(['html', 'json'])

        assert result == ['html', 'json']

    def it_flattens_comma_separated_elements_in_list(self) -> None:
        result = _parse_cli_report_formats(['html,console', 'json'])

        assert result == ['html', 'console', 'json']

    def it_deduplicates_preserving_insertion_order(self) -> None:
        result = _parse_cli_report_formats(['html', 'json', 'html'])

        assert result == ['html', 'json']

    def it_strips_whitespace_from_formats(self) -> None:
        result = _parse_cli_report_formats(' html , json ')

        assert result == ['html', 'json']

    def it_exits_when_all_formats_are_empty(self) -> None:
        with pytest.raises(Exit, match='at least one valid format'):
            _parse_cli_report_formats(',,,')

    def it_exits_on_unknown_format(self) -> None:
        with pytest.raises(Exit, match='Unknown --gremlin-report format'):
            _parse_cli_report_formats('xml')
