"""A ``-p`` that loads pytest-rerunfailures must not break gremlin runs or fake verdicts (refs #546).

pytest loads ``-p`` plugins while it pre-parses the raw command line, before ``@file`` arguments are expanded, so a
``-p pytest_rerunfailures`` kept in an argument file loads nothing.  With plugin autoload on, the baseline gets
pytest-rerunfailures from its entry point (registered as ``rerunfailures``) and passes on a rerun.  Forwarding that
``-p`` as a top-level argument makes each gremlin run load the module a second time under ``pytest_rerunfailures``,
and pluggy refuses it: ``ValueError: Plugin already registered under a different name``.

``--disable-plugin-autoload`` has the same effect: it turns entry-point autoload off for the baseline only, and being a
command-line flag the gremlin subprocesses never see it.  Every gremlin run then fails before any test runs, and each
mutant would be reported as zapped.

With ``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` the baseline only knows ``--reruns`` because ``-p`` loaded the plugin; the
plugin abstains there rather than guess (tracked in #654).
"""

from __future__ import annotations

import pytest
from rerun_samples import (
    FLAKY_WEAK_TEST,
    SAMPLE,
    survivor_count,
    verdicts,
    write_flaky_project,
)


@pytest.mark.medium
class DescribeRerunfailuresLoadedWithPOnTheCommandLine:
    def it_reports_every_gremlin_as_an_error_and_zaps_none_when_autoload_is_disabled(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A ``-p`` is not forwarded, so gremlin runs reject ``--reruns=2`` as unrecognized.  The plugin
        # abstains: every gremlin is an error and none is falsely zapped.
        monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
        pytester_with_markers.makeini('[pytest]\naddopts = -p pytest_gremlins.plugin -p pytest_cov\n')
        pytester_with_markers.makepyfile(sample=SAMPLE)
        pytester_with_markers.makepyfile(test_sample=FLAKY_WEAK_TEST)

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

        counts = verdicts(result.stdout.str())
        assert counts['Error'] > 0
        assert counts['Zapped'] == 0
        assert counts['Survived'] == 0


@pytest.mark.medium
class DescribeRerunfailuresLoaderKeptInAnArgumentFileWithAutoload:
    def it_leaves_the_mutant_the_flaky_test_cannot_catch_alive(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        write_flaky_project(pytester_with_markers)
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

        assert survivor_count(result.stdout.str()) > 0


@pytest.mark.medium
class DescribeRerunfailuresLoaderWithAutoloadDisabledByFlag:
    @pytest.mark.parametrize('loader', [('-p', 'pytest_rerunfailures'), ('-ppytest_rerunfailures',)])
    def it_leaves_the_mutant_the_flaky_test_cannot_catch_alive(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, loader: tuple[str, ...]
    ) -> None:
        monkeypatch.delenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', raising=False)
        write_flaky_project(pytester_with_markers)

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

        assert survivor_count(result.stdout.str()) > 0
