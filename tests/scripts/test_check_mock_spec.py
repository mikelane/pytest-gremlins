"""Tests for scripts/check_mock_spec.py -- bare MagicMock/Mock detector."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_mock_spec.py'


def _run_checker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_test_file(tmp_path: Path, code: str, filename: str = 'test_example.py') -> Path:
    """Write code into a tests/ subdirectory so the checker considers it in-scope."""
    tests_dir = tmp_path / 'tests'
    tests_dir.mkdir(exist_ok=True)
    target = tests_dir / filename
    target.write_text(textwrap.dedent(code))
    return target


@pytest.mark.medium
class DescribeCleanFiles:
    """Files with no bare MagicMock/Mock calls produce exit code 0."""

    def it_exits_zero_for_file_with_spec(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock(spec=dict)
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 0
        assert result.stdout == ''

    def it_exits_zero_for_file_with_spec_set(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock(spec_set=dict)
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 0
        assert result.stdout == ''

    def it_exits_zero_for_file_with_no_mocks(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            x = 1 + 2
            print(x)
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 0
        assert result.stdout == ''

    def it_exits_zero_for_non_test_file(self, tmp_path: Path) -> None:
        target = tmp_path / 'helper.py'
        target.write_text(
            textwrap.dedent("""\
            from unittest.mock import MagicMock
            m = MagicMock()
        """)
        )
        result = _run_checker(str(target))
        assert result.returncode == 1


@pytest.mark.medium
class DescribeBareViolations:
    """Files with bare MagicMock/Mock calls produce exit code 1."""

    def it_exits_one_for_bare_magicmock(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock()
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 1

    def it_exits_one_for_bare_mock(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import Mock
            m = Mock()
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 1

    def it_exits_one_for_magicmock_with_only_name_kwarg(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock(name='foo')
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 1

    def it_exits_one_for_magicmock_with_only_return_value(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock(return_value=42)
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 1

    def it_reports_filename_and_line_number(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock()
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 1
        assert str(target) in result.stdout
        assert ':2:' in result.stdout
        assert 'bare MagicMock()' in result.stdout


@pytest.mark.medium
class DescribeMultilineCall:
    """Multiline MagicMock calls are handled correctly."""

    def it_exits_zero_for_multiline_magicmock_with_spec(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock(
                spec=dict,
                name='foo',
            )
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 0
        assert result.stdout == ''

    def it_exits_one_for_multiline_magicmock_without_spec(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock(
                name='foo',
                return_value=42,
            )
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 1


@pytest.mark.medium
class DescribeEdgeCases:
    """Edge cases that exercise less obvious code paths."""

    def it_flags_attribute_style_mock_access(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            import unittest.mock
            m = unittest.mock.MagicMock()
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 1
        assert 'bare MagicMock()' in result.stdout

    def it_ignores_create_autospec(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import create_autospec
            m = create_autospec(dict)
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 0
        assert result.stdout == ''

    def it_exits_zero_for_file_with_syntax_error(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            def broken(
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 0
        assert result.stdout == ''

    def it_exits_zero_for_nonexistent_file(self, tmp_path: Path) -> None:
        result = _run_checker(str(tmp_path / 'does_not_exist.py'))
        assert result.returncode == 0
        assert result.stdout == ''


@pytest.mark.medium
class DescribeSuppression:
    """Lines with ``# bare-mock: ok`` are suppressed."""

    def it_exits_zero_when_bare_mock_has_suppression_comment(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock()  # bare-mock: ok
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 0
        assert result.stdout == ''

    def it_still_flags_bare_mock_without_suppression_comment(self, tmp_path: Path) -> None:
        target = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            ok = MagicMock()  # bare-mock: ok
            bad = MagicMock()
            """,
        )
        result = _run_checker(str(target))
        assert result.returncode == 1
        assert ':3:' in result.stdout
        assert ':2:' not in result.stdout


@pytest.mark.medium
class DescribeMultipleFiles:
    """The checker handles multiple file arguments."""

    def it_reports_violations_across_multiple_files(self, tmp_path: Path) -> None:
        file_a = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock()
            """,
            filename='test_a.py',
        )
        file_b = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import Mock
            m = Mock()
            """,
            filename='test_b.py',
        )
        result = _run_checker(str(file_a), str(file_b))
        assert result.returncode == 1
        assert str(file_a) in result.stdout
        assert str(file_b) in result.stdout

    def it_exits_zero_when_all_files_clean(self, tmp_path: Path) -> None:
        file_a = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import MagicMock
            m = MagicMock(spec=dict)
            """,
            filename='test_a.py',
        )
        file_b = _write_test_file(
            tmp_path,
            """\
            from unittest.mock import Mock
            m = Mock(spec_set=list)
            """,
            filename='test_b.py',
        )
        result = _run_checker(str(file_a), str(file_b))
        assert result.returncode == 0
        assert result.stdout == ''
