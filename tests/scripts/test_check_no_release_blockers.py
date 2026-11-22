"""Tests for scripts/check_no_release_blockers.py -- the release gate that fails while a release-blocker issue is open.

The GitHub API is replaced by a fake ``fetch`` that serves canned JSON, so no test touches the network.
"""

from __future__ import annotations

from collections.abc import (
    Callable,
    Iterator,
)
import email.message
import importlib.util
import io
from pathlib import Path
import sys
from types import ModuleType
from typing import Any
import urllib.error

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
REPO = 'owner/repo'
LABEL_PATH = f'/repos/{REPO}/labels/release-blocker'
ISSUES_PATH = f'/repos/{REPO}/issues?state=open&labels=release-blocker&per_page=100'


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
    _load('check_ci_passed')
    gate = _load('check_no_release_blockers')
finally:
    sys.path.remove(str(SCRIPTS))


def _issue(number: int, title: str = 'A blocker') -> dict[str, Any]:
    return {'number': number, 'title': title}


def _pull_request(number: int, title: str = 'A blocking PR') -> dict[str, Any]:
    return {'number': number, 'title': title, 'pull_request': {'url': f'https://example/pulls/{number}'}}


@pytest.fixture
def http_error() -> Iterator[Callable[[int], urllib.error.HTTPError]]:
    """Build HTTP errors and close them afterwards, so none is garbage collected unclosed."""
    created: list[urllib.error.HTTPError] = []

    def build(code: int) -> urllib.error.HTTPError:
        error = urllib.error.HTTPError('https://example', code, 'error', email.message.Message(), None)
        created.append(error)
        return error

    yield build
    for error in created:
        error.close()


def _transport_error(failure_kind: int | str, http_error: Callable[[int], urllib.error.HTTPError]) -> Exception:
    """Return the transport error ``failure_kind`` names: an HTTP status code, or ``'unreachable'`` for a URLError."""
    return urllib.error.URLError('boom') if failure_kind == 'unreachable' else http_error(int(failure_kind))


class FakeGitHub:
    """Serves the label and the paginated issue listing; ``pages`` are the issue pages in order."""

    def __init__(
        self, pages: list[object], label: object = None, label_error: Exception | None = None, repo: str = REPO
    ) -> None:
        self._pages = pages
        self._label = {'name': 'release-blocker'} if label is None else label
        self._label_error = label_error
        self._label_path = f'/repos/{repo}/labels/release-blocker'
        self.paths: list[str] = []

    def __call__(self, path: str) -> Any:
        self.paths.append(path)
        if path == self._label_path:
            if self._label_error is not None:
                raise self._label_error
            return self._label
        page = 1 if '&page=' not in path else int(path.rsplit('&page=', maxsplit=1)[1])
        return self._pages[page - 1] if page <= len(self._pages) else []


