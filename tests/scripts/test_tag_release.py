"""Tests for scripts/tag_release.py -- the logic behind tag-release.yml.

The decision table runs against real git repositories (a bare origin and a clone). The GitHub calls (pull request
lookup, tag creation, workflow dispatch) and the two gate scripts sit behind ``Effects``, so they are replaced by
recorders here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import (
    dataclass,
    field,
)
import importlib.util
import json
import locale
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from types import (
    ModuleType,
    SimpleNamespace,
)
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'tag_release.py'

GIT_CONFIG_ARGS = (
    '-c',
    'user.name=Test',
    '-c',
    'user.email=test@example.com',
    '-c',
    'commit.gpgsign=false',
    '-c',
    'tag.gpgSign=false',
    '-c',
    'core.autocrlf=false',
)
# COVERAGE_PROCESS_START is dropped so no child process starts a coverage run of its own. The Actions variables are
# dropped so a run of these tests in CI neither annotates nor writes to the test job's own step summary.
ACTIONS_ENV = ('GITHUB_ACTIONS', 'GITHUB_STEP_SUMMARY')
ISOLATED_GIT_ENV = {
    **{key: value for key, value in os.environ.items() if key != 'COVERAGE_PROCESS_START' and key not in ACTIONS_ENV},
    'GIT_CONFIG_GLOBAL': os.devnull,
    'GIT_CONFIG_NOSYSTEM': '1',
}
WORKFLOW_PATH = '.github/workflows/tag-release.yml'


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location('tag_release', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['tag_release'] = module
    spec.loader.exec_module(module)
    return module


tag_release = _load_module()


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ['git', *GIT_CONFIG_ARGS, *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=ISOLATED_GIT_ENV,
    )
    return completed.stdout.strip()


def _pyproject(version: str) -> str:
    return f'[project]\nname = "demo"\nversion = "{version}"\n'


def _commit(clone: Path, version: str, extra_files: tuple[str, ...] = ()) -> str:
    (clone / 'pyproject.toml').write_text(_pyproject(version))
    paths = ['pyproject.toml']
    for extra in extra_files:
        target = clone / extra
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'changed for {version}\n')
        paths.append(extra)
    _git(clone, 'add', *paths)
    _git(clone, 'commit', '--quiet', '--allow-empty', '-m', f'version {version}')
    _git(clone, 'push', '--quiet', 'origin', 'HEAD:refs/heads/main')
    return _git(clone, 'rev-parse', 'HEAD')


def _make_repo(
    tmp_path: Path, parent_version: str, pushed_version: str, extra_files: tuple[str, ...] = ()
) -> tuple[Path, Path, str]:
    """Return ``(origin, clone, sha)``: main has a commit at ``parent_version``, then ``sha`` at ``pushed_version``."""
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--quiet', '--bare', str(origin))
    clone = tmp_path / 'clone'
    _git(tmp_path, 'clone', '--quiet', str(origin), str(clone))
    _commit(clone, parent_version)
    sha = _commit(clone, pushed_version, extra_files)
    return origin, clone, sha


def _tag_on_origin(clone: Path, tag: str, commit: str) -> None:
    _git(clone, 'tag', '-a', tag, commit, '-m', 'release')
    _git(clone, 'push', '--quiet', 'origin', f'refs/tags/{tag}')
    _git(clone, 'tag', '-d', tag)


@dataclass
class Recorder:
    calls: list[str] = field(default_factory=list)
    guard_error: Exception | None = None
    pull_request_branch: str | None = 'release/v9.9.9'
    blocker_error: Exception | None = None
    dispatch_error: Exception | None = None

    def effects(self) -> object:
        return tag_release.Effects(
            find_pull_request_branch=self._find_pull_request_branch,
            run_guard=self._run_guard,
            run_blocker_gate=self._run_blocker_gate,
            create_tag=self._create_tag,
            dispatch=self._dispatch,
        )

    def _find_pull_request_branch(self, sha: str) -> str | None:
        self.calls.append(f'find_pull_request_branch {sha}')
        return self.pull_request_branch

    def _run_guard(self, sha: str, pull_request_branch: str) -> None:
        self.calls.append(f'guard {sha} {pull_request_branch}')
        if self.guard_error is not None:
            raise self.guard_error

    def _run_blocker_gate(self) -> None:
        self.calls.append('blockers')
        if self.blocker_error is not None:
            raise self.blocker_error

    def _create_tag(self, tag: str, sha: str) -> None:
        self.calls.append(f'create_tag {tag} {sha}')

    def _dispatch(self, tag: str) -> None:
        self.calls.append(f'dispatch {tag}')
        if self.dispatch_error is not None:
            raise self.dispatch_error


def _release(clone: Path, sha: str, recorder: Recorder, before: str | None = None) -> str:
    main_tip_before_push = before if before is not None else _git(clone, 'rev-parse', f'{sha}^')
    return str(tag_release.release(clone, sha, recorder.effects(), main_tip_before_push))


@pytest.mark.medium
class DescribeAVersionThatDidNotChange:
    def it_is_a_no_op_when_the_tag_exists(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', sha)
        recorder = Recorder()

        message = _release(clone, sha, recorder)

        assert message == 'v1.2.3 already tagged'
        assert recorder.calls == []

    def it_is_a_no_op_when_the_tag_is_on_an_older_commit(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', _git(clone, 'rev-parse', 'HEAD~1'))
        recorder = Recorder()

        message = _release(clone, sha, recorder)

        assert message == 'v1.2.3 already tagged'
        assert recorder.calls == []

    def it_fails_without_tagging_when_the_tag_is_missing(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')
        recorder = Recorder()

        with pytest.raises(tag_release.ReleaseRefusedError, match=re.escape('v1.2.3')):
            _release(clone, sha, recorder)

        assert recorder.calls == []


@pytest.mark.medium
class DescribeAVersionThatChanged:
    def it_runs_the_guard_and_the_blocker_gate_then_tags_then_dispatches(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder()

        message = _release(clone, sha, recorder)

        assert recorder.calls == [
            f'find_pull_request_branch {sha}',
            f'guard {sha} release/v9.9.9',
            'blockers',
            f'create_tag v1.2.3 {sha}',
            'dispatch v1.2.3',
        ]
        assert message == f'tagged v1.2.3 at {sha} and dispatched release.yml'

    def it_tags_a_prerelease_version(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.14.0', '1.15.0b0')
        recorder = Recorder()

        _release(clone, sha, recorder)

        assert f'create_tag v1.15.0b0 {sha}' in recorder.calls

    def it_ignores_a_tag_whose_name_only_shares_the_prefix(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _tag_on_origin(clone, 'v1.2.30', sha)
        recorder = Recorder()

        _release(clone, sha, recorder)

        assert f'create_tag v1.2.3 {sha}' in recorder.calls

    @pytest.mark.parametrize('failing', ['guard_error', 'blocker_error'])
    def it_creates_no_tag_and_dispatches_nothing_when_a_gate_fails(self, tmp_path: Path, failing: str) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder(**{failing: tag_release.ReleaseRefusedError('gate said no')})

        with pytest.raises(tag_release.ReleaseRefusedError, match='gate said no'):
            _release(clone, sha, recorder)

        assert not any(call.startswith(('create_tag', 'dispatch')) for call in recorder.calls)

    def it_skips_the_blocker_gate_when_the_guard_fails(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder(guard_error=tag_release.ReleaseRefusedError('guard said no'))

        with pytest.raises(tag_release.ReleaseRefusedError):
            _release(clone, sha, recorder)

        assert 'blockers' not in recorder.calls


@pytest.mark.medium
class DescribeARerun:
    def it_only_dispatches_when_the_tag_peels_to_this_commit(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', sha)
        recorder = Recorder()

        message = _release(clone, sha, recorder)

        assert recorder.calls == [f'find_pull_request_branch {sha}', 'dispatch v1.2.3']
        assert message == f'v1.2.3 already tagged at {sha}; dispatched release.yml'

    def it_compares_the_peeled_commit_not_the_annotated_tag_object(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', sha)
        tag_object = _git(clone, 'ls-remote', 'origin', 'refs/tags/v1.2.3').split()[0]
        recorder = Recorder()

        _release(clone, sha, recorder)

        assert tag_object != sha
        assert recorder.calls == [f'find_pull_request_branch {sha}', 'dispatch v1.2.3']

    def it_accepts_a_lightweight_tag_on_this_commit(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _git(clone, 'push', '--quiet', 'origin', f'{sha}:refs/tags/v1.2.3')
        recorder = Recorder()

        _release(clone, sha, recorder)

        assert recorder.calls == [f'find_pull_request_branch {sha}', 'dispatch v1.2.3']

    def it_fails_loudly_and_dispatches_nothing_when_the_tag_is_on_another_commit(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', _git(clone, 'rev-parse', 'HEAD~1'))
        recorder = Recorder()

        with pytest.raises(tag_release.ReleaseRefusedError, match='another commit'):
            _release(clone, sha, recorder)

        assert recorder.calls == []


@pytest.mark.medium
class DescribeAReleaseCommitThatEditsThisWorkflow:
    def it_refuses_when_the_version_changes_too(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3', extra_files=(WORKFLOW_PATH,))
        recorder = Recorder()

        with pytest.raises(tag_release.ReleaseRefusedError, match=re.escape('tag-release.yml')):
            _release(clone, sha, recorder)

        assert recorder.calls == []

    def it_does_not_object_when_the_version_is_unchanged(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3', extra_files=(WORKFLOW_PATH,))
        _tag_on_origin(clone, 'v1.2.3', _git(clone, 'rev-parse', 'HEAD~1'))
        recorder = Recorder()

        assert _release(clone, sha, recorder) == 'v1.2.3 already tagged'


@pytest.mark.medium
class DescribeALookupThatFails:
    def it_fails_closed_when_origin_is_unreachable(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _git(clone, 'remote', 'set-url', 'origin', str(tmp_path / 'missing.git'))
        recorder = Recorder()

        with pytest.raises(tag_release.CannotCheckError, match=re.escape('could not look up tag v1.2.3')):
            _release(clone, sha, recorder)

        assert recorder.calls == []

    def it_fails_closed_when_the_commit_has_no_parent(self, tmp_path: Path) -> None:
        origin = tmp_path / 'origin.git'
        _git(tmp_path, 'init', '--quiet', '--bare', str(origin))
        clone = tmp_path / 'clone'
        _git(tmp_path, 'clone', '--quiet', str(origin), str(clone))
        sha = _commit(clone, '1.2.3')
        recorder = Recorder()

        with pytest.raises(tag_release.CannotCheckError, match='parent'):
            _release(clone, sha, recorder, before='f' * 40)

        assert recorder.calls == []

    @pytest.mark.parametrize(
        'bad_version',
        ['latest', '01.2.3', '1.2.3abc', ''],
    )
    def it_fails_closed_on_an_unusable_version(self, tmp_path: Path, bad_version: str) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', bad_version)
        recorder = Recorder()

        with pytest.raises(tag_release.CannotCheckError):
            _release(clone, sha, recorder)

        assert recorder.calls == []

    def it_fails_closed_when_the_parent_version_is_unusable(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, 'latest', '1.2.3')
        recorder = Recorder()

        with pytest.raises(tag_release.CannotCheckError):
            _release(clone, sha, recorder)

        assert recorder.calls == []


def _pull(*, merged: bool = True, head_repo: str = 'owner/repo', ref: str = 'release/v1.2.3') -> dict[str, object]:
    return {
        'merged_at': '2026-11-22T00:00:00Z' if merged else None,
        'head': {'ref': ref, 'repo': {'full_name': head_repo}},
    }


@pytest.mark.small
class DescribeTheHeadBranchOfAMergedPullRequest:
    def it_returns_the_branch_of_the_one_merged_pull_request(self) -> None:
        pulls = json.dumps([_pull()])

        assert tag_release.head_ref_from_pulls(pulls, 'owner/repo') == 'release/v1.2.3'

    @pytest.mark.parametrize(
        'pulls',
        [
            pytest.param([_pull(head_repo='fork/repo')], id='fork'),
            pytest.param([_pull(), _pull(ref='release/v1.2.4')], id='two'),
            pytest.param([{'merged_at': 'x', 'head': {'ref': 'a', 'repo': None}}], id='deleted-fork'),
        ],
    )
    def it_refuses_a_fork_or_more_than_one_merged_pull_request(self, pulls: list[object]) -> None:
        with pytest.raises(tag_release.ReleaseRefusedError):
            tag_release.head_ref_from_pulls(json.dumps(pulls), 'owner/repo')

    @pytest.mark.parametrize('pulls', [[], [_pull(merged=False)]], ids=['none', 'unmerged'])
    def it_returns_nothing_when_no_merged_pull_request_exists(self, pulls: list[object]) -> None:
        assert tag_release.head_ref_from_pulls(json.dumps(pulls), 'owner/repo') is None

    def it_ignores_an_unmerged_pull_request_next_to_the_merged_one(self) -> None:
        pulls = json.dumps([_pull(merged=False, ref='other'), _pull()])

        assert tag_release.head_ref_from_pulls(pulls, 'owner/repo') == 'release/v1.2.3'

    @pytest.mark.parametrize('text', ['not json', '{}', '"x"'])
    def it_fails_closed_on_an_answer_that_is_not_a_list(self, text: str) -> None:
        with pytest.raises(tag_release.CannotCheckError):
            tag_release.head_ref_from_pulls(text, 'owner/repo')


@pytest.mark.small
class DescribeTheTagRequest:
    def it_builds_an_annotated_tag_object_for_the_commit_by_the_actions_bot(self) -> None:
        payload = tag_release.tag_object_payload('v1.2.3', 'abc123')

        assert payload['tag'] == 'v1.2.3'
        assert payload['object'] == 'abc123'
        assert payload['type'] == 'commit'
        assert payload['message'] == 'Release v1.2.3'
        assert payload['tagger'] == {
            'name': 'github-actions[bot]',
            'email': '41898282+github-actions[bot]@users.noreply.github.com',
        }


@pytest.mark.small
class DescribeTheGateCommands:
    def it_runs_the_guard_that_sits_next_to_the_script_against_the_parent(self) -> None:
        command = tag_release.guard_command(Path('/work'), 'abc', 'release/v1.2.3')

        assert command[1:3] == ['-E', '-s']
        assert command[3] == str(SCRIPT.parent / 'check_version_change.py')
        assert command[4:] == [
            '--repo',
            str(Path('/work')),
            '--base-ref',
            'abc^',
            '--branch',
            'release/v1.2.3',
        ]

    def it_runs_the_blocker_gate_that_sits_next_to_the_script(self) -> None:
        command = tag_release.blocker_command()

        assert command[1:3] == ['-E', '-s']
        assert command[3] == str(SCRIPT.parent / 'check_no_release_blockers.py')


def _run_cli(clone: Path, sha: str, *extra: str) -> subprocess.CompletedProcess[str]:
    before = _git(clone, 'rev-parse', f'{sha}^')
    env = {key: value for key, value in ISOLATED_GIT_ENV.items() if key != 'GITHUB_REPOSITORY'}
    return subprocess.run(
        [sys.executable, str(SCRIPT), '--repo', str(clone), '--sha', sha, '--before', before, *extra],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.medium
class DescribeTheCommandLine:
    def it_prints_the_no_op_line_and_exits_zero(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', sha)

        result = _run_cli(clone, sha, '--github-repository', 'owner/repo')

        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ['v1.2.3 already tagged']

    def it_exits_one_when_a_rule_is_broken(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')

        result = _run_cli(clone, sha, '--github-repository', 'owner/repo')

        assert result.returncode == 1
        assert 'did not change the version' in result.stderr

    def it_exits_two_when_the_lookup_fails(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _git(clone, 'remote', 'set-url', 'origin', str(tmp_path / 'missing.git'))

        result = _run_cli(clone, sha, '--github-repository', 'owner/repo')

        assert result.returncode == 2
        assert 'could not look up tag' in result.stderr

    def it_exits_two_without_a_repository_name(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')

        result = _run_cli(clone, sha)

        assert result.returncode == 2
        assert 'GITHUB_REPOSITORY' in result.stderr


@pytest.mark.medium
class DescribeAPushThatAddedSeveralCommits:
    ZEROS = '0' * 40

    def it_refuses_a_version_change_when_the_parent_is_not_the_main_tip_before_the_push(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder()

        with pytest.raises(tag_release.ReleaseRefusedError, match='exactly one commit'):
            _release(clone, sha, recorder, before='f' * 40)

        assert recorder.calls == []

    @pytest.mark.parametrize('before', ['', ZEROS])
    def it_refuses_a_version_change_without_a_real_before_commit(self, tmp_path: Path, before: str) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder()

        with pytest.raises(tag_release.ReleaseRefusedError, match='exactly one commit'):
            _release(clone, sha, recorder, before=before)

        assert recorder.calls == []

    def it_does_not_look_at_before_when_the_version_is_unchanged(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', sha)

        assert _release(clone, sha, Recorder(), before=self.ZEROS) == 'v1.2.3 already tagged'


@pytest.mark.medium
class DescribeATagMadeByAnotherPath:
    def it_is_a_no_op_when_no_pull_request_exists_and_the_tag_is_on_this_commit(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', sha)
        recorder = Recorder(pull_request_branch=None)

        message = _release(clone, sha, recorder)

        assert message == 'v1.2.3 was tagged by another path (cut-release.yml); its tag push runs release.yml'
        assert recorder.calls == [f'find_pull_request_branch {sha}']

    def it_refuses_when_no_pull_request_exists_and_there_is_no_tag(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder(pull_request_branch=None)

        with pytest.raises(tag_release.ReleaseRefusedError, match='cut-release'):
            _release(clone, sha, recorder)

        assert recorder.calls == [f'find_pull_request_branch {sha}']

    def it_looks_up_the_pull_request_before_tagging(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder()

        _release(clone, sha, recorder)

        assert recorder.calls[0] == f'find_pull_request_branch {sha}'


@pytest.mark.medium
class DescribeTheRecoveryHint:
    def it_points_a_missed_release_at_rerunning_the_release_commits_run(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')

        with pytest.raises(tag_release.ReleaseRefusedError, match='gh run rerun'):
            _release(clone, sha, Recorder())


class FixedAnswerGh:
    """Replaces ``tag_release._gh`` with one fixed answer."""

    def __init__(self, answer: str) -> None:
        self.answer = answer

    def __call__(self, *_args: str, stdin: str | None = None) -> str:  # noqa: ARG002
        return self.answer


@pytest.mark.small
class DescribeAnAnswerThatIsNotWhatWasExpected:
    @pytest.mark.parametrize(
        'pull',
        [
            pytest.param({'merged_at': 'x', 'head': 'release/v1.2.3'}, id='head-not-an-object'),
            pytest.param({'merged_at': 'x', 'head': {'repo': {'full_name': 'owner/repo'}}}, id='no-ref'),
            pytest.param(
                {'merged_at': 'x', 'head': {'ref': 7, 'repo': {'full_name': 'owner/repo'}}}, id='ref-not-text'
            ),
        ],
    )
    def it_fails_closed_on_a_merged_pull_request_without_a_usable_head_branch(self, pull: dict[str, object]) -> None:
        with pytest.raises(tag_release.CannotCheckError):
            tag_release.head_ref_from_pulls(json.dumps([pull]), 'owner/repo')

    @pytest.mark.parametrize('entry', [42, 'text', None, [1]])
    def it_fails_closed_on_a_pulls_entry_that_is_not_an_object(self, entry: object) -> None:
        with pytest.raises(tag_release.CannotCheckError):
            tag_release.head_ref_from_pulls(json.dumps([entry]), 'owner/repo')

    @pytest.mark.parametrize('answer', ['not json', '[]', '{"message": "odd"}', '{"sha": 7}'])
    def it_fails_closed_on_a_tag_object_answer_without_a_sha(
        self, monkeypatch: pytest.MonkeyPatch, answer: str
    ) -> None:
        monkeypatch.setattr(tag_release, '_gh', FixedAnswerGh(answer))
        effects = tag_release.github_effects(Path(), 'owner/repo')

        with pytest.raises(tag_release.CannotCheckError):
            effects.create_tag('v1.2.3', 'a' * 40)

    def it_exits_two_on_an_unexpected_error_and_prints_its_traceback(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def explode(*_args: object) -> str:
            raise RuntimeError('boom')

        monkeypatch.setattr(tag_release, 'release', explode)
        for name in ACTIONS_ENV:
            monkeypatch.delenv(name, raising=False)

        status = tag_release.main(['--sha', 'abc', '--before', 'def', '--github-repository', 'owner/repo'])

        err = capsys.readouterr().err
        assert status == 2
        assert 'error: unexpected RuntimeError: boom' in err
        assert 'Traceback (most recent call last)' in err


@pytest.mark.medium
class DescribeAPyprojectThatIsNotUtf8:
    def it_fails_closed_instead_of_crashing(self, tmp_path: Path) -> None:
        origin = tmp_path / 'origin.git'
        _git(tmp_path, 'init', '--quiet', '--bare', str(origin))
        clone = tmp_path / 'clone'
        _git(tmp_path, 'clone', '--quiet', str(origin), str(clone))
        _commit(clone, '1.0.0')
        (clone / 'pyproject.toml').write_bytes(b'[project]\nversion = "1.0.0"\n# \xff\xfe\n')
        _git(clone, 'add', 'pyproject.toml')
        _git(clone, 'commit', '--quiet', '-m', 'binary')
        sha = _git(clone, 'rev-parse', 'HEAD')

        result = _run_cli(clone, sha, '--github-repository', 'owner/repo')

        assert result.returncode == 2, result.stderr
        assert 'Traceback' not in result.stderr
        assert 'not UTF-8' in result.stderr


# Python on Windows decodes subprocess text with the ANSI code page (cp1252), which, like ISO-8859-1, decodes the bytes
# 0xff 0xfe without error. This locale reproduces that leg on POSIX.
SINGLE_BYTE_LOCALE = {'LC_ALL': 'en_US.ISO8859-1', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0'}
PREFERRED_ENCODING_PROBE = 'import codecs, locale; print(codecs.lookup(locale.getpreferredencoding(False)).name)'


@pytest.fixture
def single_byte_locale_env() -> dict[str, str]:
    """Return the child environment, skipping when the host cannot give a child an ISO-8859-1 preferred encoding.

    A host without the locale (common on ubuntu-latest) falls back to ASCII, which also rejects 0xff, so the test would
    pass with or without UTF-8 decoding in the script and prove nothing.
    """
    env = {**ISOLATED_GIT_ENV, **SINGLE_BYTE_LOCALE}
    probe = subprocess.run(
        [sys.executable, '-c', PREFERRED_ENCODING_PROBE], env=env, capture_output=True, text=True, check=True
    )
    encoding = probe.stdout.strip()
    if encoding != 'iso8859-1':
        pytest.skip(f'{SINGLE_BYTE_LOCALE["LC_ALL"]} is not installed (child preferred encoding: {encoding})')
    return env


@pytest.mark.medium
@pytest.mark.skipif(os.name == 'nt', reason='forces a POSIX locale')
class DescribeAPyprojectThatIsNotUtf8UnderASingleByteLocale:
    def it_still_fails_closed_because_git_output_is_decoded_as_utf8(
        self, tmp_path: Path, single_byte_locale_env: dict[str, str]
    ) -> None:
        origin = tmp_path / 'origin.git'
        _git(tmp_path, 'init', '--quiet', '--bare', str(origin))
        clone = tmp_path / 'clone'
        _git(tmp_path, 'clone', '--quiet', str(origin), str(clone))
        before = _commit(clone, '1.0.0')
        (clone / 'pyproject.toml').write_bytes(b'[project]\nversion = "1.0.0"\n# \xff\xfe\n')
        _git(clone, 'add', 'pyproject.toml')
        _git(clone, 'commit', '--quiet', '-m', 'binary')
        sha = _git(clone, 'rev-parse', 'HEAD')
        command = [sys.executable, str(SCRIPT), '--repo', str(clone), '--sha', sha, '--before', before]
        command += ['--github-repository', 'owner/repo']

        result = subprocess.run(command, env=single_byte_locale_env, capture_output=True, text=True, check=False)

        assert result.returncode == 2, result.stderr
        assert 'not UTF-8' in result.stderr


class FakeGh:
    """Replaces ``tag_release._gh`` and records every call."""

    TAG_OBJECT_SHA = '1' * 40

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    def __call__(self, *args: str, stdin: str | None = None) -> str:
        self.calls.append((args, stdin))
        if 'git/tags' in ' '.join(args):
            return json.dumps({'sha': self.TAG_OBJECT_SHA})
        return '[]' if '/pulls' in ' '.join(args) else '{}'


@pytest.mark.small
class DescribeTheGithubCalls:
    def it_points_the_tag_ref_at_the_tag_object_not_the_commit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeGh()
        monkeypatch.setattr(tag_release, '_gh', fake)

        tag_release.github_effects(Path(), 'owner/repo').create_tag('v1.2.3', 'c' * 40)

        (tag_args, tag_stdin), (ref_args, ref_stdin) = fake.calls
        assert tag_args[:4] == ('api', '--method', 'POST', 'repos/owner/repo/git/tags')
        assert json.loads(str(tag_stdin))['object'] == 'c' * 40
        assert ref_args[:4] == ('api', '--method', 'POST', 'repos/owner/repo/git/refs')
        assert json.loads(str(ref_stdin)) == {'ref': 'refs/tags/v1.2.3', 'sha': FakeGh.TAG_OBJECT_SHA}

    def it_dispatches_release_yml_from_main_with_the_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeGh()
        monkeypatch.setattr(tag_release, '_gh', fake)

        tag_release.github_effects(Path(), 'owner/repo').dispatch('v1.2.3')

        assert fake.calls == [
            (('workflow', 'run', 'release.yml', '--repo', 'owner/repo', '--ref', 'main', '-f', 'tag=v1.2.3'), None)
        ]

    def it_reads_the_pull_requests_of_the_commit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeGh()
        monkeypatch.setattr(tag_release, '_gh', fake)

        branch = tag_release.github_effects(Path(), 'owner/repo').find_pull_request_branch('c' * 40)

        assert branch is None
        assert fake.calls[0][0] == ('api', f'repos/owner/repo/commits/{"c" * 40}/pulls')


@pytest.mark.small
class DescribeAGateExitStatus:
    def it_reads_exit_one_as_a_refusal(self) -> None:
        with pytest.raises(tag_release.ReleaseRefusedError):
            tag_release._raise_for_status('the gate', 1)

    @pytest.mark.parametrize('status', [2, 3, 127])
    def it_reads_any_other_failure_as_could_not_run(self, status: int) -> None:
        with pytest.raises(tag_release.CannotCheckError):
            tag_release._raise_for_status('the gate', status)

    def it_accepts_zero(self) -> None:
        tag_release._raise_for_status('the gate', 0)


EXPORTED_SCRIPTS = (
    'tag_release.py',
    'check_no_release_blockers.py',
    'check_ci_passed.py',
    'check_version_change.py',
    'check_release_docs.py',
)
FAKE_GH = """#!{python}
import json
import sys

