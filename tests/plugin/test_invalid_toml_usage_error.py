"""An invalid [tool.pytest-gremlins] value is a usage error, not a crash."""

from __future__ import annotations

import pytest

_TARGET = 'def add(a, b):\n    return a + b\n'
_TEST = 'from target import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'


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
