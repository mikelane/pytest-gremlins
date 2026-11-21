"""Tests for scripts/prepare_release.py -- builds a release branch with an unfinished changelog entry (#1044)."""

from __future__ import annotations

from collections.abc import Sequence
import datetime
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any

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
    docs_gate = _load('check_release_docs')
    version_guard = _load('check_version_change')
    prepare = _load('prepare_release')
finally:
    sys.path.remove(str(SCRIPTS))

RELEASE_DATE = datetime.date(2026, 11, 20)
SECTION_HEADINGS = ['### Upgrade notes', '### Feature', '### Fix', '### Internal', '### Documentation']
CHANGELOG = '# Changelog\n\nIntro.\n\n## v1.14.3 (2026-11-16)\n\n### Fix\n\n- **Old.** (no docs: test)\n'


def _commit(subject: str, body: str = '', sha: str = '1111111aaaaaaa') -> Any:
    return prepare.Commit(sha=sha, subject=subject, body=body)


def _entry(*commits: object, version: str = '1.15.0') -> str:
    entry: str = prepare.render_entry(version, RELEASE_DATE, list(commits))
    return entry


def _gate_problems(tmp_path: Path, entry: str, version: str = '1.15.0') -> list[str]:
    changelog = prepare.insert_entry(CHANGELOG, entry)
    path = tmp_path / 'CHANGELOG.md'
    path.write_text(changelog, encoding='utf-8')
    site = tmp_path / 'site'
    site.mkdir(exist_ok=True)
    (site / 'index.html').write_text('<html><body></body></html>', encoding='utf-8')
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / 'check_release_docs.py'),
            version,
            '--site-dir',
            str(site),
            '--changelog',
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    return [line for line in completed.stdout.splitlines() if line.startswith(docs_gate.PROBLEM_PREFIX)]


@pytest.mark.small
class DescribeParseCommitLog:
    def it_returns_no_commits_for_an_empty_log(self) -> None:
        assert prepare.parse_commit_log('') == []

    def it_keeps_a_unit_separator_inside_a_body(self) -> None:
        commits = prepare.parse_commit_log('aaa\x1ffix: a\x1fone\x1ftwo\x1e')

        assert commits[0].body == 'one\x1ftwo'

    def it_reads_sha_subject_and_body_of_each_commit(self) -> None:
        raw = 'aaa\x1ffeat: add a thing\x1fLonger text\x1e\nbbb\x1ffix: repair\x1f\x1e\n'

        commits = prepare.parse_commit_log(raw)

        assert [(c.sha, c.subject, c.body) for c in commits] == [
            ('aaa', 'feat: add a thing', 'Longer text'),
            ('bbb', 'fix: repair', ''),
        ]


@pytest.mark.small
class DescribeSectionFor:
    @pytest.mark.parametrize(
        ('subject', 'body', 'section'),
        [
            ('feat: add a thing', '', 'Feature'),
            ('feat(config): add a thing', '', 'Feature'),
            ('fix: repair', '', 'Fix'),
            ('chore: tidy', '', 'Fix'),
            ('docs: reword', '', 'Fix'),
            ('refactor(core): split', '', 'Fix'),
            ('feat!: drop an option', '', 'Upgrade notes'),
            ('fix(api)!: change a default', '', 'Upgrade notes'),
            ('fix: change a default', 'BREAKING CHANGE: the default moved', 'Upgrade notes'),
            ('fix: change a default', 'Why.\n\nBREAKING-CHANGE: the default moved', 'Upgrade notes'),
        ],
    )
    def it_puts_every_commit_under_a_gated_heading(self, subject: str, body: str, section: str) -> None:
        assert prepare.section_for(_commit(subject, body)) == section

    @pytest.mark.parametrize('subject', ['Merge branch x', 'bump: version 1.0.0 -> 1.0.1', 'wip stuff', ''])
    def it_skips_commits_that_are_not_conventional_or_are_version_bumps(self, subject: str) -> None:
        assert prepare.section_for(_commit(subject)) is None


