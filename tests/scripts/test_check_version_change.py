"""Tests for scripts/check_version_change.py -- the pull request guard on version changes (#1043)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(SCRIPTS))
try:
    _load('check_release_docs')
    guard = _load('check_version_change')
finally:
    sys.path.remove(str(SCRIPTS))

RELEASE_FILES = ['pyproject.toml', 'uv.lock', 'src/pytest_gremlins/__init__.py', 'CHANGELOG.md']


def _changelog(version: str) -> str:
    return (
        f'# Changelog\n\n## v{version} (2026-11-19)\n\n### Fix\n\n- **A fix.** (no docs: test)\n\n## v1.0.0\n\nOld.\n'
    )


def _pyproject(version: str | None) -> str:
    return '[project]\nname = "x"\n' + (f'version = "{version}"\n' if version else '')


def _init(version: str) -> str:
    return f'"""Package."""\n\n__version__ = \'{version}\'\n__all__ = [\'__version__\']\n'


def _check(
    *,
    branch: str = 'release/v1.15.0',
    base: str = '1.14.3',
    head: str = '1.15.0',
    base_module: str | None = None,
    head_module: str | None = None,
    files: list[str] | None = None,
    changelog: str | None = None,
) -> list[str]:
    problems: list[str] = guard.check_version_change(
        branch=branch,
        base_version=base,
        head_version=head,
        base_module_version=base if base_module is None else base_module,
        head_module_version=head if head_module is None else head_module,
        changed_files=RELEASE_FILES if files is None else files,
        changelog=_changelog(head) if changelog is None else changelog,
    )
    return problems


@pytest.mark.small
class DescribeCheckVersionChange:
    @pytest.mark.parametrize('branch', ['feature/x', 'release/v9.9.9', ''])
    def it_returns_no_problems_when_the_version_is_unchanged(self, branch: str) -> None:
        problems = _check(branch=branch, base='1.14.3', head='1.14.3', files=['src/pytest_gremlins/plugin.py'])

        assert problems == []

    def it_returns_no_problems_for_a_correct_release_pull_request(self) -> None:
        assert _check() == []

    def it_returns_no_problems_for_a_prerelease_on_its_own_branch(self) -> None:
        assert _check(branch='release/v1.15.0b0', head='1.15.0b0') == []

    def it_reports_a_version_change_on_a_non_release_branch(self) -> None:
        problems = _check(branch='feature/bump')

        assert len(problems) == 1
        assert 'release/v1.15.0' in problems[0]
        assert 'feature/bump' in problems[0]

    def it_reports_a_version_change_on_a_release_branch_for_another_version(self) -> None:
        problems = _check(branch='release/v1.16.0')

        assert len(problems) == 1
        assert 'release/v1.15.0' in problems[0]

    def it_requires_the_prerelease_suffix_in_the_branch_name(self) -> None:
        problems = _check(branch='release/v1.15.0', head='1.15.0b0')

        assert len(problems) == 1
        assert 'release/v1.15.0b0' in problems[0]

    def it_names_every_file_outside_the_release_set(self) -> None:
        extra_files = ['src/pytest_gremlins/plugin.py', 'docs/index.md']

        problems = _check(files=[*RELEASE_FILES, *extra_files])

        assert len(problems) == 1
        assert problems[0].endswith('but it also changes: docs/index.md, src/pytest_gremlins/plugin.py')

    def it_allows_a_release_that_changes_a_subset_of_the_release_files(self) -> None:
        assert _check(files=['pyproject.toml', 'CHANGELOG.md']) == []

    def it_reports_a_changelog_whose_topmost_entry_is_another_version(self) -> None:
        problems = _check(changelog=_changelog('1.14.3'))

        assert len(problems) == 1
        assert '1.15.0' in problems[0]
        assert 'CHANGELOG.md' in problems[0]

    def it_reports_a_changelog_with_no_version_entry(self) -> None:
        problems = _check(changelog='# Changelog\n\nNothing yet.\n')

        assert len(problems) == 1
        assert 'CHANGELOG.md' in problems[0]

    def it_reports_every_broken_rule_at_once(self) -> None:
        problems = _check(branch='feature/x', files=['src/x.py'], changelog=_changelog('1.0.0'))

        assert len(problems) == 3
        assert "so the branch must be release/v1.15.0, not 'feature/x'" in problems[0]
        assert problems[1].endswith('but it also changes: src/x.py')
        assert problems[2] == 'the topmost CHANGELOG.md entry is for 1.0.0, not 1.15.0'

    def it_reports_a_change_to_only_the_module_version_on_an_ordinary_branch(self) -> None:
        problems = _check(branch='feature/x', base='1.14.3', head='1.14.3', head_module='1.15.0', files=['a.py'])

        assert len(problems) == 3
        assert "so the branch must be release/v1.14.3, not 'feature/x'" in problems[1]

    def it_reports_head_versions_that_disagree_naming_both(self) -> None:
        problems = _check(head_module='1.14.3')

        assert len(problems) == 1
        assert '1.15.0' in problems[0]
        assert '1.14.3' in problems[0]
        assert '__version__' in problems[0]

    def it_accepts_a_release_whose_versions_match(self) -> None:
        assert _check(base_module='1.14.3', head_module='1.15.0') == []


@pytest.mark.small
class DescribeFindVersion:
    def it_reads_the_project_version(self) -> None:
        assert guard.project_version(_pyproject('1.2.3b0')) == '1.2.3b0'

    @pytest.mark.parametrize('text', ['', '[project]\nname = "x"\n', 'not = [valid', '[project]\nversion = 3\n'])
    def it_raises_when_the_version_cannot_be_read(self, text: str) -> None:
        with pytest.raises(guard.CannotCheckError):
            guard.project_version(text)


LITERAL = "__version__ = '1.14.3'\n"

REBINDINGS = {
    'tuple-unpacking': "__version__, _unused = '9.9.9', 0\n",
    'list-unpacking': "[__version__] = ['9.9.9']\n",
    'augmented-assignment': "__version__ += '.post1'\n",
    'inside-if': "if True:\n    __version__ = '9.9.9'\n",
    'inside-try': "try:\n    __version__ = '9.9.9'\nexcept Exception:\n    pass\n",
    'for-target': "for __version__ in ['9.9.9']:\n    pass\n",
    'walrus': "(__version__ := '9.9.9')\n",
    'import-as': 'from os import sep as __version__\n',
    'def-named': 'def __version__():\n    pass\n',
    'class-named': 'class __version__:\n    pass\n',
    'except-as': 'try:\n    pass\nexcept Exception as __version__:\n    pass\n',
    'global-statement': 'def f():\n    global __version__\n',
    'match-capture': 'match 1:\n    case __version__:\n        pass\n',
    'match-star': 'match []:\n    case [*__version__]:\n        pass\n',
    'match-mapping-rest': 'match {}:\n    case {**__version__}:\n        pass\n',
    'star-import': 'from os.path import *\n',
}


@pytest.mark.small
class DescribeModuleVersion:
    @pytest.mark.parametrize('rebinding', REBINDINGS.values(), ids=REBINDINGS.keys())
    def it_refuses_a_module_that_rebinds_version_after_the_literal(self, rebinding: str) -> None:
        with pytest.raises(guard.CannotCheckError):
            guard.module_version(LITERAL + rebinding)

    def it_names_the_star_import_as_the_reason_it_cannot_check(self) -> None:
        with pytest.raises(guard.CannotCheckError, match='star import'):
            guard.module_version(LITERAL + 'from os.path import *\n')

    def it_reads_the_module_level_version(self) -> None:
        assert guard.module_version(_init('1.2.3b0')) == '1.2.3b0'

    def it_reads_an_annotated_module_level_version(self) -> None:
        assert guard.module_version("__version__: str = '1.2.3'\n") == '1.2.3'

    def it_raises_when_the_module_has_two_module_level_versions(self) -> None:
        with pytest.raises(guard.CannotCheckError, match='2 module-level __version__'):
            guard.module_version("__version__ = '1.2.3'\n__version__ = '9.9.9'\n")

    @pytest.mark.parametrize(
        'text',
        ['', 'x = 1\n', '__version__ = 3\n', "__version__ = f'{x}'\n", 'def f():\n    __version__ = "1"\n', 'def (:\n'],
    )
    def it_raises_when_the_module_version_is_not_a_string_literal(self, text: str) -> None:
        with pytest.raises(guard.CannotCheckError):
            guard.module_version(text)

    def it_refuses_a_coding_cookie_that_hides_a_rebinding_from_a_utf8_read(self) -> None:
        # Under UTF-8 the second assignment is a comment; Python honours the cookie and decodes +AAo- as a newline.
        source = "# coding: utf-7\n__version__ = '1.14.3'  # +AAo-__version__ = '9.9.9'\n"

        with pytest.raises(guard.CannotCheckError):
            guard.module_version(source)

    @pytest.mark.parametrize(
        'submodule_import',
        ['from .__version__ import x\n', 'import pytest_gremlins.__version__\n', 'from . import __version__ as v\n'],
        ids=['relative-from-submodule', 'absolute-dotted-import', 'relative-import-as'],
    )
    def it_refuses_an_import_of_a_submodule_named_version(self, submodule_import: str) -> None:
        # Importing pytest_gremlins.__version__ sets the package attribute __version__ to the submodule object.
        with pytest.raises(guard.CannotCheckError):
            guard.module_version(LITERAL + submodule_import)


@pytest.mark.small
class DescribeVersionShape:
    @pytest.mark.parametrize('version', ['1.2.3\nversion_changed=false', '1.2 3', '', '1.2.3\r', '1.2.3\x00'])
    def it_rejects_a_version_with_whitespace_or_control_characters(self, version: str) -> None:
        with pytest.raises(guard.CannotCheckError):
            guard.project_version(_pyproject(version).replace(version, json.dumps(version)[1:-1]))
        with pytest.raises(guard.CannotCheckError):
            guard.module_version(f'__version__ = {version!r}\n')

    @pytest.mark.parametrize('version', ['1.2.3', '1!2.0.0rc1.post2.dev3+local.1-x_y'])
    def it_accepts_pep_440_shaped_versions(self, version: str) -> None:
        assert guard.module_version(f'__version__ = {version!r}\n') == version


class _FakeGit:
    """Stand-in for git: answers merge-base, ls-tree, show and diff, and records every call.

    ``show HEAD:<path>`` serves the file from the repository directory, so a test shapes HEAD by writing files.
    """

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        base_pyproject: str,
        changed: list[str],
        base_init: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.base_pyproject = base_pyproject
        self.base_init = base_init
        self.changed = changed
        self.failure: Exception | None = None
        self.modes: dict[tuple[str, str], str] = {}
        monkeypatch.setattr(guard, '_git_bytes', self._answer_git)

    def _base_pyproject_version(self) -> str:
        try:
            version: str = guard.project_version(self.base_pyproject)
        except guard.CannotCheckError:
            return '1.14.3'
        return version

    def _answer_git(self, repo: Path, *args: str) -> bytes:
        self.calls.append(args)
        if self.failure is not None:
            raise self.failure
        if args[0] == 'merge-base':
            return b'MERGEBASE\n'
        if args[0] == 'ls-tree':
            return self._listing(repo, ref=args[1], path=args[3])
        if args[0] == 'show':
            return self._show(repo, args[1])
        if args[0] == 'diff':
            return ''.join(f'{path}\n' for path in self.changed).encode()
        raise AssertionError(args)

    def _listing(self, repo: Path, *, ref: str, path: str) -> bytes:
        if ref == 'HEAD' and not (repo / path).exists():
            return b''
        mode = self.modes.get((ref, path), '100644')
        return f'{mode} blob 0123abc\t{path}\n'.encode()

    def _show(self, repo: Path, spec: str) -> bytes:
        ref, _, path = spec.partition(':')
        if ref == 'HEAD':
            return (repo / path).read_bytes()
        if spec == 'MERGEBASE:pyproject.toml':
            return self.base_pyproject.encode()
        if spec == 'MERGEBASE:src/pytest_gremlins/__init__.py':
            return (self.base_init if self.base_init is not None else _init(self._base_pyproject_version())).encode()
        return b'<<unexpected ref>>'


@pytest.fixture
def head_files(tmp_path: Path) -> Path:
    (tmp_path / 'pyproject.toml').write_text(_pyproject('1.15.0'), encoding='utf-8')
    (tmp_path / 'CHANGELOG.md').write_text(_changelog('1.15.0'), encoding='utf-8')
    (tmp_path / 'src' / 'pytest_gremlins').mkdir(parents=True)
    (tmp_path / 'src' / 'pytest_gremlins' / '__init__.py').write_text(_init('1.15.0'), encoding='utf-8')
    return tmp_path


def _run(root: Path, *extra_args: str, branch: str = 'release/v1.15.0') -> int:
    exit_code: int = guard.main(['--repo', str(root), '--branch', branch, '--base-ref', 'origin/main', *extra_args])
    return exit_code


@pytest.mark.medium
class DescribeMain:
    def it_exits_0_for_a_correct_release_pull_request(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 0
        assert 'release/v1.15.0' in capsys.readouterr().out

    def it_exits_1_naming_the_extra_file(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _FakeGit(
            monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=[*RELEASE_FILES, 'src/pytest_gremlins/plugin.py']
        )

        assert _run(head_files) == 1
        assert 'src/pytest_gremlins/plugin.py' in capsys.readouterr().out

    def it_prefixes_the_broken_rule_with_problem_on_stdout(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _FakeGit(
            monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=[*RELEASE_FILES, 'src/pytest_gremlins/plugin.py']
        )

        assert _run(head_files) == 1
        assert 'PROBLEM: a version change may touch only' in capsys.readouterr().out

    def it_exits_0_for_a_stale_branch_whose_base_tip_has_a_newer_version(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        (head_files / 'pyproject.toml').write_text(_pyproject('1.14.3'), encoding='utf-8')
        (head_files / 'src' / 'pytest_gremlins' / '__init__.py').write_text(_init('1.14.3'), encoding='utf-8')
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=['src/pytest_gremlins/plugin.py'])

        assert _run(head_files, branch='fix/stale') == 0
        assert ('show', 'MERGEBASE:pyproject.toml') in fake.calls
        assert not any('origin/main:pyproject.toml' in call for call in fake.calls)

    def it_takes_the_changed_files_from_the_merge_base(self, monkeypatch: pytest.MonkeyPatch, head_files: Path) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        _run(head_files)

        assert ('diff', '--name-only', '--no-renames', 'MERGEBASE...HEAD') in fake.calls

    def it_exits_2_when_git_fails(self, monkeypatch: pytest.MonkeyPatch, head_files: Path) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        fake.failure = guard.CannotCheckError('git failed')

        assert _run(head_files) == 2

    def it_exits_2_when_git_raises_something_unexpected(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)
        fake.failure = RuntimeError('boom')

        assert _run(head_files) == 2

    def it_exits_2_when_the_head_pyproject_is_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=[])

        assert _run(tmp_path) == 2

    @pytest.mark.parametrize('broken', ['', '[project]\nname = "x"\n', 'not = [valid'])
    def it_exits_2_when_the_head_version_cannot_be_read(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, broken: str
    ) -> None:
        (head_files / 'pyproject.toml').write_text(broken, encoding='utf-8')
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=[])

        assert _run(head_files) == 2

    def it_exits_2_when_the_base_version_cannot_be_read(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        _FakeGit(monkeypatch, base_pyproject='', changed=[])

        assert _run(head_files) == 2

    def it_exits_2_when_the_changelog_is_missing_for_a_version_change(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        (head_files / 'CHANGELOG.md').unlink()
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 2

    def it_exits_1_when_only_the_module_version_changed_on_an_ordinary_branch(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        (head_files / 'pyproject.toml').write_text(_pyproject('1.14.3'), encoding='utf-8')
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=['src/pytest_gremlins/__init__.py'])

        assert _run(head_files, branch='fix/x') == 1

    def it_exits_1_naming_both_versions_when_a_release_pull_request_disagrees(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (head_files / 'src' / 'pytest_gremlins' / '__init__.py').write_text(_init('1.14.3'), encoding='utf-8')
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 1
        out = capsys.readouterr().out
        assert '1.15.0' in out
        assert '1.14.3' in out

    @pytest.mark.parametrize('broken', ['', 'x = 1\n', '__version__ = 3\n'])
    def it_exits_2_when_the_module_version_cannot_be_read(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, broken: str
    ) -> None:
        (head_files / 'src' / 'pytest_gremlins' / '__init__.py').write_text(broken, encoding='utf-8')
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 2

    def it_exits_2_when_the_module_has_a_non_utf8_byte_in_a_comment(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        # Python refuses to import this file (no coding cookie, invalid UTF-8), but ast.parse(bytes) skips comments.
        init = head_files / 'src' / 'pytest_gremlins' / '__init__.py'
        init.write_bytes(b'# caf\xe9\n' + _init('1.15.0').encode('utf-8'))
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 2

    def it_exits_2_when_the_non_utf8_comment_byte_is_past_the_lines_the_cookie_scan_reads(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # tokenize.detect_encoding validates only the first two lines, so only the strict decode sees line 3.
        init = head_files / 'src' / 'pytest_gremlins' / '__init__.py'
        init.write_bytes(b'"""Doc."""\n\n# caf\xe9\n' + b"__version__ = '1.15.0'\n")
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 2
        assert 'src/pytest_gremlins/__init__.py does not parse' in capsys.readouterr().err

    def it_exits_0_for_a_latin1_cookie_module_with_a_latin1_byte_in_a_comment(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Python imports this file, so the guard must read its bytes and honour the cookie, not decode it as UTF-8.
        init = head_files / 'src' / 'pytest_gremlins' / '__init__.py'
        init.write_bytes(b'# -*- coding: latin-1 -*-\n# caf\xe9\n' + b"__version__ = '1.15.0'\n")
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files) == 0
        assert 'The version changed from 1.14.3 to 1.15.0 on release/v1.15.0' in capsys.readouterr().out

    def it_exits_2_and_writes_nothing_when_a_version_contains_a_newline(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        output = tmp_path_factory.mktemp('out') / 'github_output'
        (head_files / 'pyproject.toml').write_text('[project]\nversion = "1.15.0\\nevil=1"\n', encoding='utf-8')
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        assert _run(head_files, '--github-output', str(output)) == 2
        assert not output.exists() or output.read_text(encoding='utf-8') == ''

    def it_exits_2_for_bad_arguments(self) -> None:
        with pytest.raises(SystemExit) as raised:
            guard.main(['--no-such-option'])

        assert raised.value.code == 2

    @pytest.mark.parametrize(
        ('base', 'expected'),
        [('1.14.3', 'version_changed=true\nversion=1.15.0\n'), ('1.15.0', 'version_changed=false\nversion=1.15.0\n')],
    )
    def it_reports_whether_the_version_changed_to_github_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        head_files: Path,
        tmp_path_factory: pytest.TempPathFactory,
        base: str,
        expected: str,
    ) -> None:
        output = tmp_path_factory.mktemp('out') / 'github_output'
        _FakeGit(monkeypatch, base_pyproject=_pyproject(base), changed=RELEASE_FILES)

        _run(head_files, '--github-output', str(output))

        assert output.read_text(encoding='utf-8') == expected

    def it_reports_a_failed_guard_to_github_output_without_claiming_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        output = tmp_path_factory.mktemp('out') / 'github_output'
        _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=['src/x.py'])

        assert _run(head_files, '--github-output', str(output)) == 1
        assert 'version_changed=true' in output.read_text(encoding='utf-8')


NON_REGULAR_CASES = [
    (ref, path, mode)
    for ref in ('HEAD', 'MERGEBASE')
    for path in ('pyproject.toml', 'src/pytest_gremlins/__init__.py')
    for mode in ('120000', '160000', '040000')
]


@pytest.mark.medium
class DescribeRegularFileRequirement:
    @pytest.mark.parametrize('case', NON_REGULAR_CASES)
    def it_exits_2_naming_the_path_and_mode_when_a_version_file_is_not_a_regular_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        head_files: Path,
        capsys: pytest.CaptureFixture[str],
        case: tuple[str, str, str],
    ) -> None:
        ref, path, mode = case
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

        _run(head_files)

        assert ('show', 'HEAD:pyproject.toml') in fake.calls
        assert ('show', 'HEAD:CHANGELOG.md') in fake.calls


def _real_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false', *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.mark.medium
class DescribeMainWithRealGit:
    def it_exits_1_naming_a_source_file_renamed_onto_a_release_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo = tmp_path / 'repo'
        (repo / 'src' / 'pytest_gremlins').mkdir(parents=True)
        (repo / 'pyproject.toml').write_text(_pyproject('1.14.3'), encoding='utf-8')
        (repo / 'CHANGELOG.md').write_text(_changelog('1.14.3'), encoding='utf-8')
        (repo / 'src' / 'pytest_gremlins' / '__init__.py').write_text("__version__ = '1.14.3'\n", encoding='utf-8')
        (repo / 'src' / 'pytest_gremlins' / 'x.py').write_text('x = 1\n' * 20, encoding='utf-8')
        _real_git(repo, 'init', '-q', '-b', 'main')
        _real_git(repo, 'add', '.')
        _real_git(repo, 'commit', '-q', '-m', 'base')
        _real_git(repo, 'checkout', '-q', '-b', 'release/v1.2.0')
        _real_git(repo, 'mv', 'src/pytest_gremlins/x.py', 'uv.lock')
        (repo / 'pyproject.toml').write_text(_pyproject('1.2.0'), encoding='utf-8')
        (repo / 'CHANGELOG.md').write_text(_changelog('1.2.0'), encoding='utf-8')
        (repo / 'src' / 'pytest_gremlins' / '__init__.py').write_text("__version__ = '1.2.0'\n", encoding='utf-8')
        _real_git(repo, 'add', '.')
        _real_git(repo, 'commit', '-q', '-m', 'release')

        exit_code = guard.main(['--repo', str(repo), '--branch', 'release/v1.2.0', '--base-ref', 'main'])

        assert exit_code == 1
        assert 'src/pytest_gremlins/x.py' in capsys.readouterr().out
