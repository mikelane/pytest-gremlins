"""Tests for scripts/check_cache_bump.py -- the release gate on a changed cache marker without a minor bump (#1036)."""

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
    checker = _load('check_cache_bump')
finally:
    sys.path.remove(str(SCRIPTS))


def _entry(upgrade_notes: str = '', fix: str = '- **A fix.** (no docs: test)\n') -> str:
    return (
        '# Changelog\n\n## v1.15.0 (2026-11-22)\n\nSummary.\n\n'
        f'### Upgrade notes\n\n{upgrade_notes}\n### Fix\n\n{fix}\n## v1.14.3 (2026-11-16)\n\nOld.\n'
    )


@pytest.mark.small
class DescribeUpgradeNoteBullets:
    def it_returns_each_bullet_under_upgrade_notes_with_its_continuation_lines_joined(self) -> None:
        changelog = _entry(upgrade_notes='- **First.** One\n  and two. (no docs: x)\n- **Second.** (no docs: y)\n')

        assert docs_gate.upgrade_note_bullets(changelog, '1.15.0') == [
            '**First.** One and two. (no docs: x)',
            '**Second.** (no docs: y)',
        ]

    def it_leaves_out_bullets_under_other_sections(self) -> None:
        changelog = _entry(upgrade_notes='', fix='- **Only a fix.** (no docs: x)\n')

        assert docs_gate.upgrade_note_bullets(changelog, '1.15.0') == []

    def it_returns_nothing_for_a_missing_entry(self) -> None:
        assert docs_gate.upgrade_note_bullets(_entry(), '9.9.9') is None


PREVIOUS = checker.Markers(cache_version='3', runner_fidelity_version='rf21')
CACHE_RAISED = checker.Markers(cache_version='4', runner_fidelity_version='rf21')
FIDELITY_RAISED = checker.Markers(cache_version='3', runner_fidelity_version='rf22')
REBUILT_BULLET = '**A new cache layout.** The first run after upgrading rebuilds the cache once. (no docs: test)'


@pytest.mark.small
class DescribeIsMinorBump:
    @pytest.mark.parametrize(
        ('previous', 'new'),
        [
            ('1.14.3', '1.15.0'),
            ('1.14.0', '2.0.0'),
            ('1.14.3', '1.15.0b0'),
            ('1.15.0b0', '1.15.0'),
            ('1.15.0b0', '1.15.0b1'),
            ('1.15.0b0', '1.15.1'),
            ('1.15.0rc1', '1.16.0'),
            ('0.9.9', '1.0.0'),
            ('1.9.0', '1.10.0'),
        ],
    )
    def it_accepts_a_version_with_a_higher_minor_or_major(self, previous: str, new: str) -> None:
        assert checker.is_at_least_minor_bump(previous, new) is True

    @pytest.mark.parametrize(
        ('previous', 'new'),
        [
            ('1.14.3', '1.14.4'),
            ('1.14.3', '1.14.4b0'),
            ('1.15.1b0', '1.15.1'),
            ('1.15.0', '1.15.1'),
            ('1.15.0', '1.14.9'),
            ('1.15.0', '1.15.0'),
            ('2.0.0', '1.99.0'),
            ('1.15.0b0', '1.14.9'),
            ('1.10.0', '1.9.0'),
        ],
    )
    def it_rejects_a_version_that_does_not_raise_the_minor(self, previous: str, new: str) -> None:
        assert checker.is_at_least_minor_bump(previous, new) is False

    @pytest.mark.parametrize(
        ('previous', 'new'),
        [
            ('1.15.0.post1', '1.15.1'),
            ('1.15.0+local', '1.15.1'),
            ('1.15.0.post1.dev2', '1.15.1'),
        ],
    )
    def it_rejects_a_patch_over_a_post_or_local_release_of_x_y_0(self, previous: str, new: str) -> None:
        assert checker.is_at_least_minor_bump(previous, new) is False

    @pytest.mark.parametrize(
        ('previous', 'new'),
        [
            ('1.15.0a1', '1.15.0b0'),
            ('1.15.0rc1', '1.15.0'),
            ('1.15.0.dev3', '1.15.0'),
            ('1.15.0b1.dev2', '1.15.0'),
        ],
    )
    def it_accepts_a_release_on_the_line_of_a_prerelease_or_dev_release_of_x_y_0(self, previous: str, new: str) -> None:
        assert checker.is_at_least_minor_bump(previous, new) is True

    @pytest.mark.parametrize('text', ['', '1.15', 'v1.15.0', 'one.two.three'])
    def it_refuses_a_version_it_cannot_read(self, text: str) -> None:
        with pytest.raises(docs_gate.CannotCheckError):
            checker.is_at_least_minor_bump('1.14.3', text)

    @pytest.mark.parametrize('text', ['', '1.14', 'v1.14.3'])
    def it_refuses_a_previous_version_it_cannot_read(self, text: str) -> None:
        with pytest.raises(docs_gate.CannotCheckError, match=r'X\.Y\.Z'):
            checker.is_at_least_minor_bump(text, '1.15.0')


