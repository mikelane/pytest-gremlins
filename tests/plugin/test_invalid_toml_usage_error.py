"""An invalid [tool.pytest-gremlins] value is a usage error, not a crash."""

from __future__ import annotations

import pytest

_TARGET = 'def add(a, b):\n    return a + b\n'
_TEST = 'from target import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'
_FAILING_TEST = 'from target import add\n\n\ndef test_add():\n    assert add(1, 2) == 4\n'


@pytest.mark.medium
class DescribeInvalidTomlValue:
    """pytest exits with a usage error naming the key and the value."""

    @pytest.mark.parametrize(
        ('toml_line', 'expected'),
        [
            ('mutant_timeout = 0', '*mutant_timeout must be a positive integer*got 0*'),
            ('mutant_timeout = "soon"', "*mutant_timeout must be a positive integer*got 'soon'*"),
            ('coverage_timeout = -5', '*coverage_timeout must be a positive integer*got -5*'),
            ('batch_size = 0', '*batch_size must be a positive integer*got 0*'),
            ('cache = "yes"', "*cache must be a boolean*got 'yes'*"),
            ('workers = -1', '*workers*-1*'),
            ('exclude = 5', '*exclude must be a list of strings*got 5*'),
            ('exclude = [5]', '*exclude must be a list of strings*got [[]5[]]*'),
            ('operators = 5', '*operators must be a list of strings*got 5*'),
            ('paths = 5', '*paths must be a list of strings*got 5*'),
            ('operators = "comparison"', "*operators must be a list of strings*use a list*got 'comparison'*"),
            ('exclude = "tests/*"', "*exclude must be a list of strings*use a list*got 'tests/*'*"),
            ('operators = ["bogus"]', "*unknown operator 'bogus'*Valid operators:*comparison*"),
            ('batch_size = 3\nbatch-size = 4', "*sets both 'batch_size' and 'batch-size'*"),
        ],
    )
    def it_exits_with_a_usage_error_naming_the_key_and_value(
        self, pytester_with_markers: pytest.Pytester, toml_line: str, expected: str
    ) -> None:
        pytester_with_markers.makepyprojecttoml(f'[tool.pytest-gremlins]\n{toml_line}\n')
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        assert result.ret == pytest.ExitCode.USAGE_ERROR
        assert 'INTERNALERROR' not in result.stdout.str() + result.stderr.str()
        result.stderr.fnmatch_lines([expected])


@pytest.mark.medium
class DescribeUnknownTomlKey:
    """An unknown key does not stop the run; the terminal output names it and the closest valid key."""

    def it_warns_naming_the_key_and_the_closest_valid_key(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\nmax_pardon_pct = 5\n')
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        assert result.ret == pytest.ExitCode.OK
        result.stdout.fnmatch_lines(["*unknown key 'max_pardon_pct'*did you mean 'max-pardons-pct'?*"])

    def it_applies_a_key_given_with_the_other_spelling(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\nmax_pardons_pct = 150\n')
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        assert result.ret == pytest.ExitCode.USAGE_ERROR
        result.stderr.fnmatch_lines(['*max-pardons-pct must be between 0 and 100*'])


@pytest.mark.medium
class DescribeUnknownTomlKeyWhenNothingIsMutated:
    """The unknown-key warning still reaches the user when the run skips mutation testing."""

    def it_warns_under_collect_only(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\nmax_pardon_pct = 5\n')
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--collect-only')

        output = result.stdout.str() + result.stderr.str()
        assert "unknown key 'max_pardon_pct'" in output

    def it_warns_when_the_baseline_is_red(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyprojecttoml('[tool.pytest-gremlins]\nmax_pardon_pct = 5\n')
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_FAILING_TEST)

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        output = result.stdout.str() + result.stderr.str()
        assert "unknown key 'max_pardon_pct'" in output


@pytest.mark.medium
class DescribeInvalidCliListOption:
    """An invalid --gremlin-operators or --gremlin-targets value is a usage error."""

    @pytest.mark.parametrize(
        ('flag', 'expected'),
        [
            (
                '--gremlin-operators=bogus',
                "*--gremlin-operators has unknown operator 'bogus'*Valid operators:*comparison*",
            ),
        ],
    )
    def it_exits_with_a_usage_error_naming_the_flag(
        self, pytester_with_markers: pytest.Pytester, flag: str, expected: str
    ) -> None:
        pytester_with_markers.makepyfile(target=_TARGET, test_target=_TEST)

        result = pytester_with_markers.runpytest_subprocess('--gremlins', flag)

        assert result.ret == pytest.ExitCode.USAGE_ERROR
        assert 'INTERNALERROR' not in result.stdout.str() + result.stderr.str()
        result.stderr.fnmatch_lines([expected])
