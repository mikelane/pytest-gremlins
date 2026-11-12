"""Adversarial QA run 2 (issue #996): a failed pre-scan shard is reported to the user once, not twice."""

from __future__ import annotations

import pytest

_CRASHING_SHARD_TEST = (
    "import os\n\n\ndef test_crash():\n    if os.environ.get('COVERAGE_FILE', '').endswith('coverage.data'):\n"
    '        os._exit(7)\n    assert True\n'
)


@pytest.mark.medium
class DescribeFailedShardReportedOnce:
    def it_prints_the_failed_shard_line_once_when_pytest_logging_is_disabled(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(sample='def double(value):\n    return value * 2\n')
        pytester.makepyfile(test_a='from sample import double\n\n\ndef test_a():\n    assert double(2) == 4\n')
        pytester.makepyfile(test_b=_CRASHING_SHARD_TEST)

        result = pytester.runpytest_subprocess(
            '--gremlins',
            '--gremlin-targets=sample.py',
            '--gremlin-operators=arithmetic',
            '--gremlin-prescan-workers=2',
            '-p',
            'no:cacheprovider',
            '-p',
            'no:logging',
        )

        assert result.stderr.str().count('shard 1 exited with code 7') == 1
