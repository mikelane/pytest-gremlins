"""Tests for scripts/check_ci_passed.py -- the release gate that requires a passing main CI run for the tagged commit.

The GitHub API is replaced by a fake ``fetch`` that serves canned JSON, so no test touches the network.
"""

from __future__ import annotations

from collections.abc import Callable
import http.client
import importlib.util
import io
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any
import urllib.error

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_ci_passed.py'
CI_WORKFLOW = Path(__file__).resolve().parents[2] / '.github' / 'workflows' / 'ci.yml'
SHA = 'a' * 40
REPO = 'owner/repo'


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_ci_passed', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ci = _load_script()


def _run(run_id: int = 1, *, status: str = 'completed', conclusion: str | None = 'success') -> dict[str, Any]:
    return {'id': run_id, 'status': status, 'conclusion': conclusion, 'html_url': f'https://example/runs/{run_id}'}


def _jobs(*, overrides: dict[str, str] | None = None, omit: set[str] | None = None) -> list[dict[str, str]]:
    conclusions = overrides or {}
    return [
        {'name': name, 'conclusion': conclusions.get(name, 'success')}
        for name in ci.EXPECTED_TEST_JOBS
        if name not in (omit or set())
    ] + [{'name': 'Lint', 'conclusion': 'success'}]


class FakeGitHub:
    """Serves ``/runs`` and ``/jobs`` listings; each ``runs`` entry is one poll's answer (the last repeats)."""

    def __init__(self, polls: list[list[dict[str, Any]]], jobs: dict[int, list[dict[str, str]]]) -> None:
        self._polls = polls
        self._jobs = jobs
        self.paths: list[str] = []
        self.run_polls = 0

    def __call__(self, path: str) -> Any:
        self.paths.append(path)
        if '/jobs' in path:
            run_id = int(path.split('/runs/')[1].split('/', maxsplit=1)[0])
            page = int(re.search(r'[?&]page=(\d+)', path).group(1))  # type: ignore[union-attr]
            jobs = self._jobs[run_id]
            per_page = ci.PER_PAGE
            return {'total_count': len(jobs), 'jobs': jobs[(page - 1) * per_page : page * per_page]}
        answer = self._polls[min(self.run_polls, len(self._polls) - 1)]
        self.run_polls += 1
        return {'total_count': len(answer), 'workflow_runs': answer}


class FailsOnceThenServes:
    """Raises a transient error on the first call (``URLError`` by default), then delegates to ``fetch``."""

    def __init__(self, fetch: Callable[[str], Any], error: Exception | None = None) -> None:
        self._fetch = fetch
        self._error = error or urllib.error.URLError('boom')
        self.calls = 0

    def __call__(self, path: str) -> Any:
        self.calls += 1
        if self.calls == 1:
            raise self._error
        return self._fetch(path)


def _always_unreachable(_path: str) -> Any:
    raise urllib.error.URLError('boom')


def _filler_jobs(count: int) -> list[dict[str, str]]:
    return [{'name': f'Filler {n}', 'conclusion': 'success'} for n in range(count)]


def _ci_jobs() -> dict[str, Any]:
    return yaml.safe_load(CI_WORKFLOW.read_text())['jobs']  # type: ignore[no-any-return]


def _ci_matrix_job_names() -> set[str]:
    jobs = _ci_jobs()
    test_matrix = jobs['test']['strategy']['matrix']
    python_names = {
        f'Test (Python {version}, {os_name})'
        for os_name in test_matrix['os']
        for version in test_matrix['python-version']
    }
    pytest_names = {f'Test (pytest {version})' for version in jobs['pytest-compat']['strategy']['matrix']['pytest']}
    return python_names | pytest_names


def _fetch_for(runs: list[dict[str, Any]], jobs: list[dict[str, str]] | None = None) -> FakeGitHub:
    return FakeGitHub([runs], {run['id']: jobs if jobs is not None else _jobs() for run in runs})


