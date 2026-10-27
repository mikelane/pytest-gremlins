"""Run-time diagnostics reach the user even when ``filterwarnings = error`` is set (issue #543)."""

from __future__ import annotations

import pytest

PYTEST_INI_WITH_ESCALATED_WARNINGS = '[pytest]\nfilterwarnings =\n    error\n'
TARGET = 'def add(a, b):\n    return a + b\n'
FAST_TEST = (
    'import pytest\nfrom target import add\n\n\n@pytest.mark.small\ndef test_add():\n    assert add(1, 2) == 3\n'
)
SLOW_UNDER_COVERAGE_TEST = (
    'import sys\nimport time\n\nimport pytest\nfrom target import add\n\n\n'
    '@pytest.mark.small\ndef test_add():\n'
    "    spec = getattr(sys.modules['__main__'], '__spec__', None)\n"
    "    if getattr(spec, 'name', None) == 'pytest_gremlins.coverage.prescan_main':\n        time.sleep(30)\n"
    '    assert add(1, 2) == 3\n'
)
EMPTY_COVERAGE_CONFTEST = (
    'import pytest_gremlins.plugin as gremlins_plugin\n\n'
    'gremlins_plugin._run_tests_with_coverage = lambda *args, **kwargs: {}\n'
)
PARTIAL_COVERAGE_CONFTEST = (
    'import pytest_gremlins.plugin as gremlins_plugin\n\n'
    'PARTIAL = {"unrelated.py": {"1": ["test_target.py::test_add"]}}\n'
    'gremlins_plugin._run_tests_with_coverage = lambda *args, **kwargs: PARTIAL\n'
)
TRACEBACK_MARKER = 'Traceback (most recent call last)'


@pytest.mark.medium
class DescribeDiagnosticsUnderFilterwarningsError:
    """A user's ``filterwarnings = error`` cannot turn the plugin's own diagnostics into a crash."""

    def it_reports_empty_coverage_data_without_crashing(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makeini(PYTEST_INI_WITH_ESCALATED_WARNINGS)
        pytester.makeconftest(EMPTY_COVERAGE_CONFTEST)
        pytester.makepyfile(target=TARGET, test_target=FAST_TEST)

        result = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        output = result.stdout.str() + result.stderr.str()
        assert result.ret == 0
        assert TRACEBACK_MARKER not in output
        assert 'Coverage collection returned no data' in output

    def it_reports_a_pre_scan_timeout_without_crashing(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makeini(PYTEST_INI_WITH_ESCALATED_WARNINGS)
        pytester.makepyfile(target=TARGET, test_target=SLOW_UNDER_COVERAGE_TEST)

        result = pytester.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=target.py', '--gremlin-coverage-timeout=1'
        )

        output = result.stdout.str() + result.stderr.str()
        assert result.ret == 0
        assert TRACEBACK_MARKER not in output
        assert 'coverage pre-scan exceeded 1s' in output

    def it_survives_a_partial_coverage_map_without_crashing(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        pytester.makeini(PYTEST_INI_WITH_ESCALATED_WARNINGS)
        pytester.makeconftest(PARTIAL_COVERAGE_CONFTEST)
        pytester.makepyfile(target=TARGET, test_target=FAST_TEST)

        result = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py')

        assert result.ret == 0
        assert TRACEBACK_MARKER not in result.stdout.str() + result.stderr.str()
        assert 'Zapped: 2 gremlins (100%)' in result.stdout.str()
