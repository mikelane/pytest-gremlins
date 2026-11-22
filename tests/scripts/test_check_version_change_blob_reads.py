"""Blob-read guarantees of ``scripts/check_version_change.py`` (issue #1049): regular files, checkout equals blob."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scripts.test_check_version_change import (
    RELEASE_FILES,
    _FakeGit,
    _pyproject,
    _run,
    write_head_files,
)


@pytest.fixture
def head_files(tmp_path: Path) -> Path:
    return write_head_files(tmp_path)


@pytest.mark.medium
class DescribeRegularFileRequirement:
    @pytest.mark.parametrize('ref', ['HEAD', 'MERGEBASE'])
    @pytest.mark.parametrize('path', ['pyproject.toml', 'src/pytest_gremlins/__init__.py'])
    @pytest.mark.parametrize('mode', ['120000', '160000', '040000'])
    def it_exits_2_naming_the_path_and_mode_when_a_version_file_is_not_a_regular_file(
        self,
        *,
        monkeypatch: pytest.MonkeyPatch,
        head_files: Path,
        capsys: pytest.CaptureFixture[str],
        ref: str,
        path: str,
        mode: str,
    ) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        fake.modes[(ref, path)] = mode

        assert _run(head_files) == 2
        err = capsys.readouterr().err
        assert path in err
        assert mode in err

    def it_exits_2_when_the_changelog_at_head_is_a_symlink(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        fake.modes[('HEAD', 'CHANGELOG.md')] = '120000'

        assert _run(head_files) == 2
        assert 'CHANGELOG.md' in capsys.readouterr().err

    @pytest.mark.parametrize('ref', ['HEAD', 'MERGEBASE'])
    @pytest.mark.parametrize('path', ['pyproject.toml', 'src/pytest_gremlins/__init__.py', 'CHANGELOG.md'])
    def it_accepts_an_executable_regular_file(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, ref: str, path: str
    ) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        fake.modes[(ref, path)] = '100755'

        assert _run(head_files) == 0

    def it_reads_head_through_git_and_not_from_the_working_tree(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        exit_code = _run(head_files)

        assert exit_code == 0
        assert ('show', 'HEAD:pyproject.toml') in fake.calls
        assert ('show', 'HEAD:CHANGELOG.md') in fake.calls

    def it_exits_2_naming_the_path_when_a_version_file_is_absent_at_head(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=[])

        assert _run(tmp_path) == 2
        assert 'pyproject.toml does not exist at HEAD' in capsys.readouterr().err

    def it_exits_2_naming_the_path_when_the_head_pyproject_is_not_utf8(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (head_files / 'pyproject.toml').write_bytes(b'# caf\xe9\n' + _pyproject('1.15.0').encode('utf-8'))
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 2
        assert 'cannot read pyproject.toml at HEAD' in capsys.readouterr().err

    def it_exits_2_when_git_prints_output_that_is_not_utf8(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        fake.merge_base_output = b'\xff\n'

        assert _run(head_files) == 2
        assert 'printed output that is not UTF-8' in capsys.readouterr().err


@pytest.mark.medium
class DescribeCheckedOutFilesMatchTheCommittedBlobs:
    @pytest.mark.parametrize('path', ['pyproject.toml', 'src/pytest_gremlins/__init__.py', 'CHANGELOG.md'])
    def it_exits_2_naming_the_path_when_the_checked_out_file_differs_from_its_blob(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str], path: str
    ) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        fake.head_blobs[path] = (head_files / path).read_bytes() + b'# only in the blob\n'

        assert _run(head_files) == 2
        err = capsys.readouterr().err
        assert path in err
        assert '.gitattributes' in err

    def it_exits_2_when_a_parent_directory_of_a_version_file_is_a_symlink(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        real_src = head_files / 'elsewhere'
        (head_files / 'src').rename(real_src)
        (head_files / 'src').symlink_to(real_src, target_is_directory=True)

        assert _run(head_files) == 2
        assert 'src' in capsys.readouterr().err

    def it_exits_2_when_the_checked_out_file_is_a_symlink(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        target = head_files / 'real-changelog.md'
        (head_files / 'CHANGELOG.md').rename(target)
        (head_files / 'CHANGELOG.md').symlink_to(target)

        assert _run(head_files) == 2
        assert 'CHANGELOG.md' in capsys.readouterr().err

    def it_exits_0_when_every_checked_out_file_matches_its_blob(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 0
