"""Gremlin runs inherit pytest-rerunfailures settings, so a flaky test cannot falsely zap a mutant (refs #546).

The flaky test fails on its first call in every fresh process and passes on the rerun.  The
baseline passes only because it is rerun.  If a per-gremlin subprocess did not rerun it, the flake
would fail the subprocess and every gremlin would be zapped, including the ones the test cannot
catch.  The test is deliberately weak: it leaves some mutants of ``classify`` alive.
"""

from __future__ import annotations

import re

import pytest

_SAMPLE = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

_FLAKY_WEAK_TEST = """
from sample import classify

calls = []


def test_big():
    calls.append(1)
    assert len(calls) > 1, 'flaky: fails on the first call in every fresh process'
    assert classify(11) == 'big'
"""

_FLAKY_STRONG_TEST = """
from sample import classify

calls = []


def test_big():
    calls.append(1)
    assert len(calls) > 1, 'flaky: fails on the first call in every fresh process'
    assert classify(11) == 'big'
    assert classify(10) == 'small'
"""

_GREMLIN_ARGS = (
    '--gremlins',
    '--gremlin-targets=sample.py',
    '--gremlin-operators=comparison',
    '-p',
    'no:cacheprovider',
)


def _verdicts(output: str) -> dict[str, int]:
    def count(label: str) -> int:
        match = re.search(rf'{label}: (\d+) gremlins', output)
        return int(match.group(1)) if match else 0

    return {label: count(label) for label in ('Zapped', 'Survived', 'Error')}


def _run_gremlins(pytester: pytest.Pytester, *extra_args: str, tests: str = _FLAKY_WEAK_TEST) -> pytest.RunResult:
    pytester.makepyfile(sample=_SAMPLE)
    pytester.makepyfile(test_sample=tests)
    return pytester.runpytest_subprocess(*_GREMLIN_ARGS, *extra_args)


def _survivors(result: pytest.RunResult) -> int:
    return _verdicts(result.stdout.str())['Survived']


@pytest.mark.medium
class DescribeRerunOptionsOnTheCommandLine:
    @pytest.mark.parametrize(
        'mode_args',
        [(), ('--gremlin-parallel', '--gremlin-workers=2'), ('--gremlin-batch',)],
        ids=['sequential', 'parallel', 'batch'],
    )
    def it_leaves_the_mutants_the_flaky_test_cannot_catch_alive(
        self, pytester_with_markers: pytest.Pytester, mode_args: tuple[str, ...]
    ) -> None:
        result = _run_gremlins(pytester_with_markers, '--reruns', '2', *mode_args)

        assert _survivors(result) > 0

    def it_still_zaps_mutants_that_a_flaky_test_catches_on_every_attempt(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        verdicts = _verdicts(
            _run_gremlins(pytester_with_markers, '--reruns', '2', tests=_FLAKY_STRONG_TEST).stdout.str()
        )

        assert (verdicts['Survived'], verdicts['Zapped'] > 0) == (0, True)

    def it_reaches_the_gremlin_runs_of_an_xdist_session(self, pytester_with_markers: pytest.Pytester) -> None:
        result = _run_gremlins(pytester_with_markers, '--reruns', '2', '-n', '2')

        assert _survivors(result) > 0

    def it_reaches_the_gremlin_runs_from_an_argument_file(self, pytester_with_markers: pytest.Pytester) -> None:
        (pytester_with_markers.path / 'rerun.args').write_text('--reruns=2\n', encoding='utf-8')

        result = _run_gremlins(pytester_with_markers, '@rerun.args')

        assert _survivors(result) > 0

    def it_wins_over_a_rerun_count_in_addopts(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = --reruns 0\n')

        result = _run_gremlins(pytester_with_markers, '--reruns', '2')

        assert _survivors(result) > 0


@pytest.mark.medium
class DescribeRerunOptionsInAddopts:
    def it_leaves_the_mutants_the_flaky_test_cannot_catch_alive(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makeini('[pytest]\naddopts = --reruns 2\n')

        result = _run_gremlins(pytester_with_markers)

        assert _survivors(result) > 0


@pytest.mark.medium
class DescribeProjectsWithoutRerunOptions:
    def it_completes_without_rerun_flags_or_a_warning(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(test_sample=_FLAKY_WEAK_TEST.replace('len(calls) > 1', 'True'))

        result = pytester_with_markers.runpytest_subprocess(*_GREMLIN_ARGS)

        assert result.ret == 0
        assert '--reruns' not in result.stderr.str()
        assert 'needed a rerun' not in result.stderr.str()


@pytest.mark.medium
class DescribeBaselineRerunWarning:
    def it_warns_once_naming_the_test_that_needed_a_rerun(self, pytester_with_markers: pytest.Pytester) -> None:
        result = _run_gremlins(pytester_with_markers, '--reruns', '2')

        warnings = [line for line in result.stderr.lines if 'needed a rerun' in line]

        assert len(warnings) == 1
        assert 'test_sample.py::test_big' in warnings[0]

    def it_stays_silent_when_no_baseline_test_was_rerun(self, pytester_with_markers: pytest.Pytester) -> None:
        result = _run_gremlins(
            pytester_with_markers, '--reruns', '2', tests=_FLAKY_STRONG_TEST.replace('len(calls) > 1', 'True')
        )

        assert 'needed a rerun' not in result.stderr.str()
