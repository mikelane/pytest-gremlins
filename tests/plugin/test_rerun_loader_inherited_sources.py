"""The rerunfailures loader forwarded to gremlin runs matches what they inherit (issue #679).

Each test runs a real ``pytest --gremlins`` session on a project whose only test is flaky inside gremlin
runs.  With reruns honoured, the boundary mutant survives (1 zapped / 1 survived), as with autoload on.
"""

from __future__ import annotations

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    AUTOLOAD_ENV_VAR,
    FLAKY_UNDER_GREMLINS_TEST,
    GREMLIN_ARGS,
    SAMPLE,
    verdicts,
)

# The session autoloads these but gremlin runs with autoload off would not; block them so only reruns differ.
SESSION_ONLY_BLOCKS = ('-p', 'no:xdist', '-p', 'no:test_categories')


def _write_flaky_project(pytester: pytest.Pytester, ini: str) -> None:
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
    pytester.makeini(ini)


@pytest.mark.medium
class DescribeLoaderRepeatedUnderTheEntryPointName:
    """A session that loads the plugin by its entry-point name keeps working with autoload disabled.

    Forwarding the module name regressed this: every gremlin was an ERROR.  The forwarded
    ``-p pytest_rerunfailures`` registers the module under its module name, and the user's ``-p rerunfailures``
    registers the same module under its entry-point name: pluggy raises
    ``ValueError: Plugin already registered under a different name``.
    """

    def it_reruns_when_ini_addopts_loads_the_plugin_by_entry_point_name(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p pytest_cov.plugin')
        _write_flaky_project(pytester, '[pytest]\nreruns = 2\naddopts = -p rerunfailures\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'gremlins')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_reruns_when_pytest_addopts_loads_the_plugin_by_entry_point_name(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p pytest_cov.plugin -p rerunfailures')
        _write_flaky_project(pytester, '[pytest]\nreruns = 2\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'gremlins')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}


@pytest.mark.medium
class DescribeAutoloadDisabledByAFlagThatGremlinRunsInherit:
    """``--disable-plugin-autoload`` in ini ``addopts`` or ``PYTEST_ADDOPTS`` reaches gremlin runs.

    The session loaded the plugin by a command-line ``-p``; gremlin runs inherit the flag, so they need the
    loader, or they never rerun and falsely zap the boundary mutant (2 zapped / 0 survived).
    """

    def it_reruns_when_ini_addopts_disables_autoload(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(
            pytester, '[pytest]\nreruns = 2\naddopts = --disable-plugin-autoload -p pytest_cov.plugin -p gremlins\n'
        )

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_reruns_when_pytest_addopts_disables_autoload(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        monkeypatch.setenv('PYTEST_ADDOPTS', '--disable-plugin-autoload -p pytest_cov.plugin -p gremlins')
        _write_flaky_project(pytester, '[pytest]\nreruns = 2\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_accepts_a_rerun_option_on_the_command_line_when_ini_addopts_disables_autoload(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        # Without the loader, gremlin runs reject --reruns as an unrecognized argument and every gremlin errors.
        pytester = pytester_with_markers
        _write_flaky_project(
            pytester, '[pytest]\naddopts = --disable-plugin-autoload -p pytest_cov.plugin -p gremlins\n'
        )

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures', '--reruns', '2')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}


@pytest.mark.medium
class DescribeInheritedFlagsKeptInAnArgumentFile:
    """pytest expands ``@file`` in ``addopts`` and ``PYTEST_ADDOPTS``, relative to the directory it was run from.

    A flag or loader inside such a file reaches gremlin runs just like a bare one, so it must count.
    """

    def it_reruns_when_ini_addopts_names_an_argument_file_that_disables_autoload(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(
            pytester, '[pytest]\nreruns = 2\naddopts = @autoload.args -p pytest_cov.plugin -p gremlins\n'
        )
        pytester.makefile('.args', autoload='--disable-plugin-autoload\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_reruns_when_pytest_addopts_names_an_argument_file_that_disables_autoload(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        monkeypatch.setenv('PYTEST_ADDOPTS', '@autoload.args -p pytest_cov.plugin -p gremlins')
        _write_flaky_project(pytester, '[pytest]\nreruns = 2\n')
        pytester.makefile('.args', autoload='--disable-plugin-autoload\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_reruns_when_the_flag_sits_in_a_nested_argument_file(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(pytester, '[pytest]\nreruns = 2\naddopts = @outer.args -p pytest_cov.plugin -p gremlins\n')
        pytester.makefile('.args', outer='@inner.args\n', inner='--disable-plugin-autoload\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_does_not_serve_a_verdict_cached_without_reruns_to_a_session_with_autoload_on(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(
            pytester, '[pytest]\nreruns = 2\naddopts = @autoload.args -p pytest_cov.plugin -p gremlins\n'
        )
        pytester.makefile('.args', autoload='--disable-plugin-autoload\n')
        pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures', '--gremlin-cache')
        pytester.makeini('[pytest]\nreruns = 2\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '--gremlin-cache')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}


@pytest.mark.medium
class DescribeLoaderOnTheSessionCommandLine:
    def it_reruns_when_the_command_line_loads_the_plugin_by_entry_point_name(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p pytest_cov.plugin')
        _write_flaky_project(pytester, '[pytest]\nreruns = 2\n')

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'gremlins', '-p', 'rerunfailures')

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_reruns_when_only_the_command_line_disables_autoload(self, pytester_with_markers: pytest.Pytester) -> None:
        # Gremlin runs do not get the flag, so they autoload the plugin; a loader would register it twice.
        pytester = pytester_with_markers
        _write_flaky_project(pytester, '[pytest]\nreruns = 2\n')

        result = pytester.runpytest_subprocess(
            *GREMLIN_ARGS, '--disable-plugin-autoload', '-p', 'gremlins', '-p', 'pytest_rerunfailures'
        )

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    @pytest.mark.parametrize('execution_mode', [('--gremlin-workers=2',), ('--gremlin-batch',)])
    def it_reruns_in_every_execution_mode(
        self,
        pytester_with_markers: pytest.Pytester,
        monkeypatch: pytest.MonkeyPatch,
        execution_mode: tuple[str, ...],
    ) -> None:
        pytester = pytester_with_markers
        monkeypatch.setenv(AUTOLOAD_ENV_VAR, '1')
        monkeypatch.setenv('PYTEST_ADDOPTS', '-p pytest_cov.plugin')
        _write_flaky_project(pytester, '[pytest]\nreruns = 2\n')

        result = pytester.runpytest_subprocess(
            *GREMLIN_ARGS, '-p', 'gremlins', '-p', 'pytest_rerunfailures', *execution_mode
        )

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}


@pytest.mark.medium
class DescribeCachedVerdictsWhenAnInheritedFlagDisablesAutoload:
    def it_does_not_serve_a_verdict_cached_by_a_run_without_reruns(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester = pytester_with_markers
        _write_flaky_project(
            pytester, '[pytest]\nreruns = 2\naddopts = --disable-plugin-autoload -p pytest_cov.plugin -p gremlins\n'
        )
        cache_args = ('--gremlin-cache',)
        uncached_run = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures')
        pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures', '-o', 'reruns=0', *cache_args)

        cached_run = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures', *cache_args)

        assert verdicts(cached_run.stdout.str()) == verdicts(uncached_run.stdout.str())
        assert verdicts(cached_run.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}


def _write_project_run_from_subdirectory(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, *, at_rootdir: str, at_invocation_dir: str
) -> None:
    pytester.makepyfile(sample=SAMPLE)
    pytester.makepyfile(test_sample=FLAKY_UNDER_GREMLINS_TEST)
    pytester.makeini('[pytest]\nreruns = 2\naddopts = @shared.args -p pytest_cov -p gremlins\n')
    pytester.makefile('.args', shared=at_rootdir)
    invocation_dir = pytester.mkdir('sub')
    (invocation_dir / 'shared.args').write_text(at_invocation_dir)
    monkeypatch.chdir(invocation_dir)


@pytest.mark.medium
class DescribeArgumentFileResolvedFromTheDirectoryGremlinRunsStartIn:
    """Gremlin runs start in the rootdir, so a relative ``@file`` in ``addopts`` is read from there.

    The detector must read the copy gremlin runs read, not the copy beside a session started from a subdirectory.
    """

    def it_reruns_when_only_the_rootdir_copy_of_the_argument_file_disables_autoload(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project_run_from_subdirectory(
            pytester, monkeypatch, at_rootdir='--disable-plugin-autoload\n', at_invocation_dir='-q\n'
        )

        result = pytester.runpytest_subprocess(
            *GREMLIN_ARGS, '-p', 'rerunfailures', *SESSION_ONLY_BLOCKS, str(pytester.path)
        )

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_scores_no_errors_when_only_the_invocation_dir_copy_disables_autoload(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester = pytester_with_markers
        _write_project_run_from_subdirectory(
            pytester, monkeypatch, at_rootdir='-q\n', at_invocation_dir='--disable-plugin-autoload\n'
        )

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures', str(pytester.path))

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}

    def it_reruns_when_both_copies_disable_autoload(
        self, pytester_with_markers: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Control: same content in both places, so the detector and gremlin runs agree.
        pytester = pytester_with_markers
        _write_project_run_from_subdirectory(
            pytester,
            monkeypatch,
            at_rootdir='--disable-plugin-autoload\n',
            at_invocation_dir='--disable-plugin-autoload\n',
        )

        result = pytester.runpytest_subprocess(*GREMLIN_ARGS, '-p', 'pytest_rerunfailures', str(pytester.path))

        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}