@pytest.mark.small
class DescribeCheckCi:
    def it_passes_when_the_run_succeeded_and_every_test_job_succeeded(self) -> None:
        outcome = ci.check_ci(_fetch_for([_run()]), REPO, SHA)

        assert outcome.state == 'passed'

    def it_looks_the_run_up_by_sha_and_push_event(self) -> None:
        fetch = _fetch_for([_run()])

        ci.check_ci(fetch, REPO, SHA)

        assert fetch.paths[0] == f'/repos/{REPO}/actions/workflows/ci.yml/runs?head_sha={SHA}&event=push&per_page=100'

    def it_reports_a_missing_run_when_none_exists_yet(self) -> None:
        outcome = ci.check_ci(_fetch_for([]), REPO, SHA)

        assert outcome.state == 'missing'
        assert SHA in outcome.message

    def it_is_pending_while_the_run_is_in_progress(self) -> None:
        outcome = ci.check_ci(_fetch_for([_run(status='in_progress', conclusion=None)]), REPO, SHA)

        assert outcome.state == 'pending'

    @pytest.mark.parametrize('conclusion', ['failure', 'cancelled', 'skipped', 'timed_out'])
    def it_fails_when_the_run_did_not_succeed(self, conclusion: str) -> None:
        outcome = ci.check_ci(_fetch_for([_run(conclusion=conclusion)]), REPO, SHA)

        assert outcome.state == 'failed'
        assert SHA in outcome.message
        assert conclusion in outcome.message

    def it_fails_when_a_test_job_was_skipped_even_though_the_run_succeeded(self) -> None:
        skipped = 'Test (Python 3.12, windows-latest)'
        fetch = _fetch_for([_run()], _jobs(overrides={skipped: 'skipped'}))

        outcome = ci.check_ci(fetch, REPO, SHA)

        assert outcome.state == 'failed'
        assert skipped in outcome.message
        assert 'skipped' in outcome.message

    def it_fails_when_every_test_job_is_missing_as_when_the_change_filter_skipped_them(self) -> None:
        fetch = _fetch_for([_run()], [{'name': 'Lint', 'conclusion': 'success'}])

        outcome = ci.check_ci(fetch, REPO, SHA)

        assert outcome.state == 'failed'
        assert 'Test (pytest 8.4.2)' in outcome.message

    def it_fails_when_one_expected_test_job_is_missing(self) -> None:
        missing = 'Test (pytest latest)'
        fetch = _fetch_for([_run()], _jobs(omit={missing}))

        outcome = ci.check_ci(fetch, REPO, SHA)

        assert outcome.state == 'failed'
        assert missing in outcome.message

    def it_fails_when_a_test_job_failed(self) -> None:
        failed = 'Test (Python 3.11, ubuntu-latest)'

        outcome = ci.check_ci(_fetch_for([_run()], _jobs(overrides={failed: 'failure'})), REPO, SHA)

        assert outcome.state == 'failed'
        assert failed in outcome.message

    def it_passes_when_any_run_for_the_sha_qualifies(self) -> None:
        failed_run = _run(1, conclusion='failure')
        good_run = _run(2)
        fetch = FakeGitHub([[failed_run, good_run]], {1: _jobs(), 2: _jobs()})

        outcome = ci.check_ci(fetch, REPO, SHA)

        assert outcome.state == 'passed'

    def it_stays_pending_when_one_run_failed_but_another_is_still_running(self) -> None:
        runs = [_run(1, conclusion='failure'), _run(2, status='queued', conclusion=None)]

        outcome = ci.check_ci(FakeGitHub([runs], {1: _jobs()}), REPO, SHA)

        assert outcome.state == 'pending'

    def it_reads_every_page_of_jobs(self) -> None:
        many = _filler_jobs(ci.PER_PAGE) + _jobs()
        fetch = FakeGitHub([[_run()]], {1: many})

        outcome = ci.check_ci(fetch, REPO, SHA)

        assert outcome.state == 'passed'
        assert f'/repos/{REPO}/actions/runs/1/jobs?filter=latest&per_page={ci.PER_PAGE}&page=2' in fetch.paths

    def it_ignores_jobs_that_are_not_part_of_the_test_matrix(self) -> None:
        jobs = [*_jobs(), {'name': 'Security Audit', 'conclusion': 'failure'}]

        outcome = ci.check_ci(_fetch_for([_run()], jobs), REPO, SHA)

        assert outcome.state == 'passed'


