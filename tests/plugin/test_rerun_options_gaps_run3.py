"""A ``-p`` for pytest-rerunfailures that pytest never acted on must not be forwarded (adversarial QA run 3, refs #546).

pytest loads ``-p`` plugins while it pre-parses the raw command line, before ``@file`` arguments are expanded, so a
``-p pytest_rerunfailures`` kept in an argument file loads nothing.  With plugin autoload on, the baseline gets
pytest-rerunfailures from its entry point (registered as ``rerunfailures``) and passes on a rerun.  Forwarding that
``-p`` as a top-level argument makes each gremlin run load the module a second time under ``pytest_rerunfailures``,
and pluggy refuses it: ``ValueError: Plugin already registered under a different name``.
"""

from __future__ import annotations

from pathlib import Path
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


@pytest.mark.medium
class DescribePluginLoaderInsideAnArgumentFile:
    def it_does_not_forward_a_p_that_only_appears_inside_an_argument_file(self, tmp_path: Path) -> None:
        (tmp_path / 'args.txt').write_text('-p\npytest_rerunfailures\n--reruns\n2\n', encoding='utf-8')

        assert rerun_options_in(['@args.txt'], base_dir=tmp_path) == ['--reruns=2']


@pytest.mark.medium
class DescribeRerunfailuresLoaderKeptInAnArgumentFileWithAutoload:
    def it_leaves_the_mutant_the_flaky_test_cannot_catch_alive(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(test_sample=_FLAKY_WEAK_TEST)
        (pytester_with_markers.path / 'args.txt').write_text(
            '-p\npytest_rerunfailures\n--reruns\n2\n', encoding='utf-8'
        )

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '-p',
            'no:cacheprovider',
            '@args.txt',
        )

        assert _survivor_count(result.stdout.str()) > 0