@pytest.mark.small
class DescribeSaysCacheRebuilt:
    @pytest.mark.parametrize(
        'bullet',
        [
            REBUILT_BULLET,
            'The cache is REBUILT once.',
            'Rebuilding the Cache happens on the first run.',
        ],
    )
    def it_accepts_a_bullet_that_mentions_the_cache_and_a_rebuild(self, bullet: str) -> None:
        assert checker.says_cache_rebuilt(bullet) is True

    @pytest.mark.parametrize(
        'bullet',
        [
            'The cache layout changed.',
            'Everything is rebuilt.',
            '**TODO: describe this change for users.**',
        ],
    )
    def it_rejects_a_bullet_that_lacks_either_word(self, bullet: str) -> None:
        assert checker.says_cache_rebuilt(bullet) is False


@pytest.mark.small
class DescribeHiddenRebuildWording:
    @pytest.mark.parametrize(
        'bullet',
        [
            '- **Faster runs** <a title="the cache is rebuilt once">.</a> (no docs: r)\n',
            '- **Faster runs** ![the cache is rebuilt once](x.png) (no docs: r)\n',
        ],
    )
    def it_fails_a_release_whose_rebuild_wording_the_page_does_not_show(self, bullet: str) -> None:
        bullets = docs_gate.upgrade_note_bullets(_entry(upgrade_notes=bullet), '1.15.0')

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert len(problems) == 1

    def it_accepts_rebuild_wording_that_sits_between_tags(self) -> None:
        bullet = '- **Faster runs** <b>the cache is rebuilt once</b> (no docs: r)\n'
        bullets = docs_gate.upgrade_note_bullets(_entry(upgrade_notes=bullet), '1.15.0')

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert problems == []


@pytest.mark.small
class DescribeImageAltTextTheRendererHides:
    @pytest.mark.parametrize(
        'bullet',
        [
            '- **Faster runs** ![the cache is rebuilt [once]](x.png) (no docs: r)\n',
            "- **Faster runs** ![the cache is rebuilt once](x.png 'title') (no docs: r)\n",
            '- **Faster runs** ![the cache is rebuilt once](x.png (title)) (no docs: r)\n',
            '- **Faster runs** ![the cache is rebuilt once](<a b.png>) (no docs: r)\n',
            '- **Faster runs** \\\\![the cache is rebuilt once](x.png) (no docs: r)\n',
            '- **Faster runs** ![the cache is \\] rebuilt once](x.png) (no docs: r)\n',
        ],
    )
    def it_fails_a_release_whose_rebuild_wording_is_only_in_image_alt_text(self, bullet: str) -> None:
        bullets = docs_gate.upgrade_note_bullets(_entry(upgrade_notes=bullet), '1.15.0')

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert len(problems) == 1


