"""Warnings a user must act on reach the terminal with default logging options (issue #982).

pytest's logging plugin captures ``logger.warning`` records and prints none of them unless ``log_cli`` or
``--log-file`` is set, so each of these is a terminal notice rather than a log record.
"""

from __future__ import annotations

import pytest

TARGET = 'def add(a, b):\n    return a + b\n'
FAST_TEST = (
    'import pytest\nfrom target import add\n\n\n@pytest.mark.small\ndef test_add():\n    assert add(1, 2) == 3\n'
)
NOTICE_PREFIX = 'pytest-gremlins: warning: '


@pytest.mark.medium
class DescribeRuntimeWarningsVisibleByDefault:
    """Each actionable runtime warning is printed without any logging option."""

    def it_prints_a_notice_when_two_targets_are_the_same_file(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makepyfile(target=TARGET, test_target=FAST_TEST)
        (pytester.path / 'alias.py').symlink_to(pytester.path / 'target.py')

        result = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py,alias.py')

        output = result.stdout.str() + result.stderr.str()
        assert f'{NOTICE_PREFIX}Skipping ' in output
        assert 'alias.py as a mutation target' in output
        assert 'is the same file on disk as ' in output

    @pytest.mark.parametrize(
        ('pragma', 'expected'),
        [
            ('# gremlin: pardon[no-such-code] because', 'has unknown reason code'),
            ('# gremlin: pardon[equivalent]', 'is missing a justification'),
        ],
    )
    def it_prints_a_notice_when_a_pragma_is_ignored(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, pragma: str, expected: str
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makepyfile(target=f'def add(a, b):\n    return a + b  {pragma}\n', test_target=FAST_TEST)

        result = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        output = result.stdout.str() + result.stderr.str()
        assert f'{NOTICE_PREFIX}gremlin pragma at' in output
        assert expected in output
        assert 'pragma ignored' in output

    def it_prints_a_notice_when_the_report_history_cannot_be_written(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makepyfile(target=TARGET, test_target=FAST_TEST)
        history_as_directory = pytester.path / 'coverage' / 'gremlins' / 'history.json'
        history_as_directory.mkdir(parents=True)

        result = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py', '--gremlin-report=html')

        output = result.stdout.str() + result.stderr.str()
        assert f'{NOTICE_PREFIX}Failed to persist history for report at ' in output