args = sys.argv[1:]
body = sys.stdin.read() if '--input' in args else ''
with open({log!r}, 'a') as log:
    log.write(json.dumps({{'argv': args, 'stdin': body}}) + '\\n')
joined = ' '.join(args)
if '/pulls' in joined:
    print(json.dumps([{{'merged_at': 'x', 'head': {{'ref': 'release/v1.15.0', 'repo': {{'full_name': 'o/r'}}}}}}]))
elif 'git/tags' in joined:
    print(json.dumps({{'sha': '{tag_object}'}}))
else:
    print('{{}}')
"""


def _write_release_files(clone: Path, version: str) -> None:
    (clone / 'pyproject.toml').write_text(_pyproject(version))
    init = clone / 'src' / 'pytest_gremlins' / '__init__.py'
    init.parent.mkdir(parents=True, exist_ok=True)
    init.write_text(f'"""Package."""\n\n__version__ = \'{version}\'\n')
    (clone / 'CHANGELOG.md').write_text(
        f'# Changelog\n\n## v{version} (2026-11-19)\n\n### Fix\n\n- **A fix.** (no docs: test)\n\n## v1.0.0\n\nOld.\n'
    )


def _commit_release_files(clone: Path, version: str, extra_file: str | None = None) -> str:
    _write_release_files(clone, version)
    paths = ['pyproject.toml', 'src/pytest_gremlins/__init__.py', 'CHANGELOG.md']
    if extra_file is not None:
        (clone / extra_file).write_text('unrelated\n')
        paths.append(extra_file)
    _git(clone, 'add', *paths)
    _git(clone, 'commit', '--quiet', '-m', f'release {version}')
    _git(clone, 'push', '--quiet', 'origin', 'HEAD:refs/heads/main')
    return _git(clone, 'rev-parse', 'HEAD')


def _run_exported(
    tmp_path: Path, extra_file: str | None
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]:
    """Run the script as the workflow does: exported scripts, ``-I``, another directory, a fake ``gh`` on PATH."""
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--quiet', '--bare', str(origin))
    clone = tmp_path / 'clone'
    _git(tmp_path, 'clone', '--quiet', str(origin), str(clone))
    before = _commit_release_files(clone, '1.14.3')
    _tag_on_origin(clone, 'v1.14.3', before)
    sha = _commit_release_files(clone, '1.15.0', extra_file)
    exported = tmp_path / 'exported'
    exported.mkdir()
    for name in EXPORTED_SCRIPTS:
        shutil.copy(SCRIPT.parent / name, exported / name)
    log = tmp_path / 'gh.log'
    # The real blocker gate calls api.github.com; the stand-in records that it ran and passes.
    stand_in = f'import pathlib\npathlib.Path({str(log)!r}).open("a").write(\'{{"argv": ["BLOCKER_GATE"]}}\\n\')\n'
    (exported / 'check_no_release_blockers.py').write_text(stand_in)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    gh = bin_dir / 'gh'
    gh.write_text(FAKE_GH.format(python=sys.executable, log=str(log), tag_object=FakeGh.TAG_OBJECT_SHA))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    env = {**ISOLATED_GIT_ENV, 'PATH': f'{bin_dir}{os.pathsep}{ISOLATED_GIT_ENV["PATH"]}', 'GH_TOKEN': 'x'}
    elsewhere = tmp_path / 'runner_temp'
    elsewhere.mkdir()
    command = [sys.executable, '-I', str(exported / 'tag_release.py'), '--sha', sha, '--before', before]
    command += ['--repo', str(clone), '--github-repository', 'o/r']
    completed = subprocess.run(command, cwd=elsewhere, env=env, capture_output=True, text=True, check=False)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return completed, calls


@pytest.mark.medium
@pytest.mark.skipif(os.name == 'nt', reason='the stand-in gh is a shebang script')
class DescribeTheScriptRunAsTheWorkflowRunsIt:
    def it_looks_up_the_pull_request_gates_tags_and_dispatches_in_order(self, tmp_path: Path) -> None:
        completed, calls = _run_exported(tmp_path, extra_file=None)

        assert completed.returncode == 0, completed.stderr + completed.stdout
        assert [call['argv'][0] for call in calls] == ['api', 'BLOCKER_GATE', 'api', 'api', 'workflow']
        assert '/pulls' in calls[0]['argv'][1]
        assert json.loads(calls[3]['stdin']) == {'ref': 'refs/tags/v1.15.0', 'sha': FakeGh.TAG_OBJECT_SHA}
        assert calls[4]['argv'][-4:] == ['--ref', 'main', '-f', 'tag=v1.15.0']

    def it_refuses_with_exit_one_and_posts_nothing_when_the_guard_fails(self, tmp_path: Path) -> None:
        completed, calls = _run_exported(tmp_path, extra_file='unrelated.py')

        assert completed.returncode == 1, completed.stderr
        assert not any('POST' in call['argv'] or 'workflow' in call['argv'] for call in calls)

    def it_logs_each_action_on_stderr_and_keeps_stdout_to_the_result_line(self, tmp_path: Path) -> None:
        completed, _ = _run_exported(tmp_path, extra_file=None)

        assert completed.stdout.splitlines()[-1].startswith('tagged v1.15.0 at ')
        assert 'release pull request branch: release/v1.15.0' in completed.stderr
        assert 'running the version guard' in completed.stderr
        assert 'running the release-blocker gate' in completed.stderr
        assert 'created tag v1.15.0 at ' in completed.stderr
        assert 'dispatched release.yml for v1.15.0' in completed.stderr


def _main_with_release(
    monkeypatch: pytest.MonkeyPatch, outcome: str | Exception, *, actions: bool, summary: Path | None = None
) -> int:
    def fake_release(*_args: object) -> str:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(tag_release, 'release', fake_release)
    for name in ACTIONS_ENV:
        monkeypatch.delenv(name, raising=False)
    if actions:
        monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    if summary is not None:
        monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    return int(tag_release.main(['--sha', 'abc', '--before', 'def', '--github-repository', 'owner/repo']))


@pytest.mark.small
class DescribeTheActionsAnnotations:
    def it_annotates_a_refusal_as_an_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        status = _main_with_release(monkeypatch, tag_release.ReleaseRefusedError('v1 is elsewhere'), actions=True)

        assert status == 1
        assert '::error title=tag-release refused (exit 1)::v1 is elsewhere' in capsys.readouterr().err

    def it_annotates_a_check_that_could_not_run_as_an_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        status = _main_with_release(monkeypatch, tag_release.CannotCheckError('lookup failed'), actions=True)

        assert status == 2
        assert '::error title=tag-release could not run (exit 2)::lookup failed' in capsys.readouterr().err

    def it_escapes_a_multi_line_message_so_the_annotation_keeps_all_of_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _main_with_release(monkeypatch, tag_release.CannotCheckError('gh failed:\r\nHTTP 500 at 100%'), actions=True)

        assert '::gh failed:%0D%0AHTTP 500 at 100%25\n' in capsys.readouterr().err

    def it_keeps_the_plain_error_line_next_to_the_annotation(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _main_with_release(monkeypatch, tag_release.CannotCheckError('lookup failed'), actions=True)

        assert 'error: lookup failed\n' in capsys.readouterr().err

    def it_does_not_annotate_outside_github_actions(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _main_with_release(monkeypatch, tag_release.CannotCheckError('lookup failed'), actions=False)

        assert '::error' not in capsys.readouterr().err


@pytest.mark.medium
class DescribeTheStepSummary:
    def it_records_a_tag_and_dispatch_with_the_commit(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        summary = tmp_path / 'summary.md'

        status = _main_with_release(
            monkeypatch, 'tagged v1.2.3 at abc and dispatched release.yml', actions=True, summary=summary
        )

        text = summary.read_text()
        assert status == 0
        assert '- Outcome: done' in text
        assert '- Commit: `abc`' in text
        assert '- Main before the push: `def`' in text
        assert 'tagged v1.2.3 at abc and dispatched release.yml' in text

    def it_records_a_refusal_with_its_reason(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        summary = tmp_path / 'summary.md'

        _main_with_release(
            monkeypatch, tag_release.ReleaseRefusedError('v1 is elsewhere'), actions=True, summary=summary
        )

        text = summary.read_text()
        assert '- Outcome: refused (exit 1)' in text
        assert 'v1 is elsewhere' in text

    def it_keeps_the_exit_status_when_the_summary_cannot_be_written(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        status = _main_with_release(monkeypatch, 'v1.2.3 already tagged', actions=True, summary=tmp_path)

        assert status == 0
        assert 'could not write the step summary' in capsys.readouterr().err


@pytest.mark.medium
class DescribeADispatchThatFailsAfterTheTagExists:
    def it_says_the_tag_exists_and_that_a_rerun_dispatches_only(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder(dispatch_error=tag_release.CannotCheckError('gh workflow run failed: HTTP 500'))

        with pytest.raises(tag_release.CannotCheckError) as raised:
            _release(clone, sha, recorder)

        message = str(raised.value)
        assert f'v1.2.3 now exists at {sha}' in message
        assert 'HTTP 500' in message
        assert 'gh run rerun' in message


FAILING_GH = """#!{python}
import sys