@pytest.mark.small
class DescribeVisibleCodeSpansAndAutolinks:
    @pytest.mark.parametrize(
        'bullet',
        [
            '- **Faster runs** `<b title="the cache is rebuilt once">` (no docs: r)\n',
            '- **Faster runs** `![the cache is rebuilt once](x.png)` (no docs: r)\n',
            '- **Faster runs** <https://example.com/cache-rebuilt-once> (no docs: r)\n',
        ],
    )
    def it_accepts_rebuild_wording_the_page_shows_as_literal_text(self, bullet: str) -> None:
        bullets = docs_gate.upgrade_note_bullets(_entry(upgrade_notes=bullet), '1.15.0')

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert problems == []


@pytest.mark.small
class DescribeAttributeListsTheRendererHides:
    @pytest.mark.parametrize(
        'bullet',
        [
            '- **Upgrade** `CACHE_VERSION`{ title="the cache is rebuilt once" } (no docs: r)\n',
            '- **Faster runs**{ title="the cache is rebuilt once" } (no docs: r)\n',
            '- **Upgrade** first run is slower. (no docs: r)\n  { data-note="the cache is rebuilt once" }\n',
        ],
    )
    def it_fails_a_release_whose_rebuild_wording_is_only_in_an_attr_list_attribute(self, bullet: str) -> None:
        bullets = docs_gate.upgrade_note_bullets(_entry(upgrade_notes=bullet), '1.15.0')

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert len(problems) == 1


@pytest.mark.small
class DescribeLinkReferenceDefinitionsTheRendererHides:
    def it_fails_a_release_whose_rebuild_wording_is_only_in_a_reference_definition_label(self) -> None:
        bullet = '- **Upgrade** first run is slower. (no docs: r)\n  [the cache is rebuilt once]: https://example.com\n'
        bullets = docs_gate.upgrade_note_bullets(_entry(upgrade_notes=bullet), '1.15.0')

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert len(problems) == 1

    def it_fails_a_release_whose_rebuild_wording_is_only_in_an_abbreviation_definition_label(self) -> None:
        bullet = '- **Upgrade** first run is slower. (no docs: r)\n  *[the cache is rebuilt once]: x\n'
        bullets = docs_gate.upgrade_note_bullets(_entry(upgrade_notes=bullet), '1.15.0')

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert len(problems) == 1

    @pytest.mark.parametrize(
        'definition',
        [
            '  [docs]: https://example.com\n  "the cache is rebuilt once"\n',
            "  [docs]: https://example.com\n  'the cache is rebuilt once'\n",
            '  [docs]: https://example.com\n  (the cache is rebuilt once)\n',
            '  [docs]:\n  https://example.com/cache-rebuilt\n',
        ],
    )
    def it_fails_a_release_whose_rebuild_wording_is_only_in_a_definition_continued_on_the_next_line(
        self, definition: str
    ) -> None:
        bullet = f'- **Upgrade** first run is slower. (no docs: r)\n{definition}'
        bullets = docs_gate.upgrade_note_bullets(_entry(upgrade_notes=bullet), '1.15.0')

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert len(problems) == 1


@pytest.mark.small
class DescribeMinorBumpOverCanonicalPrereleases:
    @pytest.mark.parametrize('previous', ['1.15.0rc1.post1', '1.15.0b0+local', '1.15.0a1.post1.dev2'])
    def it_accepts_a_release_on_the_line_of_a_prerelease_that_sorts_before_x_y_0(self, previous: str) -> None:
        assert checker.is_at_least_minor_bump(previous, '1.15.0') is True


