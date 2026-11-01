"""Under ``-c`` a gremlin run reads the project config the baseline ignored (refs #658).

A gremlin run never gets ``-c``, so it discovers the project's own config file (``pytest.ini``,
``pyproject.toml``...).  Every rerun key not forwarded as ``--override-ini`` -- because the ``-c`` file
leaves it unset, or because #658 skips it -- is then filled in from that other file.  When that value
restricts reruns more than the baseline did, a flaky test is not rerun and gremlins are falsely zapped.
"""

from __future__ import annotations

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    run_gremlins,
    survivor_count,
)

_CI_TOML_WITH_TRAILING_SPACE_PATTERN = '[tool.pytest.ini_options]\nreruns = 2\nrerun_except = ["xyz "]\n'


@pytest.mark.medium
class DescribeRerunKeysTheConfigFileDoesNotForward:
    def it_does_not_let_the_project_rerun_except_replace_a_skipped_pattern(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        # Regression against c0326f2: there the stripped ``xyz`` was forwarded and masked pytest.ini.
        (pytester_with_markers.path / 'ci.toml').write_text(_CI_TOML_WITH_TRAILING_SPACE_PATTERN, encoding='utf-8')
        (pytester_with_markers.path / 'pytest.ini').write_text('[pytest]\nrerun_except = flaky\n', encoding='utf-8')

        result = run_gremlins(pytester_with_markers, '-c', 'ci.toml')

        assert survivor_count(result.stdout.str()) > 0

    def it_does_not_let_the_project_rerun_except_apply_when_the_config_file_leaves_it_unset(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        (pytester_with_markers.path / 'ci.ini').write_text('[pytest]\nreruns = 2\n', encoding='utf-8')
        (pytester_with_markers.path / 'pyproject.toml').write_text(
            '[tool.pytest.ini_options]\nrerun_except = ["flaky"]\n', encoding='utf-8'
        )

        result = run_gremlins(pytester_with_markers, '-c', 'ci.ini')

        assert survivor_count(result.stdout.str()) > 0

    def it_does_not_let_the_project_only_rerun_apply_when_the_config_file_leaves_it_unset(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        (pytester_with_markers.path / 'ci.ini').write_text('[pytest]\nreruns = 2\n', encoding='utf-8')
        (pytester_with_markers.path / 'pytest.ini').write_text('[pytest]\nonly_rerun = nomatch\n', encoding='utf-8')

        result = run_gremlins(pytester_with_markers, '-c', 'ci.ini')

        assert survivor_count(result.stdout.str()) > 0


@pytest.mark.medium
class DescribeTheSkippedPatternWarning:
    def it_stays_silent_when_a_command_line_option_already_replaces_the_skipped_setting(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        # pytest-rerunfailures reads ``--only-rerun`` instead of the ini key, so nothing is lost.
        (pytester_with_markers.path / 'ci.toml').write_text(
            '[tool.pytest.ini_options]\nreruns = 2\nonly_rerun = ["flaky "]\n', encoding='utf-8'
        )

        result = run_gremlins(pytester_with_markers, '-c', 'ci.toml', '--only-rerun', 'flaky')

        assert survivor_count(result.stdout.str()) > 0
        assert 'not carried into gremlin runs' not in result.stderr.str()

    def it_stays_silent_when_the_config_file_addopts_already_replaces_the_skipped_setting(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        (pytester_with_markers.path / 'ci.toml').write_text(
            '[tool.pytest.ini_options]\nreruns = 2\naddopts = "--only-rerun flaky"\nonly_rerun = ["flaky "]\n',
            encoding='utf-8',
        )

        result = run_gremlins(pytester_with_markers, '-c', 'ci.toml')

        assert survivor_count(result.stdout.str()) > 0
        assert 'not carried into gremlin runs' not in result.stderr.str()
