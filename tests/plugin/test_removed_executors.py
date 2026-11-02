"""``--gremlin-executor=fork|inprocess`` fail at startup: both executors were removed (issue #532)."""

from __future__ import annotations

import pytest

TRACKING_URL = 'https://github.com/mikelane/pytest-gremlins/issues/532'
USAGE_ERROR_EXIT_CODE = 4


@pytest.mark.medium
class DescribeRemovedExecutors:
    """The fork and inprocess executors never ran the mutated code and were removed, so they are refused."""

    @pytest.mark.parametrize('executor', ['fork', 'inprocess'])
    def it_exits_with_a_usage_error(self, pytester_with_markers: pytest.Pytester, executor: str) -> None:
        pytester_with_markers.makepyfile(test_nothing='def test_nothing():\n    pass\n')

        result = pytester_with_markers.runpytest_subprocess('--gremlins', f'--gremlin-executor={executor}')

        assert result.ret == USAGE_ERROR_EXIT_CODE

    @pytest.mark.parametrize('executor', ['fork', 'inprocess'])
    def it_names_the_executor_the_alternative_and_the_tracking_issue(
        self, pytester_with_markers: pytest.Pytester, executor: str
    ) -> None:
        pytester_with_markers.makepyfile(test_nothing='def test_nothing():\n    pass\n')

        result = pytester_with_markers.runpytest_subprocess('--gremlins', f'--gremlin-executor={executor}')

        output = result.stderr.str()
        assert f'--gremlin-executor={executor}' in output
        assert '--gremlin-executor=subprocess' in output
        assert TRACKING_URL in output

    @pytest.mark.parametrize('executor', ['fork', 'inprocess'])
    def it_says_the_executor_was_removed(self, pytester_with_markers: pytest.Pytester, executor: str) -> None:
        pytester_with_markers.makepyfile(test_nothing='def test_nothing():\n    pass\n')

        result = pytester_with_markers.runpytest_subprocess('--gremlins', f'--gremlin-executor={executor}')

        assert 'was removed' in result.stderr.str()

    def it_lists_the_valid_choices_for_an_unknown_executor(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(test_nothing='def test_nothing():\n    pass\n')

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-executor=bogus')

        assert result.ret == USAGE_ERROR_EXIT_CODE
        assert "unknown executor 'bogus'" in result.stderr.str()
        assert 'auto, subprocess' in result.stderr.str()

    @pytest.mark.parametrize('executor', ['auto', 'subprocess'])
    def it_leaves_the_supported_executors_alone(self, pytester_with_markers: pytest.Pytester, executor: str) -> None:
        pytester_with_markers.makepyfile(test_nothing='def test_nothing():\n    pass\n')

        result = pytester_with_markers.runpytest_subprocess('--gremlins', f'--gremlin-executor={executor}')

        assert result.ret != USAGE_ERROR_EXIT_CODE

    def it_ignores_the_executor_when_gremlins_are_off(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(test_nothing='def test_nothing():\n    pass\n')

        result = pytester_with_markers.runpytest_subprocess('--gremlin-executor=fork')

        assert result.ret == 0