@pytest.mark.small
class DescribeFindBlockers:
    def it_finds_no_blockers_when_the_label_has_no_open_issues(self) -> None:
        assert gate.find_blockers(FakeGitHub([[]]), REPO) == []

    def it_finds_the_one_open_blocker(self) -> None:
        blockers = gate.find_blockers(FakeGitHub([[_issue(7, 'Cache key collides')]]), REPO)

        assert blockers == [gate.Blocker(number=7, title='Cache key collides', is_pull_request=False)]

    def it_looks_the_label_up_before_listing_issues(self) -> None:
        fetch = FakeGitHub([[]])

        gate.find_blockers(fetch, REPO)

        assert fetch.paths[:2] == [LABEL_PATH, ISSUES_PATH]

    def it_follows_pagination_until_a_short_page(self) -> None:
        full_page = [_issue(number) for number in range(1, gate.PER_PAGE + 1)]
        fetch = FakeGitHub([full_page, [_issue(900)]])

        blockers = gate.find_blockers(fetch, REPO)

        assert len(blockers) == gate.PER_PAGE + 1
        assert blockers[-1] == gate.Blocker(number=900, title='A blocker', is_pull_request=False)
        assert fetch.paths == [LABEL_PATH, ISSUES_PATH, f'{ISSUES_PATH}&page=2']

    def it_counts_a_labeled_pull_request_as_a_blocker_and_marks_it_as_one(self) -> None:
        blockers = gate.find_blockers(FakeGitHub([[_pull_request(12)]]), REPO)

        assert blockers == [gate.Blocker(number=12, title='A blocking PR', is_pull_request=True)]

    def it_cannot_check_when_the_label_does_not_exist(self, http_error: Callable[[int], Exception]) -> None:
        with pytest.raises(gate.CannotCheckError):
            gate.find_blockers(FakeGitHub([[]], label_error=http_error(404)), REPO)

    @pytest.mark.parametrize(
        'failure_kind', [403, 500, 'unreachable'], ids=['forbidden', 'server-error', 'unreachable']
    )
    def it_lets_other_label_lookup_failures_propagate_instead_of_passing(
        self, failure_kind: int | str, http_error: Callable[[int], urllib.error.HTTPError]
    ) -> None:
        error = _transport_error(failure_kind, http_error)

        with pytest.raises(urllib.error.URLError) as raised:
            gate.find_blockers(FakeGitHub([[]], label_error=error), REPO)

        assert raised.value is error

    def it_says_a_missing_label_may_have_been_deleted_or_renamed(self, http_error: Callable[[int], Exception]) -> None:
        with pytest.raises(gate.CannotCheckError, match='deleted or renamed'):
            gate.find_blockers(FakeGitHub([[]], label_error=http_error(404)), REPO)

    @pytest.mark.parametrize('label', [[], 'oops', None, 3], ids=['list', 'string', 'null', 'number'])
    def it_cannot_check_when_the_label_answer_is_not_an_object(self, label: object) -> None:
        fetch = FakeGitHub([[]])
        fetch._label = label

        with pytest.raises(gate.CannotCheckError, match='unexpected shape'):
            gate.find_blockers(fetch, REPO)

    @pytest.mark.parametrize(
        'issues_answer',
        [
            {'message': 'oops'},
            None,
            'oops',
            [None],
            [{'number': 'x', 'title': 'T'}],
            [{'number': True, 'title': 'T'}],
            [{'number': 1, 'title': None}],
        ],
        ids=['object', 'null', 'string', 'null-entry', 'string-number', 'bool-number', 'null-title'],
    )
    def it_cannot_check_when_the_issue_listing_is_malformed(self, issues_answer: object) -> None:
        with pytest.raises(gate.CannotCheckError, match='unexpected shape'):
            gate.find_blockers(FakeGitHub([issues_answer]), REPO)


class _BytesResponse(io.BytesIO):
    """A context-manager response whose body is raw bytes, like ``urlopen`` returns."""

    def __enter__(self) -> _BytesResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.mark.small