@pytest.mark.small
class DescribeRenderEntry:
    def it_starts_with_the_version_heading_and_date(self) -> None:
        assert _entry(_commit('fix: a')).startswith('## v1.15.0 (2026-11-20)\n\n')

    def it_uses_the_exact_prerelease_version_in_the_heading(self) -> None:
        assert _entry(_commit('fix: a'), version='1.15.0b0').startswith('## v1.15.0b0 (2026-11-20)\n')

    def it_has_a_summary_placeholder_before_the_first_section(self) -> None:
        entry = _entry(_commit('fix: a'))

        summary = entry.split('\n\n')[1]
        assert summary.startswith('**') + summary.endswith('**') == 2
        assert entry.index(summary) < entry.index('### ')

    def it_lists_all_five_headings_in_order(self) -> None:
        entry = _entry(_commit('fix: a'))

        headings = [line for line in entry.splitlines() if line.startswith('### ')]
        assert headings == SECTION_HEADINGS

    def it_puts_a_feature_commit_in_the_feature_section_as_a_list_item(self) -> None:
        entry = _entry(_commit('feat: add a thing'))

        feature = entry.split('### Feature\n')[1].split('### Fix')[0]
        assert feature.strip().startswith('- ')
        assert '`feat: add a thing`' in feature

    def it_puts_a_breaking_commit_in_upgrade_notes(self) -> None:
        entry = _entry(_commit('feat!: drop it'))

        upgrade = entry.split('### Upgrade notes\n')[1].split('### Feature')[0]
        assert '`feat!: drop it`' in upgrade

    def it_puts_a_chore_commit_in_fix_not_internal(self) -> None:
        entry = _entry(_commit('chore: tidy'))

        fix = entry.split('### Fix\n')[1].split('### Internal')[0]
        internal = entry.split('### Internal\n')[1].split('### Documentation')[0]
        assert '`chore: tidy`' in fix
        assert internal.strip() == ''

    def it_names_each_commit_by_its_short_sha(self) -> None:
        assert '(1111111)' in _entry(_commit('fix: a', sha='1111111aaaaaaa'))

    def it_wraps_every_line_at_120_characters_with_indented_continuations(self) -> None:
        entry = _entry(_commit('fix: ' + 'word ' * 60))

        lines = entry.splitlines()
        bullet_at = next(i for i, line in enumerate(lines) if line.startswith('- '))
        assert max(len(line) for line in lines) <= 120
        assert lines[bullet_at + 1].startswith('  ')

    def it_sanitizes_line_breaks_and_control_characters_in_a_subject(self) -> None:
        entry = _entry(_commit('fix: a\u2028b\x0cc\x85d'))

        assert '`fix: a b c d`' in entry

    def it_widens_the_code_span_around_a_subject_that_has_backticks(self) -> None:
        entry = _entry(_commit('fix: handle `x` and ``y``'))

        assert '``` fix: handle `x` and ``y`` ```' in ' '.join(entry.split())


