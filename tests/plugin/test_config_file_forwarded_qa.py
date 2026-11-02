"""Adversarial QA findings for #951: what forwarding ``-c`` to gremlin runs changes beyond collection.

Before #951 a gremlin run under ``-c`` read the project's discoverable config file instead of the ``-c`` file.  When
both let the tests collect, those runs produced real verdicts, which the incremental cache stored.  Now the runs read
the ``-c`` file, so a verdict cached by the older runner can be wrong for the new one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rerun_samples import (  # type: ignore[import-not-found]
    FLAKY_WEAK_TEST,
    GREMLIN_ARGS,
    SAMPLE,
    run_gremlins,
    verdicts,
)

# The weak test lets the ``>=`` gremlin through unless its warning is an error.
WARNING_SENSITIVE_TEST = """
import warnings

from sample import classify


def test_big():
    warnings.warn('odd' if classify(10) == 'big' else 'fine', UserWarning)
    assert classify(11) == 'big'
"""

# Makes this session behave like the pre-#951 runner: gremlin runs are not given ``-c``.
PRE_951_RUNNER_PLUGIN = """
from pytest_gremlins import plugin

plugin._config_file_options = lambda config: []
"""


@pytest.fixture(autouse=True)
def utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make child pytest processes write UTF-8 so the parent decodes their output on any platform."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


@pytest.fixture
def two_config_project(pytester_with_markers: pytest.Pytester) -> Path:
    """A project whose discovered ``pytest.ini`` makes the warning an error and whose ``ci.ini`` does not."""
    root = pytester_with_markers.path
    (root / 'pytest.ini').write_text('[pytest]\nfilterwarnings =\n    error:odd\n', encoding='utf-8')
    (root / 'ci.ini').write_text('[pytest]\n', encoding='utf-8')
    (root / 'sample.py').write_text(SAMPLE, encoding='utf-8')
    (root / 'test_sample.py').write_text(WARNING_SENSITIVE_TEST, encoding='utf-8')
    return root


@pytest.mark.medium
class DescribeAVerdictCachedBeforeGremlinRunsReadTheConfigFile:
    @pytest.mark.xfail(
        strict=True,
        reason='adversarial QA #951: no cache marker or key part retires verdicts cached while gremlin runs ignored -c',
    )
    def it_is_not_reused_once_gremlin_runs_read_the_config_file(
        self, pytester_with_markers: pytest.Pytester, two_config_project: Path
    ) -> None:
        args = (*GREMLIN_ARGS, '--gremlin-cache', '-c', 'ci.ini')
        plugin_dir = two_config_project.parent / 'pre_951_plugin'
        plugin_dir.mkdir()
        (plugin_dir / 'pre_951_runner.py').write_text(PRE_951_RUNNER_PLUGIN, encoding='utf-8')
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv('PYTHONPATH', str(plugin_dir))
            pre_951_run = pytester_with_markers.runpytest_subprocess(*args, '-p', 'pre_951_runner')

        result = pytester_with_markers.runpytest_subprocess(*args)

        assert verdicts(pre_951_run.stdout.str()) == {'Zapped': 2, 'Survived': 0, 'Error': 0}, pre_951_run.stdout.str()
        assert verdicts(result.stdout.str()) == {'Zapped': 1, 'Survived': 1, 'Error': 0}, result.stdout.str()


_FLAKY_TEST_FAILING_WITH_XYZ = FLAKY_WEAK_TEST.replace(
    "'flaky: fails on the first call in every fresh process'", "'flaky xyz'"
)
_TOML_WITH_TRAILING_SPACE_PATTERN = '[tool.pytest.ini_options]\nreruns = 2\nrerun_except = ["xyz "]\n'


@pytest.mark.medium
class DescribeARerunPatternInTheConfigFileGremlinRunsNowRead:
    @pytest.mark.xfail(
        strict=True,
        reason='adversarial QA #951: rerun ini resets under -c discard a setting the gremlin runs now read themselves',
    )
    def it_keeps_the_pattern_the_gremlin_runs_read_from_the_config_file(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        (pytester_with_markers.path / 'ci.toml').write_text(_TOML_WITH_TRAILING_SPACE_PATTERN, encoding='utf-8')

        result = run_gremlins(pytester_with_markers, '-c', 'ci.toml', tests=_FLAKY_TEST_FAILING_WITH_XYZ)

        assert 'not carried into gremlin runs' not in result.stderr.str()
