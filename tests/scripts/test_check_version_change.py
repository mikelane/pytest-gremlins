"""Tests for scripts/check_version_change.py -- the pull request guard on version changes (#1043)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
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


def _check(
    *,
    branch: str = 'release/v1.15.0',
    base: str = '1.14.3',
    head: str = '1.15.0',
    files: list[str] | None = None,
    changelog: str | None = None,
) -> list[str]:
    problems: list[str] = guard.check_version_change(
        branch=branch,
        base_version=base,
        head_version=head,
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
        extra = ['src/pytest_gremlins/plugin.py', 'docs/index.md']

        problems = _check(files=[*RELEASE_FILES, *extra])

        assert len(problems) == 1
        assert all(path in problems[0] for path in extra)

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


@pytest.mark.small
class DescribeFindVersion:
    def it_reads_the_project_version(self) -> None:
        assert guard.project_version(_pyproject('1.2.3b0')) == '1.2.3b0'

    @pytest.mark.parametrize('text', ['', '[project]\nname = "x"\n', 'not = [valid', '[project]\nversion = 3\n'])
    def it_raises_when_the_version_cannot_be_read(self, text: str) -> None:
        with pytest.raises(guard.CannotCheckError):
            guard.project_version(text)


class _FakeGit:
    """Stand-in for the git helper: answers merge-base, show and diff from fixed values, and records every call."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, base_pyproject: str, changed: list[str]) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.base_pyproject = base_pyproject
        self.changed = changed
        self.failure: Exception | None = None
        monkeypatch.setattr(guard, '_git', self._run)

    def _run(self, _repo: Path, *args: str) -> str:
        self.calls.append(args)
        if self.failure is not None:
            raise self.failure
        if args[0] == 'merge-base':
            return 'MERGEBASE\n'
        if args[0] == 'show':
            return self.base_pyproject if args[1] == 'MERGEBASE:pyproject.toml' else '<<unexpected ref>>'
        if args[0] == 'diff':
            return ''.join(f'{path}\n' for path in self.changed)
        raise AssertionError(args)


@pytest.fixture
def head_files(tmp_path: Path) -> Path:
    (tmp_path / 'pyproject.toml').write_text(_pyproject('1.15.0'), encoding='utf-8')
    (tmp_path / 'CHANGELOG.md').write_text(_changelog('1.15.0'), encoding='utf-8')
    return tmp_path


def _run(root: Path, *extra: str, branch: str = 'release/v1.15.0') -> int:
    exit_code: int = guard.main(['--repo', str(root), '--branch', branch, '--base-ref', 'origin/main', *extra])
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

    def it_exits_0_for_a_stale_branch_whose_base_tip_has_a_newer_version(
        self, monkeypatch: pytest.MonkeyPatch, head_files: Path
    ) -> None:
        (head_files / 'pyproject.toml').write_text(_pyproject('1.14.3'), encoding='utf-8')
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=['src/pytest_gremlins/plugin.py'])

        assert _run(head_files, branch='fix/stale') == 0
        assert ('show', 'MERGEBASE:pyproject.toml') in fake.calls
        assert not any('origin/main:pyproject.toml' in call for call in fake.calls)

    def it_takes_the_changed_files_from_the_merge_base(self, monkeypatch: pytest.MonkeyPatch, head_files: Path) -> None:
        fake = _FakeGit(monkeypatch, base_pyproject=_pyproject('1.14.3'), changed=RELEASE_FILES)

        _run(head_files)

        assert ('diff', '--name-only', 'MERGEBASE...HEAD') in fake.calls

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
