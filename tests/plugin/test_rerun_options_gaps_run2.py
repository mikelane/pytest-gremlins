"""Rerun settings the baseline uses that still go wrong in gremlin runs (adversarial QA run 2, refs #546).

Each case was reproduced end to end against a flaky test that fails on its first call in every fresh
process: the baseline passes on a rerun, and the gremlin runs must rerun it the same way.
"""

from __future__ import annotations

import re

import pytest

from pytest_gremlins.rerun_options import rerun_options_in

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


def _survivor_count(output: str) -> int:
    match = re.search(r'Survived: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


@pytest.mark.small
class DescribeOverrideIniClusteredWithAnInlineValue:
    def it_carries_an_ini_override_written_as_a_clustered_flag_with_an_equals_sign(self) -> None:
        # argparse reads ``-qo=reruns=2`` as ``-q -o reruns=2``, just as it reads ``-o=reruns=2`` as ``-o reruns=2``.
        assert rerun_options_in(['-qo=reruns=2']) == ['--override-ini=reruns=2']


@pytest.mark.medium
class DescribeRerunfailuresLoadedWithPOnTheCommandLine:
    def it_leaves_the_mutants_the_flaky_test_cannot_catch_alive_when_autoload_is_disabled(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 the baseline only knows ``--reruns`` because ``-p`` loaded the
        # plugin.  Gremlin runs that get ``--reruns=2`` without that ``-p`` reject it as unrecognized, so every
        # gremlin is reported as an error.
        monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
        pytester_with_markers.makeini('[pytest]\naddopts = -p pytest_gremlins.plugin -p pytest_cov\n')
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(test_sample=_FLAKY_WEAK_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '-p',
            'no:cacheprovider',
            '-p',
            'pytest_rerunfailures',
            '--reruns',
            '2',
        )

        assert _survivor_count(result.stdout.str()) > 0