@pytest.mark.small
class DescribeWaitForCi:
    def _wait(self, fetch: Callable[[str], Any], *, timeout: float = 100.0) -> Any:
        clock = {'now': 0.0}

        def sleep(seconds: float) -> None:
            clock['now'] += seconds

        return ci.wait_for_ci(
            fetch,
            REPO,
            SHA,
            timeout_seconds=timeout,
            interval_seconds=10.0,
            sleep=sleep,
            monotonic=lambda: clock['now'],
        )

    def it_waits_for_an_in_progress_run_to_finish(self) -> None:
        running = [_run(status='in_progress', conclusion=None)]
        fetch = FakeGitHub([running, running, [_run()]], {1: _jobs()})

        outcome = self._wait(fetch)

        assert outcome.state == 'passed'
        assert fetch.run_polls == 3

    def it_fails_without_waiting_when_the_run_already_failed(self) -> None:
        fetch = FakeGitHub([[_run(conclusion='failure')]], {1: _jobs()})

        outcome = self._wait(fetch)

        assert outcome.state == 'failed'
        assert fetch.run_polls == 1

    def it_fails_naming_the_sha_when_no_run_appears_within_the_grace_period(self) -> None:
        fetch = FakeGitHub([[]], {})

        outcome = self._wait(fetch, timeout=ci.DEFAULT_TIMEOUT_SECONDS)

        assert outcome.state == 'failed'
        assert SHA in outcome.message
        assert 'has no main CI run' in outcome.message

    def it_stops_polling_for_a_missing_run_after_the_grace_period_not_the_long_timeout(self) -> None:
        fetch = FakeGitHub([[]], {})

        self._wait(fetch, timeout=ci.DEFAULT_TIMEOUT_SECONDS)

        assert fetch.run_polls <= ci.NO_RUN_GRACE_SECONDS / 10.0 + 1

    def it_keeps_the_grace_period_at_ten_minutes(self) -> None:
        assert ci.NO_RUN_GRACE_SECONDS == 10 * 60

    def it_waits_for_a_run_that_appears_within_the_grace_period(self) -> None:
        late = [[], [], [_run(status='queued', conclusion=None)], [_run()]]

        outcome = self._wait(FakeGitHub(late, {1: _jobs()}))

        assert outcome.state == 'passed'

    def it_keeps_waiting_past_the_grace_period_for_a_run_that_exists(self) -> None:
        running = [_run(status='in_progress', conclusion=None)]
        polls = [[], *([running] * 100), [_run()]]

        outcome = self._wait(FakeGitHub(polls, {1: _jobs()}), timeout=ci.DEFAULT_TIMEOUT_SECONDS)

        assert outcome.state == 'passed'

    def it_restarts_the_grace_period_when_a_run_disappears_after_appearing(self) -> None:
        running = [_run(status='in_progress', conclusion=None)]
        polls = [[], running, [], [_run()]]

        outcome = self._wait(FakeGitHub(polls, {1: _jobs()}))

        assert outcome.state == 'passed'

    def it_fails_when_the_run_never_appears_before_a_short_timeout(self) -> None:
        outcome = self._wait(FakeGitHub([[]], {}), timeout=30.0)

        assert outcome.state == 'failed'
        assert SHA in outcome.message

    def it_fails_when_the_run_is_still_in_progress_at_the_timeout(self) -> None:
        running = [_run(status='in_progress', conclusion=None)]

        outcome = self._wait(FakeGitHub([running], {1: _jobs()}), timeout=30.0)

        assert outcome.state == 'failed'
        assert 'timed out' in outcome.message

    def it_retries_a_transient_api_error(self) -> None:
        flaky = FailsOnceThenServes(_fetch_for([_run()]))

        outcome = self._wait(flaky)

        assert outcome.state == 'passed'
        assert flaky.calls > 1

    @pytest.mark.parametrize(
        'error',
        [http.client.IncompleteRead(b'{"workflow_ru'), http.client.BadStatusLine('x'), http.client.ResponseNotReady()],
        ids=['IncompleteRead', 'BadStatusLine', 'ResponseNotReady'],
    )
    def it_retries_an_http_client_error_like_any_other_network_error(self, error: Exception) -> None:
        flaky = FailsOnceThenServes(_fetch_for([_run()]), error)

        outcome = self._wait(flaky)

        assert outcome.state == 'passed'
        assert flaky.calls > 1

    def it_raises_cannot_check_after_repeated_api_errors(self) -> None:
        with pytest.raises(ci.CannotCheckError):
            self._wait(_always_unreachable)


