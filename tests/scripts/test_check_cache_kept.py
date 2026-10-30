"""Tests for scripts/check_cache_kept.py -- the release gate on verdict code changes without a cache bump (#877)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest
import yaml

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
    checker = _load('check_cache_kept')
finally:
    sys.path.remove(str(SCRIPTS))

PREVIOUS = checker.Markers(cache_version='3', runner_fidelity_version='rf21')
CHANGED = ['src/pytest_gremlins/cache/key.py', 'src/pytest_gremlins/plugin.py']


def _entry(preamble: str = '', body: str = '### Fix\n\n- **A fix.** (no docs: test)\n') -> str:
    return f'# Changelog\n\n## v1.14.0 (2026-11-01)\n\n{preamble}\n{body}\n## v1.13.1 (2026-10-28)\n\nOld.\n'


@pytest.mark.small
class DescribeCheckCacheKept:
    def it_passes_when_no_guarded_file_changed(self) -> None:
        assert checker.check_cache_kept([], PREVIOUS, PREVIOUS, preamble='') == []

    def it_fails_naming_the_changed_files_when_nothing_was_raised_and_no_line_exists(self) -> None:
        problems = checker.check_cache_kept(CHANGED, PREVIOUS, PREVIOUS, preamble='Prose.\n')

        assert len(problems) == 1
        assert all(path in problems[0] for path in CHANGED)
        assert '(cache kept: <reason>)' in problems[0]

    @pytest.mark.parametrize(
        'head',
        [
            checker.Markers(cache_version='4', runner_fidelity_version='rf21'),
            checker.Markers(cache_version='3', runner_fidelity_version='rf22'),
        ],
    )
    def it_passes_when_either_marker_was_raised(self, head: object) -> None:
        assert checker.check_cache_kept(CHANGED, PREVIOUS, head, preamble='') == []

    def it_passes_when_a_reason_is_given(self) -> None:
        preamble = 'Intro.\n\n(cache kept: only log wording changed)\n'

        assert checker.check_cache_kept(CHANGED, PREVIOUS, PREVIOUS, preamble=preamble) == []

    @pytest.mark.parametrize('line', ['(cache kept:)', '(cache kept:    )', '(cache kept: \t)'])
    def it_fails_when_the_reason_is_empty(self, line: str) -> None:
        problems = checker.check_cache_kept(CHANGED, PREVIOUS, PREVIOUS, preamble=f'{line}\n')

        assert len(problems) == 1
        assert 'empty' in problems[0]

    def it_passes_when_one_of_two_lines_has_a_reason(self) -> None:
        preamble = '(cache kept:)\n(cache kept: logging only)\n'

        assert checker.check_cache_kept(CHANGED, PREVIOUS, PREVIOUS, preamble=preamble) == []

    def it_keeps_a_reason_that_contains_parentheses(self) -> None:
        preamble = '(cache kept: renames only (no behavior change))\n'

        assert checker.check_cache_kept(CHANGED, PREVIOUS, PREVIOUS, preamble=preamble) == []


@pytest.mark.small
class DescribeEntryPreamble:
    def it_returns_the_prose_before_the_first_section_heading(self) -> None:
        changelog = _entry(preamble='Summary.\n\n(cache kept: logging only)\n')

        preamble = docs_gate.entry_preamble(changelog, '1.14.0')

        assert preamble is not None
        assert '(cache kept: logging only)' in preamble
        assert 'A fix.' not in preamble

    def it_returns_nothing_for_a_missing_entry(self) -> None:
        assert docs_gate.entry_preamble(_entry(), '9.9.9') is None

    def it_ignores_html_comments(self) -> None:
        changelog = _entry(preamble='<!-- (cache kept: hidden) -->\n')

        assert '(cache kept' not in (docs_gate.entry_preamble(changelog, '1.14.0') or '')

    def it_ignores_fenced_code(self) -> None:
        changelog = _entry(preamble='```\n(cache kept: fenced)\n```\n')

        assert '(cache kept' not in (docs_gate.entry_preamble(changelog, '1.14.0') or '')

    def it_ignores_code_spans(self) -> None:
        changelog = _entry(preamble='Write `(cache kept: <reason>)` to keep it.\n')

        assert checker.cache_kept_reasons(docs_gate.entry_preamble(changelog, '1.14.0') or '') == []

    def it_does_not_accept_the_line_under_a_section(self) -> None:
        changelog = _entry(body='### Fix\n\n- **A fix.** (no docs: x) (cache kept: wrong place)\n')

        assert checker.cache_kept_reasons(docs_gate.entry_preamble(changelog, '1.14.0') or '') == []

    def it_leaves_the_docs_gate_passing_when_the_line_is_in_the_prose(self) -> None:
        changelog = _entry(preamble='(cache kept: logging only)\n')

        class _NoSite:
            def anchors_of(self, page: str) -> frozenset[str] | None:  # noqa: ARG002
                return None

        assert docs_gate.find_problems(changelog, '1.14.0', _NoSite()) == []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [checker.GIT, '-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false', *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / 'work'
    work.mkdir()
    _git(work, 'init', '-q')
    (work / 'f.txt').write_text('a\n', encoding='utf-8')
    _git(work, 'add', '.')
    _git(work, 'commit', '-q', '-m', 'one')
    _git(work, 'tag', 'v1.0.0')
    (work / 'f.txt').write_text('b\n', encoding='utf-8')
    _git(work, 'commit', '-q', '-am', 'two')
    _git(work, 'tag', 'v1.1.0')
    return work


@pytest.mark.medium
class DescribePreviousReleaseTag:
    def it_finds_the_newest_release_tag_reachable_from_head(self, repo: Path) -> None:
        assert checker.previous_release_tag('1.2.0', repo) == 'v1.1.0'

    def it_does_not_count_the_tag_being_released(self, repo: Path) -> None:
        assert checker.previous_release_tag('1.1.0', repo) == 'v1.0.0'

    def it_accepts_a_version_with_a_leading_v(self, repo: Path) -> None:
        assert checker.previous_release_tag('v1.1.0', repo) == 'v1.0.0'

    def it_returns_nothing_without_an_earlier_release_tag(self, repo: Path) -> None:
        _git(repo, 'tag', '-d', 'v1.0.0')

        assert checker.previous_release_tag('1.1.0', repo) is None


class _Git:
    """Stand-ins for the git-reading helpers, so main() runs without a repository."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, *, changed: list[str], head: object, tag: str | None = 'v1.13.1'
    ) -> None:
        monkeypatch.setattr(checker, 'previous_release_tag', lambda *_: tag)
        monkeypatch.setattr(checker, 'released_markers', lambda *_: PREVIOUS)
        monkeypatch.setattr(checker, '_changed_guarded_files', lambda *_: changed)
        monkeypatch.setattr(checker, '_head_markers', lambda: head)


