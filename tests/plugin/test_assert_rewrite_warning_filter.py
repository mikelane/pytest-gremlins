"""The child pytest processes ignore only the assert-rewrite warning that pytest-gremlins itself provokes (issue #838).

A non-editable install imports ``pytest_gremlins`` before pytest can mark it for assertion rewriting, so pytest warns
``Module already imported so cannot be rewritten``. Under ``filterwarnings = ["error"]`` that killed the child. The
filter that tolerates it must name this one module, so the same warning for the user's own modules still surfaces.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from pytest_gremlins.plugin import (
    ASSERT_REWRITE_WARNING_FILTER,
    _run_tests_with_coverage,
)

pytest.importorskip('xdist')

RunPytestIsolated = Callable[..., pytest.RunResult]

WARNINGS_AS_ERRORS_PYPROJECT = '[tool.pytest.ini_options]\nfilterwarnings = ["error"]\n'
IMPORT_THEN_REGISTER_CONFTEST = 'import {module}\nimport pytest\n\npytest.register_assert_rewrite({module!r})\n'


SMALL_TEST = 'import pytest\n\n\n@pytest.mark.small\ndef test_one():\n    assert True\n'


def _write_project(pytester: pytest.Pytester, module: str) -> None:
    pytester.makepyprojecttoml(WARNINGS_AS_ERRORS_PYPROJECT)
    pytester.path.joinpath('usermod.py').write_text('VALUE = 1\n')
    pytester.makeconftest(IMPORT_THEN_REGISTER_CONFTEST.format(module=module))
    pytester.path.joinpath('test_one.py').write_text(SMALL_TEST)


@pytest.mark.small
class DescribeAssertRewriteWarningFilter:
    """The filter text itself."""

    def it_names_only_the_pytest_gremlins_module(self) -> None:
        assert ASSERT_REWRITE_WARNING_FILTER == (
            'ignore:Module already imported so cannot be rewritten; pytest_gremlins:pytest.PytestAssertRewriteWarning'
        )


@pytest.mark.medium
class DescribePrescanCommandAssertRewriteFilter:
    """The coverage pre-scan command carries the narrow filter, not a blanket ignore."""

    def it_passes_the_narrow_filter_and_no_blanket_ignore(self, tmp_path: Path) -> None:
        captured_cmd: list[str] = []

        def capture_cmd(cmd: list[str], **_kwargs: object) -> None:
            captured_cmd.extend(cmd)

        with patch('pytest_gremlins.plugin.subprocess.run', autospec=True, side_effect=capture_cmd):
            _run_tests_with_coverage(['tests/test_a.py::test_one'], tmp_path)

        warning_filters = [captured_cmd[i + 1] for i, value in enumerate(captured_cmd) if value == '-W']
        assert warning_filters == [ASSERT_REWRITE_WARNING_FILTER]


@pytest.mark.medium
class DescribeAssertRewriteFilterInAChildPytest:
    """A child pytest started with the filter, under ``filterwarnings = ["error"]``."""

    def it_tolerates_the_warning_for_pytest_gremlins(
        self, pytester: pytest.Pytester, run_pytest_isolated: RunPytestIsolated
    ) -> None:
        _write_project(pytester, 'pytest_gremlins')

        result = run_pytest_isolated(pytester, '-W', ASSERT_REWRITE_WARNING_FILTER, '-p', 'no:gremlins')

        assert result.ret == 0

    def it_still_raises_the_warning_for_the_users_own_module(
        self, pytester: pytest.Pytester, run_pytest_isolated: RunPytestIsolated
    ) -> None:
        _write_project(pytester, 'usermod')

        result = run_pytest_isolated(pytester, '-W', ASSERT_REWRITE_WARNING_FILTER, '-p', 'no:gremlins')

        result.stderr.fnmatch_lines(['*Module already imported so cannot be rewritten; usermod*'])
