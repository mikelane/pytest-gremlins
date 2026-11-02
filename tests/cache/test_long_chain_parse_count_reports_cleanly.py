"""The long-chain parse-count test reports a regression as a plain failure, not an INTERNALERROR (#924)."""

from __future__ import annotations

from pathlib import Path

import pytest

PROBE = Path(__file__).with_name('test_conftest_operator_imports_label_relative.py')

REPARSING_WALK = """
import pytest_gremlins.cache.versions as versions

_real_walk = versions._local_modules_imported_by


def _walk_twice(conftests, project_root):
    conftests = list(conftests)
    _real_walk(conftests, project_root)
    return _real_walk(conftests, project_root)


versions._local_modules_imported_by = _walk_twice
"""


@pytest.mark.medium
class DescribeLongChainParseCountProbe:
    def it_reports_a_walk_that_reparses_modules_as_one_failed_test(
        self,
        pytester: pytest.Pytester,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        pytester.makepyfile(reparsing_walk=REPARSING_WALK)
        pytester.makepyfile(test_probe=PROBE.read_text())

        result = pytester.runpytest_subprocess(
            '-p',
            'reparsing_walk',
            '-p',
            'no:randomly',
            '-o',
            'python_classes=Describe*',
            '-o',
            'python_functions=it_*',
            '-k',
            'long_chain',
            'test_probe.py',
        )

        assert (result.ret, 'INTERNALERROR' in result.stdout.str()) == (pytest.ExitCode.TESTS_FAILED, False)