class DescribeMain:
    def _main(self, monkeypatch: pytest.MonkeyPatch, fetch: Callable[[str], Any], *argv: str) -> int:
        monkeypatch.setattr(gate, 'github_fetcher', lambda _token: fetch)
        monkeypatch.setenv('GITHUB_TOKEN', 'token')
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)
        monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
        return int(gate.main(list(argv)))

    def it_exits_zero_with_a_one_line_message_when_none_are_open(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = self._main(monkeypatch, FakeGitHub([[]]))

        assert code == 0
        assert capsys.readouterr().out == f'No open release-blocker issues in {REPO}\n'

    def it_exits_one_listing_each_open_blocker_and_how_to_clear_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = self._main(monkeypatch, FakeGitHub([[_issue(7, 'Cache key collides'), _pull_request(12, 'Fix it')]]))

        assert code == 1
        assert capsys.readouterr().out == (
            f'2 open release-blocker item(s) in {REPO}:\n'
            '  #7 Cache key collides\n'
            '  #12 Fix it (pull request)\n'
            'To clear it, fix the problem, or if it should not block the release, remove the release-blocker label '
            'from the issue. The label change stays visible on the issue.\n'
        )

    def it_adds_an_escaped_actions_annotation_when_running_in_github_actions(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A '%' in the title proves '%' is escaped before the newlines, or '%0A' would turn into '%250A'.
        monkeypatch.setenv('GITHUB_ACTIONS', 'true')
        monkeypatch.setattr(gate, 'github_fetcher', lambda _token: FakeGitHub([[_issue(7, '100% broken')]]))
        monkeypatch.setenv('GITHUB_TOKEN', 'token')
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)

        code = gate.main([])

        last_line = capsys.readouterr().out.splitlines()[-1]
        assert code == 1
        assert last_line == (
            f'::error title=Release blocker gate failed::1 open release-blocker item(s) in {REPO}:'
            '%0A  #7 100%25 broken'
            '%0ATo clear it, fix the problem, or if it should not block the release, remove the release-blocker '
            'label from the issue. The label change stays visible on the issue.'
        )

    def it_queries_the_repo_given_on_the_command_line_over_the_environment(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # GITHUB_REPOSITORY is owner/repo; the fake only answers the label for other/name, so reading it would exit 2.
        fetch = FakeGitHub([[]], repo='other/name')

        code = self._main(monkeypatch, fetch, '--repo', 'other/name')

        assert code == 0
        assert fetch.paths == [
            '/repos/other/name/labels/release-blocker',
            '/repos/other/name/issues?state=open&labels=release-blocker&per_page=100',
        ]
        assert capsys.readouterr().out == 'No open release-blocker issues in other/name\n'

    def it_exits_two_when_there_is_no_token(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv('GITHUB_TOKEN', raising=False)
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)

        code = gate.main([])

        assert code == 2
        assert 'GITHUB_TOKEN' in capsys.readouterr().err

    @pytest.mark.parametrize('repo', ['', 'no-slash', 'a/b/c', '/name', 'owner/', 'o/n#', 'o/n?'], ids=repr)
    def it_exits_two_when_the_repository_is_missing_or_malformed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], repo: str
    ) -> None:
        monkeypatch.setenv('GITHUB_TOKEN', 'token')
        monkeypatch.delenv('GITHUB_REPOSITORY', raising=False)

        code = gate.main(['--repo', repo])

        assert code == 2
        assert 'OWNER/NAME' in capsys.readouterr().err

    def it_exits_two_when_the_label_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        http_error: Callable[[int], Exception],
    ) -> None:
        code = self._main(monkeypatch, FakeGitHub([[]], label_error=http_error(404)))

        assert code == 2
        assert 'deleted or renamed' in capsys.readouterr().err

    @pytest.mark.parametrize(
        'failure_kind', [500, 403, 'unreachable'], ids=['server-error', 'forbidden', 'unreachable']
    )
    def it_exits_two_when_the_issue_listing_request_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        http_error: Callable[[int], urllib.error.HTTPError],
        failure_kind: int | str,
    ) -> None:
        error = _transport_error(failure_kind, http_error)

        def fetch(path: str) -> Any:
            if path == LABEL_PATH:
                return {'name': 'release-blocker'}
            raise error

        code = self._main(monkeypatch, fetch)

        assert code == 2
        assert capsys.readouterr().err.startswith('error: GitHub API request failed: ')

    def it_exits_two_when_the_issue_listing_is_not_a_list(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = self._main(monkeypatch, FakeGitHub([{'message': 'Bad credentials'}]))

        assert code == 2
        assert 'unexpected shape' in capsys.readouterr().err

    def it_exits_two_when_the_body_is_not_valid_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv('GITHUB_TOKEN', 'token')
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)
        monkeypatch.setattr(gate.urllib.request, 'urlopen', lambda *_a, **_k: _BytesResponse(b'<html>'))

        code = gate.main([])

        assert code == 2
        assert capsys.readouterr().err.startswith('error: GitHub API request failed: ')

    def it_exits_two_when_the_api_root_is_not_https(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv('GITHUB_TOKEN', 'token')
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)
        monkeypatch.setenv('GITHUB_API_URL', 'http://api.github.com')

        code = gate.main([])

        assert code == 2
        assert 'GITHUB_API_URL must be an https URL' in capsys.readouterr().err

    def it_exits_two_not_a_traceback_when_the_repository_is_not_ascii(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv('GITHUB_TOKEN', 'token')

        code = gate.main(['--repo', 'ownér/repo'])

        assert code == 2
        assert capsys.readouterr().err.startswith('error: ')

    @pytest.mark.parametrize('flag', ['--skip', '--force', '--no-check'])
    def it_has_no_flag_that_skips_the_check(self, flag: str, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as raised:
            gate.main([flag])

        assert raised.value.code == 2
        assert f'unrecognized arguments: {flag}' in capsys.readouterr().err