sys.stdin.read()
sys.stderr.write('HTTP 422: Reference already exists\\n')
sys.exit(1)
"""


@pytest.mark.medium
@pytest.mark.skipif(os.name == 'nt', reason='the stand-in gh is a shebang script')
class DescribeAFailedGhCall:
    def it_names_the_whole_command_so_two_posts_are_told_apart(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        gh = tmp_path / 'gh'
        gh.write_text(FAILING_GH.format(python=sys.executable))
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{os.environ["PATH"]}')

        with pytest.raises(tag_release.CannotCheckError, match=r'repos/o/r/git/refs .*HTTP 422'):
            tag_release._gh('api', '--method', 'POST', 'repos/o/r/git/refs', '--input', '-', stdin='{}')


class RecordedRun:
    """Stands in for ``subprocess.run`` inside ``tag_release`` only: records the keyword arguments, reports success."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.kwargs = kwargs
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')


@pytest.mark.small
class DescribeTheTokensInTheGateEnvironments:
    TOKENS = ('GH_TOKEN', 'GITHUB_TOKEN')

    def it_removes_the_workflow_tokens_from_the_guard_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in self.TOKENS:
            monkeypatch.setenv(name, 'secret')
        monkeypatch.setenv('KEPT', 'yes')

        environment = tag_release.guard_environment()

        assert not set(self.TOKENS) & set(environment)
        assert environment['KEPT'] == 'yes'

    def it_runs_the_guard_without_the_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in self.TOKENS:
            monkeypatch.setenv(name, 'secret')
        recorded = RecordedRun()
        monkeypatch.setattr(tag_release, 'subprocess', SimpleNamespace(run=recorded))

        tag_release.github_effects(Path('/work'), 'owner/repo').run_guard('abc', 'release/v1.2.3')

        assert not set(self.TOKENS) & set(recorded.kwargs['env'])

    def it_runs_the_blocker_gate_with_the_inherited_environment_that_holds_the_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded = RecordedRun()
        monkeypatch.setattr(tag_release, 'subprocess', SimpleNamespace(run=recorded))

        tag_release.github_effects(Path('/work'), 'owner/repo').run_blocker_gate()

        assert recorded.kwargs.get('env') is None


@pytest.mark.small
class DescribeUtf8DecodingOfCommandOutput:
    """Reverting to ``text=True`` would decode with the locale code page; this fails on every OS if that happens."""

    @pytest.mark.parametrize('call', [lambda: tag_release._git(Path(), 'status'), lambda: tag_release._gh('api', 'x')])
    def it_asks_subprocess_for_strict_utf8_whatever_the_locale(
        self, monkeypatch: pytest.MonkeyPatch, call: Callable[[], object]
    ) -> None:
        recorded = RecordedRun()
        monkeypatch.setattr(tag_release, 'subprocess', SimpleNamespace(run=recorded))
        monkeypatch.setattr(locale, 'getpreferredencoding', lambda *_args: 'cp1252')

        call()

        assert recorded.kwargs['encoding'] == 'utf-8'
        assert recorded.kwargs['errors'] == 'strict'
        assert 'text' not in recorded.kwargs


@pytest.mark.small
class DescribeTheIsolatedChildEnvironment:
    @pytest.mark.parametrize('name', ACTIONS_ENV)
    def it_drops_the_actions_variables_so_a_child_run_neither_annotates_nor_writes_the_job_summary(
        self, name: str
    ) -> None:
        assert name not in ISOLATED_GIT_ENV