@pytest.mark.small
class DescribeChangedMarkers:
    @pytest.mark.parametrize(
        ('head', 'expected'),
        [
            (PREVIOUS, []),
            (CACHE_RAISED, ['CACHE_VERSION']),
            (FIDELITY_RAISED, ['RUNNER_FIDELITY_VERSION']),
            (
                checker.Markers(cache_version='4', runner_fidelity_version='rf22'),
                ['CACHE_VERSION', 'RUNNER_FIDELITY_VERSION'],
            ),
        ],
    )
    def it_names_each_marker_that_differs(self, head: object, expected: list[str]) -> None:
        assert checker.changed_markers(PREVIOUS, head) == expected


@pytest.mark.small
class DescribeCheckCacheBump:
    def it_passes_when_no_marker_changed(self) -> None:
        assert checker.check_cache_bump(PREVIOUS, PREVIOUS, '1.14.3', '1.14.4', bullets=[]) == []

    def it_passes_a_minor_bump_with_a_rebuild_bullet(self) -> None:
        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=[REBUILT_BULLET])

        assert problems == []

    def it_fails_a_patch_bump_naming_the_marker_and_both_versions(self) -> None:
        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.14.4', bullets=[REBUILT_BULLET])

        assert len(problems) == 1
        assert 'CACHE_VERSION' in problems[0]
        assert '1.14.3' in problems[0]
        assert '1.14.4' in problems[0]

    def it_fails_without_a_rebuild_bullet(self) -> None:
        problems = checker.check_cache_bump(PREVIOUS, FIDELITY_RAISED, '1.14.3', '1.15.0', bullets=['Other.'])

        assert len(problems) == 1
        assert '### Upgrade notes' in problems[0]
        assert 'RUNNER_FIDELITY_VERSION' in problems[0]

    def it_reports_both_problems_at_once(self) -> None:
        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.14.4', bullets=[])

        assert len(problems) == 2

    def it_names_both_markers_when_both_changed(self) -> None:
        both = checker.Markers(cache_version='4', runner_fidelity_version='rf22')

        problems = checker.check_cache_bump(PREVIOUS, both, '1.14.3', '1.14.4', bullets=[REBUILT_BULLET])

        assert problems[0].startswith('CACHE_VERSION and RUNNER_FIDELITY_VERSION changed since v1.14.3,')

    def it_passes_a_stable_release_that_follows_its_own_minor_prerelease(self) -> None:
        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.15.0b0', '1.15.0', bullets=[REBUILT_BULLET])

        assert problems == []

    def it_ignores_a_rebuild_bullet_when_no_marker_changed_and_the_release_is_a_patch(self) -> None:
        problems = checker.check_cache_bump(PREVIOUS, PREVIOUS, '1.14.3', '1.14.4', bullets=['Other.'])

        assert problems == []

    def it_passes_when_any_one_bullet_says_the_cache_is_rebuilt(self) -> None:
        bullets = ['**Other.** (no docs: x)', REBUILT_BULLET]

        problems = checker.check_cache_bump(PREVIOUS, CACHE_RAISED, '1.14.3', '1.15.0', bullets=bullets)

        assert problems == []


def _changelog_text(version: str = '1.15.0', upgrade_notes: str = f'- {REBUILT_BULLET}\n') -> str:
    return (
        f'# Changelog\n\n## v{version} (2026-11-22)\n\nSummary.\n\n### Upgrade notes\n\n{upgrade_notes}\n'
        '## v1.14.3 (2026-11-16)\n\n### Fix\n\n- **Old.** (no docs: test)\n'
    )


