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


def _count_in(output: str, label: str) -> int:
    match = re.search(rf'{label}: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


@pytest.mark.small
class DescribeOverrideIniClusteredWithAnInlineValue:
    def it_carries_an_ini_override_written_as_a_clustered_flag_with_an_equals_sign(self) -> None:
        # argparse reads ``-qo=reruns=2`` as ``-q -o reruns=2``, just as it reads ``-o=reruns=2`` as ``-o reruns=2``.
        assert rerun_options_in(['-qo=reruns=2']) == ['--override-ini=reruns=2']


@pytest.mark.medium
class DescribeRerunfailuresLoadedWithPOnTheCommandLine:
    def it_reports_every_gremlin_as_an_error_and_zaps_none_when_autoload_is_disabled(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 the baseline only knows ``--reruns`` because ``-p`` loaded the
        # plugin.  A ``-p`` is not forwarded, so gremlin runs reject ``--reruns=2`` as unrecognized.  The plugin
        # abstains: every gremlin is an error and none is falsely zapped.  Loading it there is tracked in #654.
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

        output = result.stdout.str()
        assert _count_in(output, 'Error') > 0
        assert _count_in(output, 'Zapped') == 0
        assert _count_in(output, 'Survived') == 0