@pytest.mark.small
class DescribeInsertEntry:
    def it_places_the_entry_above_the_newest_version_heading(self) -> None:
        entry = _entry(_commit('fix: a'))

        changelog = prepare.insert_entry(CHANGELOG, entry)

        assert changelog.index('## v1.15.0') < changelog.index('## v1.14.3')
        assert changelog.index('Intro.') < changelog.index('## v1.15.0')

    def it_keeps_one_blank_line_between_the_entry_and_the_next_heading(self) -> None:
        changelog = prepare.insert_entry(CHANGELOG, _entry(_commit('fix: a')))

        assert '\n\n## v1.14.3 (2026-11-16)' in changelog
        assert '\n\n\n## v1.14.3' not in changelog

    def it_leaves_the_rest_of_the_changelog_unchanged(self) -> None:
        changelog = prepare.insert_entry(CHANGELOG, _entry(_commit('fix: a')))

        assert changelog.endswith(CHANGELOG[CHANGELOG.index('## v1.14.3') :])
        assert changelog.startswith(CHANGELOG[: CHANGELOG.index('## v1.14.3')])

    def it_ignores_a_version_heading_inside_a_code_fence(self) -> None:
        changelog = '# Changelog\n\n```\n## v9.9.9\n```\n\n## v1.14.3 (2026-11-16)\n\nOld.\n'

        inserted = prepare.insert_entry(changelog, _entry(_commit('fix: a')))

        assert inserted.index('## v1.15.0') > inserted.index('```\n\n')
        assert inserted.index('## v1.15.0') < inserted.index('## v1.14.3')

    def it_refuses_a_changelog_whose_topmost_entry_is_not_a_version(self) -> None:
        with pytest.raises(prepare.ReleaseRefusedError, match='Unreleased'):
            prepare.insert_entry('# Changelog\n\n## Unreleased\n\nx\n\n## v1.0.0\n', _entry(_commit('fix: a')))


@pytest.mark.medium
class DescribePlaceholdersFailTheDocsGate:
    def it_fails_for_each_kind_of_commit(self, tmp_path: Path) -> None:
        entry = _entry(_commit('feat: a'), _commit('fix: b'), _commit('feat!: c'))

        problems = _gate_problems(tmp_path, entry)

        assert len(problems) == 3

    def it_fails_for_a_range_of_only_chore_and_docs_commits(self, tmp_path: Path) -> None:
        problems = _gate_problems(tmp_path, _entry(_commit('chore: tidy'), _commit('docs: reword')))

        assert len(problems) == 2

    @pytest.mark.parametrize(
        'subject',
        [
            'fix: tweak (no docs: because I said so)',
            'fix: see [docs](https://pytest-gremlins.readthedocs.io/en/latest/guide/configuration/#batch-size)',
            'fix: see [docs](guide/configuration.md#batch-size) and docs/guide/configuration.md',
            'fix: ' + 'word ' * 30 + '(no docs: split across wrapped lines)',
        ],
    )
    def it_fails_even_when_the_subject_looks_like_a_docs_reference_or_exemption(
        self, tmp_path: Path, subject: str
    ) -> None:
        problems = _gate_problems(tmp_path, _entry(_commit(subject)))

        assert len(problems) == 1

    def it_fails_when_a_subject_closes_a_code_span_early(self, tmp_path: Path) -> None:
        problems = _gate_problems(tmp_path, _entry(_commit('fix: a` (no docs: sneaky) `b')))

        assert len(problems) == 1


LOG_FORMAT = '--format=%H%x1f%s%x1f%b%x1e'
LOG_RECORD = 'aaa1111bbb\x1ffeat: add a thing\x1f\x1e'
NO_REFERENCE = prepare.CommandResult(returncode=1, stdout='', stderr='')


def _ok(stdout: str = '') -> Any:
    return prepare.CommandResult(returncode=0, stdout=stdout, stderr='')


def _fail(returncode: int, stderr: str = 'boom') -> Any:
    return prepare.CommandResult(returncode=returncode, stdout='', stderr=stderr)