@pytest.mark.medium
class DescribeExpectedTestJobs:
    """The expected job names must track the matrices in ci.yml, so a matrix change cannot silently shrink the gate."""

    def it_matches_the_job_names_the_ci_matrices_produce(self) -> None:
        assert set(ci.EXPECTED_TEST_JOBS) == _ci_matrix_job_names()

    @pytest.mark.parametrize('job', ['test', 'pytest-compat'])
    def it_requires_the_ci_matrix_to_have_no_include_or_exclude_entries(self, job: str) -> None:
        matrix = _ci_jobs()[job]['strategy']['matrix']

        assert {'include', 'exclude'}.isdisjoint(matrix)

    def it_has_no_duplicates(self) -> None:
        assert len(set(ci.EXPECTED_TEST_JOBS)) == len(ci.EXPECTED_TEST_JOBS)

    def it_pins_the_job_name_templates_in_ci_yml(self) -> None:
        jobs = _ci_jobs()

        assert jobs['test']['name'] == 'Test (Python ${{ matrix.python-version }}, ${{ matrix.os }})'
        assert jobs['pytest-compat']['name'] == 'Test (pytest ${{ matrix.pytest }})'


class _BytesResponse(io.BytesIO):
    """A context-manager response whose body is raw bytes, like ``urlopen`` returns."""

    def __enter__(self) -> _BytesResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.mark.small
class DescribeMain:
    def _main(self, monkeypatch: pytest.MonkeyPatch, fetch: Callable[[str], Any], *argv: str) -> int:
        monkeypatch.setattr(ci, 'github_fetcher', lambda _token: fetch)
        monkeypatch.setenv('GITHUB_TOKEN', 'token')
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)
        return int(ci.main([SHA, '--timeout', '0', '--interval', '0', *argv]))

    def it_exits_zero_when_ci_passed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._main(monkeypatch, _fetch_for([_run()])) == 0

    def it_exits_one_and_names_the_sha_when_ci_did_not_pass(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = self._main(monkeypatch, _fetch_for([_run(conclusion='failure')]))

        assert code == 1
        assert SHA in capsys.readouterr().out

    def it_exits_two_when_the_api_cannot_be_reached(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = self._main(monkeypatch, _always_unreachable)

        assert code == 2
        assert capsys.readouterr().err.startswith('error: ')

    def it_exits_two_when_the_api_body_is_not_valid_utf8(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv('GITHUB_TOKEN', 'token')
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)
        monkeypatch.setattr(ci.urllib.request, 'urlopen', lambda *_a, **_k: _BytesResponse(b'{"x": "\xff"}'))

        code = ci.main([SHA, '--timeout', '0', '--interval', '0'])

        assert code == 2
        assert capsys.readouterr().err.startswith('error: ')

    @pytest.mark.parametrize(
        'runs_answer',
        [
            {'workflow_runs': None},
            {'workflow_runs': 'oops'},
            {'workflow_runs': [None]},
            {'workflow_runs': [{'id': 'abc', 'status': 'completed', 'conclusion': 'success'}]},
            {'workflow_runs': [{'id': None, 'status': 'completed', 'conclusion': 'success'}]},
            {'workflow_runs': [{'id': True, 'status': 'completed', 'conclusion': 'success'}]},
            ['not', 'an', 'object'],
        ],
        ids=['null-runs', 'string-runs', 'null-run', 'string-id', 'null-id', 'bool-id', 'list-answer'],
    )
    def it_exits_two_when_the_runs_answer_has_an_unexpected_shape(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], runs_answer: Any
    ) -> None:
        code = self._main(monkeypatch, lambda _path: runs_answer)

        assert code == 2
        assert 'unexpected' in capsys.readouterr().err

    @pytest.mark.parametrize(
        'jobs_answer',
        [{'jobs': None}, {'jobs': 'oops'}, {'jobs': [None]}, {'jobs': [{'conclusion': 'success'}]}, 'nope'],
        ids=['null-jobs', 'string-jobs', 'null-job', 'nameless-job', 'string-answer'],
    )
    def it_exits_two_when_the_jobs_answer_has_an_unexpected_shape(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], jobs_answer: Any
    ) -> None:
        runs_fetch = _fetch_for([_run()])

        def fetch(path: str) -> Any:
            return jobs_answer if '/jobs' in path else runs_fetch(path)

        code = self._main(monkeypatch, fetch)

        assert code == 2
        assert 'unexpected' in capsys.readouterr().err

    def it_exits_two_naming_the_token_when_no_token_is_available(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv('GITHUB_TOKEN', raising=False)
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)

        code = ci.main([SHA])

        assert code == 2
        assert 'GITHUB_TOKEN' in capsys.readouterr().err

    def it_exits_two_naming_the_bad_value_for_a_malformed_sha(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv('GITHUB_TOKEN', 'token')
        monkeypatch.setenv('GITHUB_REPOSITORY', REPO)

        code = ci.main(['main'])

        assert code == 2
        assert "'main' is not a full 40-character commit SHA" in capsys.readouterr().err
