"""Rerun options are read from ``@file`` arguments the way pytest expands them (refs #546)."""

from __future__ import annotations

import locale
from pathlib import Path

import pytest

from pytest_gremlins import rerun_options
from pytest_gremlins.rerun_options import rerun_options_in


@pytest.mark.medium
class DescribeRerunOptionsInArgumentFiles:
    """pytest expands ``@file`` arguments, one argument per line, before it parses the command line."""

    def it_reads_rerun_options_from_an_argument_file(self, tmp_path: Path) -> None:
        (tmp_path / 'args.txt').write_text('--reruns=2\n--only-rerun\nTimeout\n', encoding='utf-8')

        assert rerun_options_in(['@args.txt'], base_dir=tmp_path) == ['--reruns=2', '--only-rerun=Timeout']

    def it_reads_an_argument_file_given_by_absolute_path(self, tmp_path: Path) -> None:
        argument_file = tmp_path / 'args.txt'
        argument_file.write_text('--reruns=3\n', encoding='utf-8')

        assert rerun_options_in([f'@{argument_file}']) == ['--reruns=3']

    def it_pairs_an_option_ending_a_file_with_the_value_that_follows_it(self, tmp_path: Path) -> None:
        (tmp_path / 'args.txt').write_text('-x\n--reruns\n', encoding='utf-8')

        assert rerun_options_in(['@args.txt', '2'], base_dir=tmp_path) == ['--reruns=2']

    def it_reads_argument_files_named_inside_argument_files(self, tmp_path: Path) -> None:
        (tmp_path / 'outer.txt').write_text('@inner.txt\n', encoding='utf-8')
        (tmp_path / 'inner.txt').write_text('--reruns=4\n', encoding='utf-8')

        assert rerun_options_in(['@outer.txt'], base_dir=tmp_path) == ['--reruns=4']

    def it_ignores_an_argument_file_that_does_not_exist(self, tmp_path: Path) -> None:
        assert rerun_options_in(['@missing.txt', '--reruns=2'], base_dir=tmp_path) == ['--reruns=2']

    def it_stops_at_an_argument_file_that_names_itself(self, tmp_path: Path) -> None:
        (tmp_path / 'loop.txt').write_text('--reruns=2\n@loop.txt\n', encoding='utf-8')

        assert rerun_options_in(['@loop.txt'], base_dir=tmp_path) == ['--reruns=2']

    def it_stops_at_a_cycle_through_two_argument_files(self, tmp_path: Path) -> None:
        (tmp_path / 'first.txt').write_text('--reruns=2\n@second.txt\n', encoding='utf-8')
        (tmp_path / 'second.txt').write_text('--reruns-delay=1\n@first.txt\n', encoding='utf-8')

        assert rerun_options_in(['@first.txt'], base_dir=tmp_path) == ['--reruns=2', '--reruns-delay=1']

    def it_reads_an_argument_file_with_a_byte_that_is_not_utf8_the_way_argparse_does(self, tmp_path: Path) -> None:
        # An encoded surrogate is invalid in strict UTF-8 but decodes under both error handlers argparse may
        # use (surrogateescape on POSIX, surrogatepass on Windows); a lone latin-1 byte would not on Windows.
        (tmp_path / 'not_utf8.txt').write_bytes(b'--reruns\n2\n# \xed\xa0\x80\n')

        assert rerun_options_in(['@not_utf8.txt'], base_dir=tmp_path) == ['--reruns=2']

    def it_resolves_a_relative_argument_file_against_the_current_directory_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / 'args.txt').write_text('--reruns=5\n', encoding='utf-8')
        monkeypatch.chdir(tmp_path)

        assert rerun_options_in(['@args.txt']) == ['--reruns=5']

    def it_does_not_forward_a_p_that_only_appears_inside_an_argument_file(self, tmp_path: Path) -> None:
        (tmp_path / 'args.txt').write_text('-p\npytest_rerunfailures\n--reruns\n2\n', encoding='utf-8')

        assert rerun_options_in(['@args.txt'], base_dir=tmp_path) == ['--reruns=2']


@pytest.mark.medium
class DescribeArgumentFilesOnPythonBefore312:
    """Python 3.11's argparse opens an ``@file`` with the locale encoding, strictly; 3.12+ uses the filesystem's."""

    @pytest.fixture(autouse=True)
    def _argparse_reads_the_locale_encoding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rerun_options, '_ARGPARSE_READS_LOCALE_ENCODING', True)
        monkeypatch.setattr(locale, 'getpreferredencoding', lambda *_args: 'cp1252')

    def it_reads_a_file_in_the_locale_encoding_that_the_filesystem_encoding_would_reject(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('sys.getfilesystemencoding', lambda: 'utf-8')
        monkeypatch.setattr('sys.getfilesystemencodeerrors', lambda: 'surrogatepass')
        (tmp_path / 'args.txt').write_bytes('-k\ncafé\n--reruns\n2\n'.encode('cp1252'))

        assert rerun_options_in(['@args.txt'], base_dir=tmp_path) == ['--reruns=2']

    def it_ignores_a_file_the_locale_encoding_cannot_decode_instead_of_raising(self, tmp_path: Path) -> None:
        # cp1252 leaves 0x81 undefined, so a strict read fails; pytest would have rejected this file already.
        (tmp_path / 'args.txt').write_bytes(b'--reruns\n2\n\x81\n')

        assert rerun_options_in(['@args.txt', '--reruns-delay=1'], base_dir=tmp_path) == ['--reruns-delay=1']


@pytest.mark.medium
class DescribeArgumentFilesOnPython312AndLater:
    def it_ignores_a_file_the_filesystem_encoding_cannot_decode_instead_of_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rerun_options, '_ARGPARSE_READS_LOCALE_ENCODING', False)
        monkeypatch.setattr('sys.getfilesystemencoding', lambda: 'utf-8')
        monkeypatch.setattr('sys.getfilesystemencodeerrors', lambda: 'strict')
        (tmp_path / 'args.txt').write_bytes(b'--reruns\n2\n\xff\n')

        assert rerun_options_in(['@args.txt', '--reruns-delay=1'], base_dir=tmp_path) == ['--reruns-delay=1']
