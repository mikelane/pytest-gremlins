"""``--gremlin-prescan-workers`` reaches the session through the real entry point (#527)."""

from __future__ import annotations

import pytest

from pytest_gremlins import plugin


def _configured_session(pytester: pytest.Pytester, *args: str, pyproject: str = '') -> plugin.GremlinSession:
    pytester.makepyfile(sample='def one():\n    return 1\n')
    if pyproject:
        pytester.makepyprojecttoml(f'[tool.pytest-gremlins]\n{pyproject}\n')
    pytester.parseconfigure('--gremlins', '--gremlin-targets=sample.py', *args)
    session = plugin._get_session()
    assert session is not None
    return session


@pytest.mark.small
class DescribeSessionDefault:
    def it_runs_the_pre_scan_serially_unless_asked(self) -> None:
        assert plugin.GremlinSession().prescan_workers == 1


@pytest.mark.medium
class DescribePrescanWorkersThroughTheRealEntryPoint:
    def it_defaults_to_one(self, pytester: pytest.Pytester) -> None:
        assert _configured_session(pytester).prescan_workers == 1

    def it_reads_the_command_line_flag(self, pytester: pytest.Pytester) -> None:
        assert _configured_session(pytester, '--gremlin-prescan-workers=3').prescan_workers == 3

    def it_reads_the_toml_key(self, pytester: pytest.Pytester) -> None:
        assert _configured_session(pytester, pyproject='prescan_workers = 2').prescan_workers == 2

    def it_lets_the_flag_beat_the_toml_key(self, pytester: pytest.Pytester) -> None:
        session = _configured_session(pytester, '--gremlin-prescan-workers=4', pyproject='prescan_workers = 2')

        assert session.prescan_workers == 4

    @pytest.mark.parametrize('value', ['0', '-1', '65'])
    def it_rejects_an_out_of_range_flag_naming_the_flag_and_value(
        self, pytester_with_markers: pytest.Pytester, value: str
    ) -> None:
        pytester_with_markers.makepyfile(target='def f():\n    return 1\n', test_target='def test_f():\n    pass\n')

        result = pytester_with_markers.runpytest('--gremlins', f'--gremlin-prescan-workers={value}')

        result.stderr.fnmatch_lines([f'*--gremlin-prescan-workers must be a positive integer*{value}*'])
