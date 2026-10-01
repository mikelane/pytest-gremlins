"""Every per-mutant run goes through the pytest bootstrap while the lightweight runner is off (issue #538)."""

from __future__ import annotations

import pytest

from pytest_gremlins import plugin

TARGET = """
def classify(n):
    if n > 10:
        return 'big'
    return 'small'
"""

PLAIN_TESTS = """
from sample import classify

def test_plain():
    assert classify(11) == 'big'
    assert classify(10) == 'small'

class TestGroup:
    def test_method(self):
        assert classify(1) == 'small'
"""


@pytest.mark.medium
class DescribeLightweightRunnerDisabled:
    """Even an all-plain suite runs each gremlin through pytest, because the runner cannot imitate it."""

    def it_builds_no_lightweight_command_for_any_gremlin(
        self,
        pytester_with_markers: pytest.Pytester,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        commands: list[list[str] | None] = []
        real_build = plugin.build_lightweight_command

        def spy(test_command: list[str], env_vars: dict[str, str]) -> list[str] | None:
            command = real_build(test_command, env_vars)
            commands.append(command)
            return command

        monkeypatch.setattr(plugin, 'build_lightweight_command', spy)
        pytester_with_markers.makepyfile(sample=TARGET)
        pytester_with_markers.mkdir('tests')
        pytester_with_markers.path.joinpath('tests', 'test_sample.py').write_text(PLAIN_TESTS)

        pytester_with_markers.runpytest_inprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=comparison',
            '--gremlin-no-coverage-filter',
            '-p',
            'no:cacheprovider',
        )

        assert commands
        assert all(command is None for command in commands)