class _StubbedGitReaders:
    """Stand-ins for the git-reading helpers, so main() runs without a repository."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        head: object,
        tag: str | None = 'v1.14.3',
        tagged: bool = False,
    ) -> None:
        monkeypatch.setattr(checker, 'previous_release_tag', lambda *_: tag)
        monkeypatch.setattr(checker, 'released_markers', lambda *_: PREVIOUS)
        monkeypatch.setattr(checker, '_head_markers', lambda: head)
        monkeypatch.setattr(checker, '_is_tagged', lambda *_: tagged)


@pytest.fixture
def changelog(tmp_path: Path) -> Path:
    path = tmp_path / 'CHANGELOG.md'
    path.write_text(_changelog_text(), encoding='utf-8')
    return path


@pytest.mark.medium
class DescribeMain:
    def it_exits_0_when_no_marker_changed_even_without_a_matching_entry(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=PREVIOUS)

        assert checker.main(['9.9.9', '--changelog', str(changelog)]) == 0

    def it_exits_0_for_a_minor_release_that_explains_the_rebuild(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)

        assert checker.main(['--newest', '--changelog', str(changelog)]) == 0

    def it_exits_1_and_names_the_problem_for_a_patch_release(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)
        path = tmp_path / 'CHANGELOG.md'
        path.write_text(_changelog_text('1.14.4'), encoding='utf-8')

        assert checker.main(['1.14.4', '--changelog', str(path)]) == 1
        assert 'minor bump' in capsys.readouterr().out

    def it_exits_1_when_the_entry_has_no_rebuild_bullet(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=FIDELITY_RAISED)
        path = tmp_path / 'CHANGELOG.md'
        path.write_text(_changelog_text(upgrade_notes='- **Other.** (no docs: test)\n'), encoding='utf-8')

        assert checker.main(['--newest', '--changelog', str(path)]) == 1
        assert '### Upgrade notes' in capsys.readouterr().out

    def it_exits_2_when_there_is_no_previous_release_tag(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED, tag=None)

        assert checker.main(['--newest', '--changelog', str(changelog)]) == 2

    def it_exits_2_when_the_entry_is_missing_and_a_marker_changed(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)

        assert checker.main(['9.9.9', '--changelog', str(changelog)]) == 2

    def it_exits_0_when_the_newest_entry_is_already_released(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED, tagged=True)

        assert checker.main(['--newest', '--changelog', str(changelog)]) == 0

    @pytest.mark.parametrize('flag', ['--skip', '--force', '--bypass', '--no-check'])
    def it_has_no_flag_that_skips_the_check(self, flag: str) -> None:
        with pytest.raises(SystemExit) as raised:
            checker.main(['--newest', flag])

        assert raised.value.code == 2

    @pytest.mark.parametrize('argv', [[], ['1.15.0', '--newest']])
    def it_exits_2_unless_given_exactly_one_of_the_version_and_newest(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit) as raised:
            checker.main(argv)

        assert raised.value.code == 2

    def it_exits_0_for_a_version_given_with_its_leading_v(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)

        assert checker.main(['v1.15.0', '--changelog', str(changelog)]) == 0

    def it_exits_2_for_an_empty_version(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)

        assert checker.main(['v', '--changelog', str(changelog)]) == 2
        assert 'the version is empty' in capsys.readouterr().err

    def it_leaves_out_the_tag_of_the_version_being_released(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)
        asked: list[str | None] = []

        def previous_release_tag(version: str | None) -> str:
            asked.append(version)
            return 'v1.14.3'

        monkeypatch.setattr(checker, 'previous_release_tag', previous_release_tag)

        checker.main(['v1.15.0', '--changelog', str(changelog)])

        assert asked == ['1.15.0']

    def it_counts_every_tag_with_newest(self, monkeypatch: pytest.MonkeyPatch, changelog: Path) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)
        asked: list[str | None] = []

        def previous_release_tag(version: str | None) -> str:
            asked.append(version)
            return 'v1.14.3'

        monkeypatch.setattr(checker, 'previous_release_tag', previous_release_tag)

        checker.main(['--newest', '--changelog', str(changelog)])

        assert asked == [None]

    def it_prints_each_problem_with_the_problem_prefix(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)
        path = tmp_path / 'CHANGELOG.md'
        path.write_text(_changelog_text('1.14.4', upgrade_notes='- **Other.** (no docs: test)\n'), encoding='utf-8')

        assert checker.main(['1.14.4', '--changelog', str(path)]) == 1
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == '1.14.4 cannot be released with its cache markers as they are:'
        assert len(lines) == 3
        assert lines[1].startswith('PROBLEM: CACHE_VERSION changed since v1.14.3')
        assert lines[2].startswith('PROBLEM: CACHE_VERSION changed since v1.14.3')

    def it_exits_2_when_the_markers_at_the_previous_tag_cannot_be_read(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)
        monkeypatch.setattr(checker, 'released_markers', lambda *_: None)

        assert checker.main(['--newest', '--changelog', str(changelog)]) == 2
        assert 'cannot read the cache markers at v1.14.3' in capsys.readouterr().err

    def it_exits_2_when_the_markers_being_released_cannot_be_read(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)

        def unreadable() -> object:
            raise docs_gate.CannotCheckError('cannot read the cache markers')

        monkeypatch.setattr(checker, '_head_markers', unreadable)

        assert checker.main(['--newest', '--changelog', str(changelog)]) == 2

    def it_exits_2_and_names_an_unexpected_error(
        self, monkeypatch: pytest.MonkeyPatch, changelog: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)

        def broken() -> object:
            raise FileNotFoundError('src/pytest_gremlins/cache/versions.py')

        monkeypatch.setattr(checker, '_head_markers', broken)

        assert checker.main(['--newest', '--changelog', str(changelog)]) == 2
        assert 'unexpected FileNotFoundError' in capsys.readouterr().err

    def it_exits_2_when_the_changelog_cannot_be_read(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _StubbedGitReaders(monkeypatch, head=CACHE_RAISED)

        assert checker.main(['1.15.0', '--changelog', str(tmp_path / 'missing.md')]) == 2


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            sys.modules['check_verdict_change'].GIT,
            '-c',
            'user.name=t',
            '-c',
            'user.email=t@example.com',
            '-c',
            'commit.gpgsign=false',
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write_markers(repo: Path, cache_version: int, fidelity: str) -> None:
    versions = repo / sys.modules['check_verdict_change'].VERSIONS_PATH
    incremental = repo / sys.modules['check_verdict_change'].INCREMENTAL_PATH
    versions.parent.mkdir(parents=True, exist_ok=True)
    incremental.parent.mkdir(parents=True, exist_ok=True)
    versions.write_text(f'CACHE_VERSION = {cache_version}\n', encoding='utf-8')
    incremental.write_text(f"RUNNER_FIDELITY_VERSION = '{fidelity}'\n", encoding='utf-8')


@pytest.fixture
def tagged_repo(tmp_path: Path) -> Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _write_markers(repo, 3, 'rf21')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-q', '-m', 'one')
    _git(repo, 'tag', 'v1.14.3')
    return repo


@pytest.mark.medium
class DescribeMarkersChangedSinceLastRelease:
    def it_returns_the_previous_version_and_no_names_when_the_markers_are_unchanged(self, tagged_repo: Path) -> None:
        assert checker.markers_changed_since_last_release(tagged_repo) == ('1.14.3', [])

    def it_names_the_marker_that_changed_since_the_tag(self, tagged_repo: Path) -> None:
        _write_markers(tagged_repo, 4, 'rf21')

        assert checker.markers_changed_since_last_release(tagged_repo) == ('1.14.3', ['CACHE_VERSION'])

    def it_returns_nothing_without_a_release_tag(self, tagged_repo: Path) -> None:
        _git(tagged_repo, 'tag', '-d', 'v1.14.3')

        assert checker.markers_changed_since_last_release(tagged_repo) is None

    def it_names_a_changed_runner_fidelity_version(self, tagged_repo: Path) -> None:
        _write_markers(tagged_repo, 3, 'rf22')

        assert checker.markers_changed_since_last_release(tagged_repo) == ('1.14.3', ['RUNNER_FIDELITY_VERSION'])

    def it_compares_with_the_newest_release_tag(self, tagged_repo: Path) -> None:
        _write_markers(tagged_repo, 4, 'rf21')
        _git(tagged_repo, 'commit', '-q', '-am', 'two')
        _git(tagged_repo, 'tag', 'v1.15.0')

        assert checker.markers_changed_since_last_release(tagged_repo) == ('1.15.0', [])

    def it_returns_nothing_when_the_markers_at_the_tag_cannot_be_read(self, tmp_path: Path) -> None:
        repo = tmp_path / 'repo'
        repo.mkdir()
        _git(repo, 'init', '-q')
        _write_markers(repo, 3, 'rf21')
        (repo / sys.modules['check_verdict_change'].VERSIONS_PATH).write_text('nothing here\n', encoding='utf-8')
        _git(repo, 'add', '.')
        _git(repo, 'commit', '-q', '-m', 'one')
        _git(repo, 'tag', 'v1.14.3')
        _write_markers(repo, 3, 'rf21')

        assert checker.markers_changed_since_last_release(repo) is None

    def it_returns_nothing_when_the_markers_cannot_be_read(self, tagged_repo: Path) -> None:
        (tagged_repo / sys.modules['check_verdict_change'].VERSIONS_PATH).write_text('nothing here\n', encoding='utf-8')

        assert checker.markers_changed_since_last_release(tagged_repo) is None

    def it_returns_nothing_when_a_marker_file_is_missing(self, tagged_repo: Path) -> None:
        (tagged_repo / sys.modules['check_verdict_change'].INCREMENTAL_PATH).unlink()

        assert checker.markers_changed_since_last_release(tagged_repo) is None

    def it_returns_nothing_when_a_marker_file_is_not_utf8(self, tagged_repo: Path) -> None:
        (tagged_repo / sys.modules['check_verdict_change'].VERSIONS_PATH).write_bytes(b'\xff\xfe')

        assert checker.markers_changed_since_last_release(tagged_repo) is None


WORKFLOWS = Path(__file__).resolve().parents[2] / '.github' / 'workflows'
GATE = 'check_cache_bump.py'


def _steps(workflow: str, job: str) -> list[dict[str, object]]:
    jobs = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding='utf-8'))['jobs']
    steps: list[dict[str, object]] = jobs[job]['steps']
    return steps


def _index(workflow: str, job: str, text: str) -> int:
    return next(i for i, step in enumerate(_steps(workflow, job)) if text in str(step.get('run', '')))


@pytest.mark.medium
class DescribeWorkflowGate:
    def it_runs_in_the_release_pr_job_only_when_the_version_changed_with_the_version_from_the_guard(self) -> None:
        step = _steps('ci.yml', 'release-pr')[_index('ci.yml', 'release-pr', GATE)]

        assert step['if'] == "steps.guard.outputs.version_changed == 'true'"
        assert step['env'] == {'VERSION': '${{ steps.guard.outputs.version }}'}
        assert '"$VERSION"' in str(step['run'])
        assert 'continue-on-error' not in step

    def it_runs_right_after_the_cache_kept_gate_in_the_release_pr_job(self) -> None:
        assert _index('ci.yml', 'release-pr', GATE) == _index('ci.yml', 'release-pr', 'check_cache_kept.py') + 1

    def it_runs_in_verify_tag_after_checking_out_the_tag_with_no_skip(self) -> None:
        step = _steps('release.yml', 'verify-tag')[_index('release.yml', 'verify-tag', GATE)]

        assert 'if' not in step
        assert 'continue-on-error' not in step
        assert '"$RELEASE_TAG"' in str(step['run'])
        assert '--no-project' not in str(step['run'])
        assert _index('release.yml', 'verify-tag', 'git checkout --detach "refs/tags/$RELEASE_TAG"') < _index(
            'release.yml', 'verify-tag', GATE
        )

    def it_is_not_added_to_the_retiring_cut_release_workflow(self) -> None:
        assert GATE not in (WORKFLOWS / 'cut-release.yml').read_text(encoding='utf-8')
