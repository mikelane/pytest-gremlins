"""Tests for scripts/tag_release.py -- the logic behind tag-release.yml.

The decision table runs against real git repositories (a bare origin and a clone). The GitHub calls (pull request
lookup, tag creation, workflow dispatch) and the two gate scripts sit behind ``Effects``, so they are replaced by
recorders here.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType

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
# COVERAGE_PROCESS_START is dropped so no child process starts a coverage run of its own.
ISOLATED_GIT_ENV = {
    **{key: value for key, value in os.environ.items() if key != 'COVERAGE_PROCESS_START'},
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
    result = subprocess.run(
        ['git', *GIT_CONFIG_ARGS, *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=ISOLATED_GIT_ENV,
    )
    return result.stdout.strip()


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


def _make_repo(tmp_path: Path, before: str, after: str, extra_files: tuple[str, ...] = ()) -> tuple[Path, Path, str]:
    """Return ``(origin, clone, sha)``: main holds a commit at version ``before``, then ``sha`` at version ``after``."""
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--quiet', '--bare', str(origin))
    clone = tmp_path / 'clone'
    _git(tmp_path, 'clone', '--quiet', str(origin), str(clone))
    _commit(clone, before)
    sha = _commit(clone, after, extra_files)
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

    def effects(self) -> object:
        return tag_release.Effects(
            head_ref=self._head_ref,
            run_guard=self._run_guard,
            run_blocker_gate=self._run_blocker_gate,
            create_tag=self._create_tag,
            dispatch=self._dispatch,
        )

    def _head_ref(self, sha: str) -> str | None:
        self.calls.append(f'head_ref {sha}')
        return self.pull_request_branch

    def _run_guard(self, sha: str, head_ref: str) -> None:
        self.calls.append(f'guard {sha} {head_ref}')
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


def _release(clone: Path, sha: str, recorder: Recorder, before: str | None = None) -> str:
    pushed_from = before if before is not None else _git(clone, 'rev-parse', f'{sha}^')
    return str(tag_release.release(clone, sha, recorder.effects(), pushed_from))


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
            f'head_ref {sha}',
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

        assert recorder.calls == [f'head_ref {sha}', 'dispatch v1.2.3']
        assert message == f'v1.2.3 already tagged at {sha}; dispatched release.yml'

    def it_compares_the_peeled_commit_not_the_annotated_tag_object(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _tag_on_origin(clone, 'v1.2.3', sha)
        tag_object = _git(clone, 'ls-remote', 'origin', 'refs/tags/v1.2.3').split()[0]
        recorder = Recorder()

        _release(clone, sha, recorder)

        assert tag_object != sha
        assert recorder.calls == [f'head_ref {sha}', 'dispatch v1.2.3']

    def it_accepts_a_lightweight_tag_on_this_commit(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        _git(clone, 'push', '--quiet', 'origin', f'{sha}:refs/tags/v1.2.3')
        recorder = Recorder()

        _release(clone, sha, recorder)

        assert recorder.calls == [f'head_ref {sha}', 'dispatch v1.2.3']

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
            '/work' if os.name != 'nt' else str(Path('/work')),
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
        assert recorder.calls == [f'head_ref {sha}']

    def it_refuses_when_no_pull_request_exists_and_there_is_no_tag(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder(pull_request_branch=None)

        with pytest.raises(tag_release.ReleaseRefusedError, match='cut-release'):
            _release(clone, sha, recorder)

        assert recorder.calls == [f'head_ref {sha}']

    def it_looks_up_the_pull_request_before_tagging(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.2', '1.2.3')
        recorder = Recorder()

        _release(clone, sha, recorder)

        assert recorder.calls[0] == f'head_ref {sha}'


@pytest.mark.medium
class DescribeTheRecoveryHint:
    def it_points_a_missed_release_at_rerunning_the_release_commits_run(self, tmp_path: Path) -> None:
        _, clone, sha = _make_repo(tmp_path, '1.2.3', '1.2.3')

        with pytest.raises(tag_release.ReleaseRefusedError, match='gh run rerun'):
            _release(clone, sha, Recorder())
