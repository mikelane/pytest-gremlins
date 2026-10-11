"""A forwarded ``-p`` must not break gremlin runs when autoload was disabled by flag (adversarial QA run 4, refs #546).

``--disable-plugin-autoload`` turns entry-point autoload off for the baseline only; it is a command-line flag, so the
gremlin subprocesses never see it and autoload pytest-rerunfailures from its entry point (registered as
``rerunfailures``).  Forwarding the top-level ``-p pytest_rerunfailures`` into those runs loads the module a second time
under ``pytest_rerunfailures``, and pluggy refuses it: ``ValueError: Plugin already registered under a different name``.
Every gremlin run then fails before any test runs, and each mutant is reported as zapped.
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


def _survivor_count(output: str) -> int:
    match = re.search(r'Survived: (\d+) gremlins', output)
    return int(match.group(1)) if match else 0


@pytest.mark.medium
class DescribeRerunfailuresLoaderWithAutoloadDisabledByFlag:
    @pytest.mark.parametrize('loader', [('-p', 'pytest_rerunfailures'), ('-ppytest_rerunfailures',)])
    def it_leaves_the_mutant_the_flaky_test_cannot_catch_alive(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, loader: tuple[str, ...]
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        pytester_with_markers.makepyfile(sample=_SAMPLE)
        pytester_with_markers.makepyfile(test_sample=_FLAKY_WEAK_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            '--disable-plugin-autoload',
            '-p',
            'gremlins',
            '-p',
            'pytest_cov',
            *loader,
            '--reruns',
            '2',
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '-p',
            'no:cacheprovider',
        )

        assert _survivor_count(result.stdout.str()) > 0