class FakeShell:
    """Answers each command from a table of exact argument tuples and records the calls."""

    def __init__(self, answers: dict[tuple[str, ...], Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: Sequence[str]) -> Any:
        self.calls.append(tuple(args))
        return self.answers[tuple(args)]

    def ran(self, *prefix: str) -> bool:
        return any(call[: len(prefix)] == prefix for call in self.calls)


def _cz(*args: str) -> tuple[str, ...]:
    return (*prepare.CZ, 'bump', *args)


def _shell(
    *,
    branch: Any = None,
    status: Any = None,
    heads: Any = None,
    next_version: Any = None,
    local_branch: Any = NO_REFERENCE,
    remote_branch: Any = None,
    flags: tuple[str, ...] = (),
    release_branch: str = 'release/v1.15.0',
) -> FakeShell:
    return FakeShell(
        {
            ('git', 'symbolic-ref', '--short', '-q', 'HEAD'): branch or _ok('issue-1-x\n'),
            ('git', 'status', '--porcelain'): status or _ok(),
            ('git', 'rev-parse', 'HEAD', 'origin/main'): heads or _ok('abc\nabc\n'),
            _cz('--get-next', *flags): next_version or _ok('1.15.0\n'),
            ('git', 'rev-parse', '--verify', '--quiet', f'refs/heads/{release_branch}'): local_branch,
            ('git', 'ls-remote', '--exit-code', '--heads', 'origin', release_branch): remote_branch or _fail(2, ''),
            ('git', 'describe', '--tags', '--abbrev=0', '--match', 'v*'): _ok('v1.14.3\n'),
            ('git', 'log', 'v1.14.3..HEAD', LOG_FORMAT): _ok(LOG_RECORD),
            ('git', 'switch', '-c', release_branch): _ok(),
            _cz('--files-only', '--yes', *flags): _ok(),
        }
    )


def _repo(tmp_path: Path, *, project: str = '1.15.0', module: str = '1.15.0') -> Path:
    (tmp_path / 'src' / 'pytest_gremlins').mkdir(parents=True)
    (tmp_path / 'pyproject.toml').write_text(f'[project]\nname = "x"\nversion = "{project}"\n', encoding='utf-8')
    (tmp_path / 'src' / 'pytest_gremlins' / '__init__.py').write_text(f"__version__ = '{module}'\n", encoding='utf-8')
    (tmp_path / 'CHANGELOG.md').write_text(CHANGELOG, encoding='utf-8')
    return tmp_path


def _prepare(repo: Path, shell: FakeShell, **options: str | None) -> Any:
    return prepare.prepare_release(
        repo=repo,
        increment=options.get('increment'),
        prerelease=options.get('prerelease'),
        run=shell,
        today=RELEASE_DATE,
    )


@pytest.mark.medium
class DescribePrepareRelease:
    def it_creates_the_branch_bumps_the_files_and_writes_the_entry(self, tmp_path: Path) -> None:
        shell = _shell()

        release = _prepare(_repo(tmp_path), shell)

        assert (release.version, release.branch) == ('1.15.0', 'release/v1.15.0')
        assert shell.ran('git', 'switch', '-c', 'release/v1.15.0')
        assert (tmp_path / 'CHANGELOG.md').read_text(encoding='utf-8').startswith('# Changelog\n\nIntro.')
        assert '## v1.15.0 (2026-11-20)' in (tmp_path / 'CHANGELOG.md').read_text(encoding='utf-8')

    def it_never_commits_tags_or_pushes(self, tmp_path: Path) -> None:
        shell = _shell()

        _prepare(_repo(tmp_path), shell)

        assert not any(call[:2] in {('git', 'commit'), ('git', 'tag'), ('git', 'push')} for call in shell.calls)

    def it_passes_increment_and_prerelease_identically_to_get_next_and_files_only(self, tmp_path: Path) -> None:
        flags = ('--increment', 'MINOR', '--prerelease', 'beta')
        shell = _shell(flags=flags, next_version=_ok('1.15.0b0\n'), release_branch='release/v1.15.0b0')
        repo = _repo(tmp_path, project='1.15.0b0', module='1.15.0b0')

        release = _prepare(repo, shell, increment='minor', prerelease='beta')

        assert release.branch == 'release/v1.15.0b0'
        assert _cz('--get-next', *flags) in shell.calls
        assert _cz('--files-only', '--yes', *flags) in shell.calls

    def it_passes_no_flags_when_none_are_given(self, tmp_path: Path) -> None:
        shell = _shell()

        _prepare(_repo(tmp_path), shell)

        assert _cz('--get-next') in shell.calls
        assert _cz('--files-only', '--yes') in shell.calls

    def it_accepts_a_detached_head(self, tmp_path: Path) -> None:
        shell = _shell(branch=_fail(1, ''))

        release = _prepare(_repo(tmp_path), shell)

        assert release.branch == 'release/v1.15.0'

    @pytest.mark.parametrize(
        ('answers', 'message'),
        [
            ({'branch': _ok('main\n')}, 'main'),
            ({'status': _ok(' M pyproject.toml\n')}, 'uncommitted'),
            ({'heads': _ok('abc\ndef\n')}, 'not origin/main'),
            ({'heads': _fail(128, 'no origin/main')}, 'cannot resolve'),
            ({'local_branch': _ok('abc\n')}, 'already exists locally'),
            ({'remote_branch': _ok('abc\trefs/heads/release/v1.15.0\n')}, 'already exists on origin'),
            ({'remote_branch': _fail(128, 'no remote')}, 'origin'),
            ({'next_version': _fail(21, '[NO_COMMITS_TO_BUMP]')}, 'no commit'),
            ({'next_version': _fail(3, '[NO_COMMITS_FOUND]')}, 'no commit'),
            ({'next_version': _fail(1, 'weird')}, 'weird'),
        ],
    )
    def it_refuses_before_changing_anything(self, tmp_path: Path, answers: dict[str, Any], message: str) -> None:
        shell = _shell(**answers)

        with pytest.raises(prepare.ReleaseRefusedError, match=message):
            _prepare(_repo(tmp_path), shell)

        assert not shell.ran('git', 'switch')
        assert not any('--files-only' in call for call in shell.calls)
        assert (tmp_path / 'CHANGELOG.md').read_text(encoding='utf-8') == CHANGELOG

    @pytest.mark.parametrize(('project', 'module'), [('1.14.3', '1.15.0'), ('1.15.0', '1.14.3'), ('1.16.0', '1.16.0')])
    def it_fails_loudly_when_the_bumped_files_disagree_with_the_computed_version(
        self, tmp_path: Path, project: str, module: str
    ) -> None:
        shell = _shell()

        with pytest.raises(prepare.ReleaseRefusedError, match=r'1\.15\.0'):
            _prepare(_repo(tmp_path, project=project, module=module), shell)

        assert (tmp_path / 'CHANGELOG.md').read_text(encoding='utf-8') == CHANGELOG

    def it_uses_every_commit_when_there_is_no_tag(self, tmp_path: Path) -> None:
        shell = _shell()
        shell.answers[('git', 'describe', '--tags', '--abbrev=0', '--match', 'v*')] = _fail(128)
        shell.answers[('git', 'log', LOG_FORMAT)] = _ok(LOG_RECORD)

        _prepare(_repo(tmp_path), shell)

        assert ('git', 'log', LOG_FORMAT) in shell.calls


@pytest.mark.medium
class DescribeFailureAfterTheBranchExists:
    def it_refuses_an_unplaceable_changelog_before_creating_the_branch(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo / 'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n\nx\n\n## v1.0.0\n', encoding='utf-8')
        shell = _shell()

        with pytest.raises(prepare.ReleaseRefusedError, match='Unreleased'):
            _prepare(repo, shell)

        assert not shell.ran('git', 'switch')

    def it_gives_the_undo_hint_when_the_bumped_versions_disagree(self, tmp_path: Path) -> None:
        with pytest.raises(prepare.ReleaseRefusedError, match='Undo with'):
            _prepare(_repo(tmp_path, project='1.14.3'), _shell())

    def it_preserves_crlf_line_endings_in_the_changelog(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        (repo / 'CHANGELOG.md').write_bytes(CHANGELOG.replace('\n', '\r\n').encode())

        _prepare(repo, _shell())

        written = (repo / 'CHANGELOG.md').read_bytes()
        assert b'\r\n' in written
        assert written.count(b'\n') == written.count(b'\r\n')


def _main_with(shell: FakeShell, repo: Path, *argv: str) -> int:
    return int(prepare.main(list(argv), repo=repo, run=shell, today=RELEASE_DATE))


@pytest.mark.medium
class DescribeMain:
    def it_prints_the_next_steps_and_returns_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = _main_with(_shell(), _repo(tmp_path))

        out = capsys.readouterr().out
        assert code == 0
        assert 'release/v1.15.0' in out
        assert 'git commit -S' in out
        assert 'cache kept' in out
        assert 'git push' in out

    def it_returns_one_and_explains_a_refusal_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _main_with(_shell(branch=_ok('main\n')), _repo(tmp_path))

        captured = capsys.readouterr()
        assert code == 1
        assert 'main' in captured.err
        assert captured.out == ''

    def it_accepts_lowercase_increments(self, tmp_path: Path) -> None:
        shell = _shell(flags=('--increment', 'MAJOR'))

        assert _main_with(shell, _repo(tmp_path), '--increment', 'major') == 0

    @pytest.mark.parametrize('argv', [['--prerelease', 'gamma'], ['--increment', 'HUGE']])
    def it_rejects_values_outside_the_allowed_choices(self, tmp_path: Path, argv: list[str]) -> None:
        with pytest.raises(SystemExit) as exit_info:
            _main_with(_shell(), _repo(tmp_path), *argv)

        assert exit_info.value.code == 2


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S607
    return completed.stdout


def _real_repo(tmp_path: Path) -> Path:
    origin = tmp_path / 'origin.git'
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(origin)], check=True)  # noqa: S607
    _git(repo, 'init', '-q', '-b', 'main')
    for key, value in [
        ('user.name', 'T'),
        ('user.email', 't@example.com'),
        ('commit.gpgsign', 'false'),
        ('tag.gpgsign', 'false'),
    ]:
        _git(repo, 'config', key, value)
    _git(repo, 'remote', 'add', 'origin', str(origin))
    (repo / 'src' / 'pytest_gremlins').mkdir(parents=True)
    (repo / 'pyproject.toml').write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n\n[tool.commitizen]\nname = "cz_conventional_commits"\n'
        'version_provider = "pep621"\nversion_files = ["src/pytest_gremlins/__init__.py:__version__"]\n'
        'tag_format = "v$version"\nannotated_tag = true\n',
        encoding='utf-8',
    )
    (repo / 'src' / 'pytest_gremlins' / '__init__.py').write_text("__version__ = '1.0.0'\n", encoding='utf-8')
    (repo / 'CHANGELOG.md').write_text('# Changelog\n\n## v1.0.0 (2026-01-01)\n\nFirst.\n', encoding='utf-8')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-q', '-m', 'feat: first')
    _git(repo, 'tag', '-a', 'v1.0.0', '-m', 'v1.0.0')
    _git(repo, 'push', '-q', 'origin', 'main')
    (repo / 'NEW.md').write_text('new\n', encoding='utf-8')
    _git(repo, 'add', 'NEW.md')
    _git(repo, 'commit', '-q', '-m', 'feat: add a thing (#7)')
    _git(repo, 'push', '-q', 'origin', 'main')
    _git(repo, 'switch', '-q', '-c', 'work')
    return repo