@pytest.fixture
def changelog(tmp_path: Path) -> Path:
    path = tmp_path / 'CHANGELOG.md'
    path.write_text(_entry(), encoding='utf-8')
    return path


@pytest.mark.medium
class DescribeMain:
    def it_exits_1_and_names_the_files_when_guarded_code_changed_without_a_marker(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _Git(monkeypatch, changed=CHANGED, head=PREVIOUS)

        assert checker.main(['--newest', '--changelog', str(changelog)]) == 1
        assert CHANGED[0] in capsys.readouterr().out

    def it_exits_0_when_a_marker_was_raised(self, monkeypatch: pytest.MonkeyPatch, changelog: Path) -> None:
        _Git(monkeypatch, changed=CHANGED, head=checker.Markers(cache_version='4', runner_fidelity_version='rf21'))

        assert checker.main(['1.14.0', '--changelog', str(changelog)]) == 0

    def it_exits_0_when_the_entry_states_a_reason(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _Git(monkeypatch, changed=CHANGED, head=PREVIOUS)
        path = tmp_path / 'CHANGELOG.md'
        path.write_text(_entry(preamble='(cache kept: logging only)\n'), encoding='utf-8')

        assert checker.main(['--newest', '--changelog', str(path)]) == 0

    def it_exits_0_without_a_changelog_entry_when_no_guarded_code_changed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _Git(monkeypatch, changed=[], head=PREVIOUS)
        path = tmp_path / 'CHANGELOG.md'
        path.write_text(_entry(), encoding='utf-8')

        assert checker.main(['1.14.0', '--changelog', str(path)]) == 0

    def it_exits_2_when_there_is_no_previous_release_tag(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _Git(monkeypatch, changed=CHANGED, head=PREVIOUS, tag=None)

        assert checker.main(['--newest', '--changelog', str(changelog)]) == 2

    def it_exits_2_when_the_entry_is_missing_and_a_line_is_needed(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _Git(monkeypatch, changed=CHANGED, head=PREVIOUS)

        assert checker.main(['9.9.9', '--changelog', str(changelog)]) == 2

    @pytest.mark.parametrize('flag', ['--skip', '--force', '--bypass', '--no-check'])
    def it_has_no_flag_that_skips_the_check(self, flag: str) -> None:
        with pytest.raises(SystemExit):
            checker.main(['--newest', flag])


WORKFLOWS = Path(__file__).resolve().parents[2] / '.github' / 'workflows'
GATE = 'check_cache_kept.py'


def _steps(workflow: str, job: str) -> list[dict[str, object]]:
    jobs = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding='utf-8'))['jobs']
    steps: list[dict[str, object]] = jobs[job]['steps']
    return steps


def _gate_step(workflow: str, job: str) -> dict[str, object]:
    return next(step for step in _steps(workflow, job) if GATE in str(step.get('run', '')))


def _index(workflow: str, job: str, text: str) -> int:
    return next(i for i, step in enumerate(_steps(workflow, job)) if text in str(step.get('run', '')))


@pytest.mark.medium
class DescribeWorkflowGate:
    @pytest.mark.parametrize(
        ('workflow', 'job'),
        [('ci.yml', 'docs'), ('cut-release.yml', 'cut-release'), ('release.yml', 'verify-tag')],
    )
    def it_never_skips_or_tolerates_failure_of_the_check(self, workflow: str, job: str) -> None:
        step = _gate_step(workflow, job)

        assert 'if' not in step or workflow == 'ci.yml'
        assert 'continue-on-error' not in step

    def it_runs_in_the_changelog_pr_check_when_the_changelog_changes(self) -> None:
        step = _gate_step('ci.yml', 'docs')

        assert step['if'] == "needs.changes.outputs.changelog == 'true'"
        assert '--newest' in str(step['run'])

    def it_fetches_tags_in_the_changelog_pr_check(self) -> None:
        checkout = _steps('ci.yml', 'docs')[0]

        assert checkout['with'] == {'fetch-depth': 0}

    def it_checks_the_version_commitizen_will_bump_to_before_the_version_is_bumped(self) -> None:
        step = _gate_step('cut-release.yml', 'cut-release')

        assert 'cz bump --get-next' in str(step['run'])
        assert _index('cut-release.yml', 'cut-release', GATE) < _index(
            'cut-release.yml', 'cut-release', 'cz bump --yes'
        )

    def it_checks_the_tag_being_released_after_checking_it_out(self) -> None:
        checkout = _index('release.yml', 'verify-tag', 'git checkout --detach "refs/tags/$RELEASE_TAG"')

        assert checkout < _index('release.yml', 'verify-tag', GATE)

    def it_runs_in_the_project_environment_so_the_guard_can_import_the_package(self) -> None:
        run = str(_gate_step('release.yml', 'verify-tag')['run'])

        assert '--no-project' not in run
        assert '"$RELEASE_TAG"' in run
