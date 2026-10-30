"""Tests for scripts/check_verdict_change.py -- the CI gate on verdict changes without a cache-version bump (#876)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_verdict_change.py'


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_verdict_change', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['check_verdict_change'] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

BASE_MARKERS = checker.Markers(cache_version='1', runner_fidelity_version='rf21')
ZAPPED = {'sample.py:10 comparison: >= to >': 'zapped'}
SURVIVED = {'sample.py:10 comparison: >= to >': 'survived'}


@pytest.mark.small
class DescribeVerdictCheck:
    def it_passes_when_every_verdict_is_unchanged(self) -> None:
        failure = checker.check_verdicts(ZAPPED, ZAPPED, BASE_MARKERS, BASE_MARKERS)

        assert failure is None

    def it_fails_when_a_verdict_changed_and_no_marker_was_raised(self) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, BASE_MARKERS)

        assert failure == (
            'Gremlin verdicts on the sample project changed, but neither cache marker was raised, so users with '
            'a warm cache would keep the old verdicts:\n'
            'changed: sample.py:10 comparison: >= to >: zapped -> survived\n'
            f'{checker.RUNNER_FIDELITY_ADVICE}'
        )

    @pytest.mark.parametrize(
        'head_markers',
        [
            checker.Markers(cache_version='2', runner_fidelity_version='rf21'),
            checker.Markers(cache_version='1', runner_fidelity_version='rf22'),
        ],
        ids=['cache-version', 'runner-fidelity-version'],
    )
    def it_passes_when_a_verdict_changed_and_a_marker_was_raised(self, head_markers: object) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, head_markers)

        assert failure is None

    def it_names_a_gremlin_whose_verdict_changed_with_both_verdicts(self) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, BASE_MARKERS)

        assert 'sample.py:10 comparison: >= to >: zapped -> survived' in failure

    def it_asks_for_the_runner_fidelity_version_when_only_verdicts_changed(self) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, BASE_MARKERS)

        assert failure.endswith(checker.RUNNER_FIDELITY_ADVICE)

    def it_names_a_gremlin_that_only_the_head_code_creates(self) -> None:
        head = {**ZAPPED, 'sample.py:12 boolean: and to or': 'zapped'}

        failure = checker.check_verdicts(ZAPPED, head, BASE_MARKERS, BASE_MARKERS)

        assert 'added: sample.py:12 boolean: and to or' in failure

    def it_names_a_gremlin_that_the_head_code_no_longer_creates(self) -> None:
        base = {**ZAPPED, 'sample.py:12 boolean: and to or': 'zapped'}

        failure = checker.check_verdicts(base, ZAPPED, BASE_MARKERS, BASE_MARKERS)

        assert 'removed: sample.py:12 boolean: and to or' in failure

    def it_asks_for_the_cache_version_when_the_set_of_gremlins_changed(self) -> None:
        head = {**ZAPPED, 'sample.py:12 boolean: and to or': 'zapped'}

        failure = checker.check_verdicts(ZAPPED, head, BASE_MARKERS, BASE_MARKERS)

        assert failure.endswith(checker.CACHE_VERSION_ADVICE)

    def it_fails_when_neither_run_produced_a_gremlin(self) -> None:
        failure = checker.check_verdicts({}, {}, BASE_MARKERS, BASE_MARKERS)

        assert failure == checker.NO_GREMLINS_MESSAGE

    @pytest.mark.parametrize(
        ('head_markers', 'lowered'),
        [
            (checker.Markers(cache_version='0', runner_fidelity_version='rf21'), 'CACHE_VERSION'),
            (checker.Markers(cache_version='1', runner_fidelity_version='rf20'), 'RUNNER_FIDELITY_VERSION'),
        ],
        ids=['cache-version', 'runner-fidelity-version'],
    )
    def it_fails_when_a_marker_was_lowered_with_a_verdict_change(self, head_markers: object, lowered: str) -> None:
        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, head_markers)

        assert failure == checker.LOWERED_MARKER_MESSAGE.format(lowered=lowered)

    def it_fails_when_a_marker_was_lowered_even_if_no_verdict_changed(self) -> None:
        lowered = checker.Markers(cache_version='0', runner_fidelity_version='rf21')

        failure = checker.check_verdicts(ZAPPED, ZAPPED, BASE_MARKERS, lowered)

        assert failure == checker.LOWERED_MARKER_MESSAGE.format(lowered='CACHE_VERSION')

    def it_fails_when_one_marker_was_raised_and_the_other_lowered(self) -> None:
        mixed = checker.Markers(cache_version='2', runner_fidelity_version='rf20')

        failure = checker.check_verdicts(ZAPPED, SURVIVED, BASE_MARKERS, mixed)

        assert failure == checker.LOWERED_MARKER_MESSAGE.format(lowered='RUNNER_FIDELITY_VERSION')


def _entry(line_number: int, status: str, description: str = '>= to >') -> dict[str, object]:
    return {
        'gremlin_id': f'sample_ab12_g{line_number:03d}',
        'file_path': '/runner/work/sample/sample.py',
        'line_number': line_number,
        'status': status,
        'operator': 'comparison',
        'description': description,
    }


@pytest.mark.small
class DescribeVerdictsFromReport:
    def it_keys_each_verdict_by_the_path_inside_the_sample_and_the_mutation(self) -> None:
        report = {'results': [_entry(10, 'zapped')]}

        verdicts = checker.verdicts_from_report(report, Path('/runner/work/sample'))

        assert verdicts == {'sample.py:10 comparison: >= to >': 'zapped'}

    def it_numbers_gremlins_that_share_a_line_operator_and_description(self) -> None:
        report = {'results': [_entry(10, 'zapped', 'boundary shift'), _entry(10, 'survived', 'boundary shift')]}

        verdicts = checker.verdicts_from_report(report, Path('/runner/work/sample'))

        assert verdicts == {
            'sample.py:10 comparison: boundary shift': 'zapped',
            'sample.py:10 comparison: boundary shift #2': 'survived',
        }


@pytest.mark.medium
class DescribeSymlinkedSampleRoot:
    def it_keys_verdicts_when_the_sample_root_is_reached_through_a_symlink(self, tmp_path: Path) -> None:
        # macOS: tempfile.gettempdir() is /var/..., a symlink to /private/var/..., and the plugin reports the
        # resolved path.
        real = tmp_path / 'real'
        real.mkdir()
        link = tmp_path / 'link'
        link.symlink_to(real, target_is_directory=True)
        entry = {**_entry(10, 'zapped'), 'file_path': str(real / 'sample.py')}

        verdicts = checker.verdicts_from_report({'results': [entry]}, link)

        assert verdicts == ZAPPED


GUARDED = frozenset({'src/pytest_gremlins/plugin.py', 'src/pytest_gremlins/config.py'})


@pytest.mark.small
class DescribeGuardedChanges:
    def it_keeps_a_changed_path_that_the_guard_covers(self) -> None:
        changes = checker.guarded_changes(['src/pytest_gremlins/plugin.py', 'docs/index.md'], [], GUARDED)

        assert changes == ['src/pytest_gremlins/plugin.py']

    def it_drops_a_changed_package_file_that_the_guard_excludes(self) -> None:
        changes = checker.guarded_changes(['src/pytest_gremlins/reporting/html.py'], [], GUARDED)

        assert changes == []

    def it_keeps_a_deleted_package_module_because_the_head_guard_cannot_list_it(self) -> None:
        deleted = ['src/pytest_gremlins/old_module.py']

        changes = checker.guarded_changes(deleted, deleted, GUARDED)

        assert changes == ['src/pytest_gremlins/old_module.py']

    def it_drops_a_deleted_file_outside_the_package_sources(self) -> None:
        deleted = ['tests/test_old.py', 'src/pytest_gremlins/py.typed']

        changes = checker.guarded_changes(deleted, deleted, GUARDED)

        assert changes == []

    def it_counts_an_edit_to_the_guard_file_as_a_guarded_change(self) -> None:
        # One PR can add a module to EXCLUDED_FROM_GUARD and change it; the head guard no longer lists the module.
        changed = ['tests/cache/test_cache_version_guard.py', 'src/pytest_gremlins/newly_excluded.py']

        changes = checker.guarded_changes(changed, [], GUARDED)

        assert changes == ['tests/cache/test_cache_version_guard.py']


@pytest.mark.medium
class DescribeGuardedPathsFromTheGuard:
    def it_lists_package_sources_from_the_guard_file_set(self) -> None:
        assert 'src/pytest_gremlins/plugin.py' in checker.guarded_repo_paths()

    def it_leaves_out_what_the_guard_excludes(self) -> None:
        assert 'src/pytest_gremlins/reporting/html.py' not in checker.guarded_repo_paths()


MODULE_BODY = ''.join(f'value_{index} = {index}\n' for index in range(30))


def _git(repo: Path, *args: str) -> None:
    subprocess.run(['git', '-c', 'user.name=qa', '-c', 'user.email=qa@example.com', *args], cwd=repo, check=True)  # noqa: S607


@pytest.fixture
def repo_with_module_moved_out_of_the_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # A throwaway repository: isolate it from the developer's global git config, as test_verify_release_tag does.
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    module = tmp_path / 'src' / 'pytest_gremlins' / 'moved.py'
    module.parent.mkdir(parents=True)
    module.write_text(MODULE_BODY, encoding='utf-8')
    _git(tmp_path, 'init', '--quiet')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, 'commit', '--quiet', '-m', 'base')
    (tmp_path / 'tools').mkdir()
    _git(tmp_path, 'mv', 'src/pytest_gremlins/moved.py', 'tools/moved.py')
    with (tmp_path / 'tools' / 'moved.py').open('a', encoding='utf-8') as moved:
        moved.write('extra = 1\n')
    _git(tmp_path, 'commit', '--quiet', '-am', 'move the module out of the package')
    monkeypatch.setattr(checker, 'REPO_ROOT', tmp_path)
    return tmp_path


@pytest.mark.medium
class DescribeModuleMovedOutOfThePackage:
    @pytest.mark.usefixtures('repo_with_module_moved_out_of_the_package')
    def it_counts_the_old_path_like_a_deleted_package_module(self) -> None:
        changed = checker._git_diff_names('HEAD~1')
        deleted = checker._git_diff_names('HEAD~1', '--diff-filter=D')

        changes = checker.guarded_changes(changed, deleted, set())

        assert 'src/pytest_gremlins/moved.py' in changes


def _write_run(path: Path, verdicts: dict[str, str], cache_version: str = '1') -> Path:
    path.write_text(
        json.dumps({'cache_version': cache_version, 'runner_fidelity_version': 'rf21', 'verdicts': verdicts}),
        encoding='utf-8',
    )
    return path


@pytest.mark.medium
class DescribeCompareCommand:
    def it_exits_zero_when_no_verdict_changed(self, tmp_path: Path) -> None:
        base = _write_run(tmp_path / 'base.json', ZAPPED)
        head = _write_run(tmp_path / 'head.json', ZAPPED)

        assert checker.main(['compare', str(base), str(head)]) == 0

    def it_exits_one_and_names_the_gremlin_when_a_verdict_changed_without_a_bump(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = _write_run(tmp_path / 'base.json', ZAPPED)
        head = _write_run(tmp_path / 'head.json', SURVIVED)

        exit_code = checker.main(['compare', str(base), str(head)])

        assert (exit_code, 'zapped -> survived' in capsys.readouterr().out) == (1, True)

    def it_exits_zero_when_a_verdict_changed_with_a_bump(self, tmp_path: Path) -> None:
        base = _write_run(tmp_path / 'base.json', ZAPPED)
        head = _write_run(tmp_path / 'head.json', SURVIVED, cache_version='2')

        assert checker.main(['compare', str(base), str(head)]) == 0

    def it_exits_one_when_neither_run_produced_a_gremlin(self, tmp_path: Path) -> None:
        base = _write_run(tmp_path / 'base.json', {})
        head = _write_run(tmp_path / 'head.json', {})

        assert checker.main(['compare', str(base), str(head)]) == checker.EXIT_VERDICT_CHANGED


@pytest.mark.medium
class DescribeRunCommand:
    def it_exits_two_when_the_report_has_no_results(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def write_empty_report(*_args: object, cwd: Path, **_kwargs: object) -> object:
            report = cwd / checker.REPORT_PATH
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({'results': []}), encoding='utf-8')
            return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

        monkeypatch.setattr(checker.subprocess, 'run', write_empty_report)
        sample = tmp_path / 'sample'
        sample.mkdir()
        out = tmp_path / 'run.json'

        exit_code = checker.main(
            ['run', '--out', str(out), '--sample', str(sample), '--workdir', str(tmp_path / 'work')]
        )

        assert (exit_code, out.exists()) == (checker.EXIT_NO_REPORT, False)


@pytest.fixture(scope='module')
def sample_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, str], list[dict[str, object]]]:
    workdir = tmp_path_factory.mktemp('verdict-run') / 'sample'
    out = workdir.parent / 'run.json'
    assert checker.main(['run', '--out', str(out), '--workdir', str(workdir)]) == 0
    report = json.loads((workdir / checker.REPORT_PATH).read_text(encoding='utf-8'))
    return json.loads(out.read_text(encoding='utf-8'))['verdicts'], report['results']


SampleRun = tuple[dict[str, str], list[dict[str, object]]]


@pytest.mark.large
class DescribeSampleRun:
    """The sample drives every verdict path the CI job is meant to watch."""

    @pytest.mark.parametrize('status', ['zapped', 'survived', 'timeout'])
    def it_produces_each_verdict(self, sample_run: SampleRun, status: str) -> None:
        verdicts, _ = sample_run

        assert status in verdicts.values()

    def it_zaps_a_gremlin_that_stops_collection(self, sample_run: SampleRun) -> None:
        _, results = sample_run

        assert '<collection>' in {entry.get('killing_test') for entry in results}

    def it_keeps_gremlins_that_only_a_rerun_test_covers_alive(self, sample_run: SampleRun) -> None:
        verdicts, _ = sample_run

        assert verdicts['sample.py:43 comparison: <= to >'] == 'survived'
