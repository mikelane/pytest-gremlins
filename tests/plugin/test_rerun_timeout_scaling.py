"""The per-mutant timeout grows with the rerun budget pytest-rerunfailures gives each test (issue #655)."""

from __future__ import annotations

import re

import pytest

from pytest_gremlins import plugin
from pytest_gremlins.config import MAX_TIMEOUT_SECONDS
from pytest_gremlins.rerun_options import scaled_mutant_timeout


@pytest.mark.small
class DescribeScaledMutantTimeout:
    @pytest.mark.parametrize('reruns', [0, -1])
    def it_returns_the_base_timeout_when_there_are_no_reruns(self, reruns: int) -> None:
        assert scaled_mutant_timeout(30, reruns=reruns, reruns_delay=20) == 30

    @pytest.mark.parametrize(
        ('base', 'reruns', 'delay', 'expected'),
        [
            (30, 1, 0, 60),
            (30, 2, 0, 90),
            (30, 2, 20, 130),
            (10, 3, 1, 43),
        ],
    )
    def it_allows_every_attempt_its_full_budget_plus_the_delays(
        self, base: int, reruns: int, delay: float, expected: int
    ) -> None:
        assert scaled_mutant_timeout(base, reruns=reruns, reruns_delay=delay) == expected

    @pytest.mark.parametrize(('delay', 'expected'), [(0.1, 61), (0.5, 61), (1.5, 62)])
    def it_rounds_the_total_delay_up_to_whole_seconds(self, delay: float, expected: int) -> None:
        assert scaled_mutant_timeout(30, reruns=1, reruns_delay=delay) == expected

    def it_rounds_the_summed_delay_not_each_delay(self) -> None:
        assert scaled_mutant_timeout(30, reruns=4, reruns_delay=0.5) == 152

    @pytest.mark.parametrize('delay', [-5, -0.5])
    def it_treats_a_negative_delay_as_no_delay(self, delay: float) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=delay) == 90

    def it_never_exceeds_the_maximum_timeout(self) -> None:
        assert scaled_mutant_timeout(MAX_TIMEOUT_SECONDS, reruns=5, reruns_delay=100) == MAX_TIMEOUT_SECONDS

    def it_clamps_an_infinite_delay_to_the_maximum_timeout(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=float('inf')) == MAX_TIMEOUT_SECONDS

    def it_treats_a_delay_that_is_not_a_number_as_no_delay(self) -> None:
        assert scaled_mutant_timeout(30, reruns=2, reruns_delay=float('nan')) == 90


def _configured_mutant_timeout(pytester: pytest.Pytester, *args: str, ini: str = '') -> int:
    pytester.makepyfile(sample='def one():\n    return 1\n')
    pytester.makeini(f'[pytest]\n{ini}\n')
    pytester.parseconfigure('--gremlins', '--gremlin-targets=sample.py', *args)
    session = plugin._get_session()
    assert session is not None
    assert session.enabled
    return session.mutant_timeout


@pytest.mark.medium
class DescribeMutantTimeoutThroughTheRealEntryPoint:
    def it_scales_the_default_timeout_by_the_command_line_reruns(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, '--reruns', '2', '--reruns-delay', '20') == 130

    def it_scales_an_explicit_timeout_too(self, pytester: pytest.Pytester) -> None:
        timeout = _configured_mutant_timeout(pytester, '--gremlin-mutant-timeout', '5', '--reruns', '1')

        assert timeout == 10

    def it_scales_by_the_reruns_in_the_ini_file(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, ini='reruns = 2\nreruns_delay = 1.5') == 93

    def it_prefers_the_command_line_count_over_the_ini_count(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, '--reruns', '1', ini='reruns = 5') == 60

    def it_takes_the_delay_from_the_ini_file_when_only_the_count_is_on_the_command_line(
        self, pytester: pytest.Pytester
    ) -> None:
        assert _configured_mutant_timeout(pytester, '--reruns', '1', ini='reruns_delay = 9') == 69

    def it_prefers_the_command_line_delay_over_the_ini_delay(self, pytester: pytest.Pytester) -> None:
        assert (
            _configured_mutant_timeout(pytester, '--reruns', '1', '--reruns-delay', '2', ini='reruns_delay = 9') == 62
        )

    def it_lets_force_reruns_set_the_rerun_count(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, '--force-reruns', '3', '--reruns', '1') == 120

    def it_leaves_the_timeout_alone_when_reruns_is_zero(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, '--reruns', '0', '--reruns-delay', '20') == 30

    def it_leaves_the_timeout_alone_when_no_reruns_are_configured(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester) == 30

    def it_ignores_a_value_that_is_not_a_number_in_the_ini_file(self, pytester: pytest.Pytester) -> None:
        assert _configured_mutant_timeout(pytester, ini='reruns = lots') == 30

    def it_leaves_the_timeout_alone_when_pytest_rerunfailures_is_not_loaded(self, pytester: pytest.Pytester) -> None:
        timeout = _configured_mutant_timeout(pytester, '-p', 'no:rerunfailures', ini='reruns = 2')

        assert timeout == 30


_ADDITION = """
def add(a, b):
    return a + b
"""

_TEST_THAT_KILLS_THE_MUTANT = """
import pytest
from sample import add


@pytest.mark.medium
def test_add():
    assert add(2, 3) == 5
"""

# The mutant's covering test fails, is rerun after the delay, and fails again.  The delay alone is longer than the
# limit of one attempt, so only a timeout widened by the rerun budget lets that kill finish as a kill.  The pytest
# start-up of the two attempts (up to 7s each on a loaded runner) fits in the scaled limit with room to spare.
_ONE_ATTEMPT_LIMIT = 10
_RERUN_DELAY = 12


@pytest.mark.medium
class DescribeRerunDelayEndToEnd:
    def it_zaps_a_mutant_whose_covering_test_waits_out_a_rerun_delay(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        pytester.makepyfile(sample=_ADDITION, test_sample=_TEST_THAT_KILLS_THE_MUTANT)

        result = pytester.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=arithmetic',
            '--gremlin-mutant-timeout',
            str(_ONE_ATTEMPT_LIMIT),
            '--reruns',
            '1',
            '--reruns-delay',
            str(_RERUN_DELAY),
            '-p',
            'no:cacheprovider',
        )

        output = result.stdout.str()
        assert re.search(r'Zapped: [1-9]\d* gremlins', output), output
