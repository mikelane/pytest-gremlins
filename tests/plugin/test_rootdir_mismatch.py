"""The checks behind the rootdir mismatch guard, without a pytest session (#686, #690)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_gremlins.rootdir_mismatch import (
    argument_files_only_the_session_can_read,
    node_ids_that_do_not_resolve,
)


@pytest.mark.medium
class DescribeArgumentFilesOnlyTheSessionCanRead:
    def it_reports_a_file_only_the_session_directory_has(self, tmp_path: Path) -> None:
        session_dir, rootdir = tmp_path / 'session', tmp_path / 'root'
        session_dir.mkdir()
        rootdir.mkdir()
        (session_dir / 'args.txt').write_text('-q\n', encoding='utf-8')

        assert argument_files_only_the_session_can_read(['-x', '@args.txt'], session_dir, rootdir) == ['@args.txt']

    def it_ignores_a_file_both_directories_have_even_when_the_contents_differ(self, tmp_path: Path) -> None:
        session_dir, rootdir = tmp_path / 'session', tmp_path / 'root'
        session_dir.mkdir()
        rootdir.mkdir()
        (session_dir / 'args.txt').write_text('-q\n', encoding='utf-8')
        (rootdir / 'args.txt').write_text('-v\n', encoding='utf-8')

        assert argument_files_only_the_session_can_read(['@args.txt'], session_dir, rootdir) == []

    def it_ignores_a_file_the_session_directory_lacks_too(self, tmp_path: Path) -> None:
        assert argument_files_only_the_session_can_read(['@missing.txt'], tmp_path, tmp_path / 'root') == []

    def it_ignores_an_absolute_path(self, tmp_path: Path) -> None:
        absolute_file = tmp_path / 'args.txt'
        absolute_file.write_text('-q\n', encoding='utf-8')

        assert argument_files_only_the_session_can_read([f'@{absolute_file}'], tmp_path, tmp_path / 'root') == []

    def it_follows_a_nested_file_the_rootdir_copy_does_not_name(self, tmp_path: Path) -> None:
        session_dir, rootdir = tmp_path / 'session', tmp_path / 'root'
        session_dir.mkdir()
        rootdir.mkdir()
        (session_dir / 'outer.txt').write_text('@inner.txt\n', encoding='utf-8')
        (session_dir / 'inner.txt').write_text('-q\n', encoding='utf-8')
        (rootdir / 'outer.txt').write_text('-q\n', encoding='utf-8')

        assert argument_files_only_the_session_can_read(['@outer.txt'], session_dir, rootdir) == ['@inner.txt']

    def it_stops_at_a_file_that_names_itself(self, tmp_path: Path) -> None:
        (tmp_path / 'loop.txt').write_text('@loop.txt\n', encoding='utf-8')

        assert argument_files_only_the_session_can_read(['@loop.txt'], tmp_path, tmp_path / 'root') == ['@loop.txt']

    def it_names_a_file_once_when_addopts_and_pytest_addopts_both_name_it(self, tmp_path: Path) -> None:
        session_dir, rootdir = tmp_path / 'session', tmp_path / 'root'
        session_dir.mkdir()
        rootdir.mkdir()
        (session_dir / 'args.txt').write_text('-q\n', encoding='utf-8')

        assert argument_files_only_the_session_can_read(['@args.txt', '@args.txt'], session_dir, rootdir) == [
            '@args.txt'
        ]


@pytest.mark.medium
class DescribeNodeIdsThatDoNotResolve:
    def it_accepts_a_node_id_naming_the_tests_own_file(self, tmp_path: Path) -> None:
        (tmp_path / 'test_a.py').write_text('', encoding='utf-8')

        assert node_ids_that_do_not_resolve(tmp_path, [(tmp_path / 'test_a.py', 'test_a.py::test_x')]) == []

    def it_reports_a_node_id_with_an_empty_file_part(self, tmp_path: Path) -> None:
        outside = tmp_path / 'outside' / 'test_ext.py'
        outside.parent.mkdir()
        outside.write_text('', encoding='utf-8')

        assert node_ids_that_do_not_resolve(tmp_path / 'root', [(outside, '::test_ext')]) == ['::test_ext']

    def it_reports_a_node_id_that_names_a_missing_file(self, tmp_path: Path) -> None:
        assert node_ids_that_do_not_resolve(tmp_path, [(tmp_path / 'test_a.py', 'test_a.py::test_x')]) == [
            'test_a.py::test_x'
        ]

    def it_reports_a_node_id_that_names_a_different_file(self, tmp_path: Path) -> None:
        (tmp_path / 'test_a.py').write_text('', encoding='utf-8')
        (tmp_path / 'test_b.py').write_text('', encoding='utf-8')

        assert node_ids_that_do_not_resolve(tmp_path, [(tmp_path / 'test_b.py', 'test_a.py::test_x')]) == [
            'test_a.py::test_x'
        ]

    def it_accepts_a_directory_part_that_is_a_symlink(self, tmp_path: Path) -> None:
        real = tmp_path / 'real'
        real.mkdir()
        (real / 'test_a.py').write_text('', encoding='utf-8')
        (tmp_path / 'link').symlink_to(real, target_is_directory=True)

        assert node_ids_that_do_not_resolve(tmp_path, [(real / 'test_a.py', 'link/test_a.py::test_x')]) == []