@pytest.mark.medium
class DescribeRealRepository:
    def it_builds_a_branch_that_passes_the_release_pull_request_guard(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
        monkeypatch.setenv('GIT_CONFIG_SYSTEM', '/dev/null')
        repo = _real_repo(tmp_path)

        code = prepare.main(['--prerelease', 'beta'], repo=repo)

        assert code == 0, capsys.readouterr().err
        assert _git(repo, 'branch', '--show-current').strip() == 'release/v1.1.0b0'
        changed = sorted(line[3:] for line in _git(repo, 'status', '--porcelain').splitlines())
        assert changed == ['CHANGELOG.md', 'pyproject.toml', 'src/pytest_gremlins/__init__.py']
        assert _git(repo, 'tag', '--list').split() == ['v1.0.0']
        assert _git(repo, 'log', '--oneline', 'origin/main..HEAD') == ''
        assert '`feat: add a thing (#7)`' in ' '.join((repo / 'CHANGELOG.md').read_text(encoding='utf-8').split())
        _git(repo, 'add', '-u')
        _git(repo, 'commit', '-q', '-m', 'bump: release')
        guard_exit = version_guard.main(
            ['--branch', 'release/v1.1.0b0', '--base-ref', 'origin/main', '--repo', str(repo)]
        )
        assert guard_exit == 0


@pytest.mark.medium
class DescribeAdversarialEntryGate:
    @pytest.mark.parametrize('subject', ['fix:repair the parser', 'feat:add a thing', 'Revert "feat: add a thing"'])
    def it_leaves_an_entry_that_fails_the_docs_gate_for_a_bump_eligible_or_forced_commit(
        self, tmp_path: Path, subject: str
    ) -> None:
        problems = _gate_problems(tmp_path, _entry(_commit(subject)))

        assert problems != []


@pytest.mark.medium
class DescribeAdversarialUndoHint:
    def it_gives_an_undo_hint_that_works_from_a_detached_head(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
        monkeypatch.setenv('GIT_CONFIG_SYSTEM', '/dev/null')
        repo = _real_repo(tmp_path)
        _git(repo, 'switch', '-q', '--detach', 'main')
        _git(repo, 'switch', '-q', '-c', 'release/v1.1.0')

        undo = subprocess.run(  # noqa: S602
            f'{prepare.UNDO_HINT}release/v1.1.0', shell=True, cwd=repo, capture_output=True, text=True, check=False
        )

        assert undo.returncode == 0, undo.stderr

    def it_gives_the_undo_hint_when_the_changelog_cannot_be_written(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        shell = _shell()
        changelog = repo / 'CHANGELOG.md'

        def run(args: Sequence[str]) -> Any:
            if tuple(args) == _cz('--files-only', '--yes'):
                changelog.chmod(0o444)
            return shell(args)

        with pytest.raises(prepare.ReleaseRefusedError, match='Undo with'):
            _prepare(repo, run)  # type: ignore[arg-type]


@pytest.mark.medium
class DescribeAdversarialWorkBranchStart:
    def it_refuses_a_work_branch_that_has_commits_origin_main_lacks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
        monkeypatch.setenv('GIT_CONFIG_SYSTEM', '/dev/null')
        repo = _real_repo(tmp_path)
        (repo / 'src' / 'pytest_gremlins' / 'work.py').write_text('X = 1\n', encoding='utf-8')
        _git(repo, 'add', '.')
        _git(repo, 'commit', '-q', '-m', 'fix: unmerged work')

        code = prepare.main([], repo=repo)

        assert code == 1
        assert 'git switch --detach origin/main' in capsys.readouterr().err
        assert _git(repo, 'branch', '--show-current').strip() == 'work'


@pytest.mark.medium
class DescribeAdversarialCommitizenBumpParity:
    @pytest.mark.parametrize(
        ('subject', 'body', 'section'),
        [
            ('BREAKING CHANGE: drop Python 3.10', '', 'Upgrade notes'),
            ('Update the parser', 'BREAKING CHANGE: the default moved', 'Upgrade notes'),
            ('Update the parser', 'fix: repair the parser', 'Fix'),
            ('fix(a(b)): repair', '', 'Fix'),
            ('fix:', '', 'Fix'),
        ],
    )
    def it_gives_a_placeholder_to_every_commit_that_commitizen_counts_toward_the_bump(
        self, subject: str, body: str, section: str
    ) -> None:
        assert prepare.section_for(_commit(subject, body)) == section


@pytest.mark.small
class DescribeForcedMajorFallback:
    def it_puts_the_generic_placeholder_under_upgrade_notes_for_a_forced_major_increment(self) -> None:
        entry = prepare.render_entry('2.0.0', RELEASE_DATE, [_commit('Revert "x"')], increment='MAJOR')

        upgrade_notes = entry.split('### Upgrade notes')[1].split('### Feature')[0]
        assert 'TODO: describe this change for users' in upgrade_notes
