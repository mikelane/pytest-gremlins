"""Adversarial QA probes for --gremlin-operators / --gremlin-targets validation (issue #785)."""

from __future__ import annotations

import pytest

_TARGET = 'def add(a, b):\n    return a + b\n'
_TEST = 'from target import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'
_CUSTOM_OPERATOR_CONFTEST = """
import ast

from pytest_gremlins.instrumentation.transformer import get_default_registry


class NoopOperator:
    @property
    def name(self):
        return 'noop-custom'

    @property
    def description(self):
        return 'never mutates'

    def can_mutate(self, node):
        return False

    def mutate(self, node):
        return []


get_default_registry().register(NoopOperator)
"""


@pytest.mark.medium
class DescribeValidButUnusualCliValues:
    """Values that worked before #785 keep working."""

    def it_accepts_an_operator_registered_in_the_root_conftest(self, pytester_with_markers: pytest.Pytester) -> None:
        conftest = pytester_with_markers.path / 'conftest.py'
        conftest.write_text(conftest.read_text() + _CUSTOM_OPERATOR_CONFTEST)
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=noop-custom,comparison'
        )

        assert result.ret == pytest.ExitCode.OK

    def it_accepts_whitespace_around_operator_names(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets= target.py ', '--gremlin-operators= arithmetic , comparison '
        )

        assert result.ret == pytest.ExitCode.OK

    def it_accepts_the_target_list_built_by_the_documented_pre_commit_recipe(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        """docs/cookbook/pre-commit.md builds --gremlin-targets with `tr "\\n" ","`, which leaves a trailing comma."""
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)
        staged_files = 'target.py\n'

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=' + staged_files.replace('\n', ',')
        )

        assert result.ret == pytest.ExitCode.OK


@pytest.mark.medium
class DescribeInvalidCliValueUnderXdist:
    def it_exits_with_a_usage_error_before_workers_start(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '-n', '2', '--gremlin-targets=target.py', '--gremlin-operators=bogus'
        )

        assert result.ret == pytest.ExitCode.USAGE_ERROR
        assert 'INTERNALERROR' not in result.stdout.str() + result.stderr.str()
        result.stderr.fnmatch_lines(["*--gremlin-operators has unknown operator 'bogus'*"])

    def it_rejects_a_bad_cli_operator_even_when_the_toml_list_is_valid(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\noperators = ["comparison"]\n')
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=target.py', '--gremlin-operators=Comparison'
        )

        assert result.ret == pytest.ExitCode.USAGE_ERROR
        result.stderr.fnmatch_lines(["*--gremlin-operators has unknown operator 'Comparison'*"])
