"""A test that runs pytest in-process must not end the outer gremlin session."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
)
from unittest.mock import (
    MagicMock,
    patch,
)

from _pytest.terminal import TerminalReporter
import pytest

from pytest_gremlins.plugin import (
    GremlinSession,
    _BaselineRecorder,
    _get_session,
    _own_session_key,
    _set_session,
    pytest_configure,
    pytest_sessionfinish,
    pytest_terminal_summary,
    pytest_unconfigure,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture(autouse=True)
def _utf8_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every pytest child these tests spawn write its output as UTF-8."""
    monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')


def _unconfigure(config: Any) -> None:
    unconfigure = pytest_unconfigure(config)
    next(unconfigure)
    with pytest.raises(StopIteration):
        next(unconfigure)


@pytest.mark.medium
class DescribeConfigureOwnsTheSession:
    """While a Config is configured, the installed session is its own, even when configure exits early."""

    def it_never_leaves_the_outer_session_installed_when_configure_exits(
        self, tmp_path: Path, make_pytest_config: Callable[..., Any]
    ) -> None:
        outer = GremlinSession(enabled=True)
        _set_session(outer)
        config = make_pytest_config(tmp_path, gremlins=True)
        config.option.gremlin_coverage_timeout = 0

        with pytest.raises(pytest.exit.Exception):
            pytest_configure(config)

        assert _get_session() is config.stash[_own_session_key]

    def it_restores_the_outer_session_when_the_inner_config_unconfigures(
        self, tmp_path: Path, make_pytest_config: Callable[..., Any]
    ) -> None:
        outer = GremlinSession(enabled=True)
        _set_session(outer)
        config = make_pytest_config(tmp_path, gremlins=False)

        pytest_configure(config)
        _unconfigure(config)

        assert _get_session() is outer

    def it_restores_the_outer_session_when_inner_configs_unconfigure_out_of_order(
        self, tmp_path: Path, make_pytest_config: Callable[..., Any]
    ) -> None:
        outer = GremlinSession(enabled=True)
        _set_session(outer)
        first = make_pytest_config(tmp_path, gremlins=False)
        second = make_pytest_config(tmp_path, gremlins=False)

        pytest_configure(first)
        pytest_configure(second)
        _unconfigure(first)

        assert _get_session() is second.stash[_own_session_key]

        _unconfigure(second)

        assert _get_session() is outer

    def it_records_reports_only_into_the_session_of_the_config_that_produced_them(
        self, tmp_path: Path, make_pytest_config: Callable[..., Any]
    ) -> None:
        outer = make_pytest_config(tmp_path, gremlins=False)
        inner = make_pytest_config(tmp_path, gremlins=False)
        outer_session = GremlinSession(enabled=True)
        inner_session = GremlinSession(enabled=True)
        outer.stash[_own_session_key] = outer_session
        inner.stash[_own_session_key] = inner_session
        failed = pytest.TestReport('test_x.py::test_a', ('test_x.py', 0, 'test_a'), {}, 'failed', None, 'call')

        _BaselineRecorder(outer).pytest_runtest_logreport(failed)

        assert (outer_session.baseline_failed_test_ids, inner_session.baseline_failed_test_ids) == (
            {'test_x.py::test_a'},
            set(),
        )


@pytest.mark.medium
class DescribeNestedPytestSession:
    """A suite containing a pytester test still gets its mutation report."""

    def it_reports_gremlins_when_a_test_runs_pytest_in_process(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(
            core_module='def sub(a, b):\n    return a - b\n',
        )
        pytester_with_markers.makepyfile(
            test_core=('from core_module import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n'),
            test_nested=(
                'import pytest\n'
                '\n'
                'pytest_plugins = ["pytester"]\n'
                '\n'
                '@pytest.mark.medium\n'
                'def test_an_inner_session_runs(pytester):\n'
                '    pytester.makepyfile(test_inner="def test_inner():\\n    assert True\\n")\n'
                '    pytester.runpytest_inprocess().assert_outcomes(passed=1)\n'
            ),
        )

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=core_module.py')

        result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*', 'Zapped: * gremlins*'])

    @pytest.mark.parametrize(
        ('inner_conftest', 'inner_args'),
        [
            (
                'import pytest\\n'
                '\\n'
                '@pytest.hookimpl(tryfirst=True)\\n'
                'def pytest_configure(config):\\n'
                '    raise RuntimeError(\\"inner configure fails\\")\\n',
                '',
            ),
            ('', '"--gremlins", "--gremlin-coverage-timeout=0"'),
            (
                'import pytest\\n'
                '\\n'
                '@pytest.hookimpl(tryfirst=True)\\n'
                'def pytest_unconfigure(config):\\n'
                '    raise RuntimeError(\\"inner unconfigure fails\\")\\n',
                '',
            ),
        ],
        ids=['before_gremlins_configures', 'inside_gremlins_configure', 'before_gremlins_unconfigures'],
    )
    def it_reports_gremlins_when_an_inner_session_fails(
        self,
        pytester_with_markers: pytest.Pytester,
        inner_conftest: str,
        inner_args: str,
    ) -> None:
        pytester_with_markers.makepyfile(
            core_module='def sub(a, b):\n    return a - b\n',
        )
        pytester_with_markers.makepyfile(
            test_core=('from core_module import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n'),
            test_nested=(
                'import pytest\n'
                '\n'
                'pytest_plugins = ["pytester"]\n'
                '\n'
                '@pytest.mark.medium\n'
                'def test_an_inner_session_fails(pytester):\n'
                f'    pytester.makeconftest("{inner_conftest}")\n'
                '    pytester.makepyfile(test_inner="def test_inner():\\n    assert True\\n")\n'
                f'    pytester.runpytest_inprocess({inner_args})\n'
            ),
        )

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-cache', '--gremlin-targets=core_module.py'
        )

        result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*', 'Zapped: * gremlins*'])
        result.stdout.no_fnmatch_line('Error: *')

    def it_keeps_an_inner_failing_test_out_of_the_outer_baseline(self, pytester_with_markers: pytest.Pytester) -> None:
        pytester_with_markers.makepyfile(
            core_module='def sub(a, b):\n    return a - b\n',
        )
        pytester_with_markers.makepyfile(
            test_core=('from core_module import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n'),
            test_nested=(
                'import pytest\n'
                '\n'
                'pytest_plugins = ["pytester"]\n'
                '\n'
                '@pytest.mark.medium\n'
                'def test_an_inner_test_fails(pytester):\n'
                '    pytester.makepyfile(test_inner="def test_inner():\\n    assert False\\n")\n'
                '    pytester.runpytest_inprocess().assert_outcomes(failed=1)\n'
            ),
        )

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=core_module.py')

        result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*', 'Zapped: * gremlins*'])
        result.stderr.no_fnmatch_line('*skipping mutation testing*')

    def it_counts_an_outer_failure_while_an_inner_config_is_still_configured(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(
            core_module='def sub(a, b):\n    return a - b\n',
        )
        pytester_with_markers.makepyfile(
            test_core=('from core_module import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n'),
            test_nested=(
                'import pytest\n'
                '\n'
                'pytest_plugins = ["pytester"]\n'
                '\n'
                '@pytest.mark.medium\n'
                'def test_fails_with_an_inner_config_open(pytester):\n'
                '    pytester.parseconfigure()\n'
                '    assert False\n'
            ),
        )

        result = pytester_with_markers.runpytest_subprocess('--gremlins', '--gremlin-targets=core_module.py')

        result.stderr.fnmatch_lines(['*skipping mutation testing because 1 baseline test(s) failed*'])

    def it_reports_gremlins_when_inner_configs_unconfigure_out_of_order(
        self, pytester_with_markers: pytest.Pytester
    ) -> None:
        pytester_with_markers.makepyfile(
            core_module='def sub(a, b):\n    return a - b\n',
        )
        pytester_with_markers.makepyfile(
            test_core=('from core_module import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n'),
            test_nested=(
                'import pytest\n'
                '\n'
                'pytest_plugins = ["pytester"]\n'
                '\n'
                '@pytest.mark.medium\n'
                'def test_two_inner_configs(pytester):\n'
                '    first = pytester.parseconfigure()\n'
                '    pytester.parseconfigure()\n'
                '    first._ensure_unconfigure()\n'
            ),
        )

        result = pytester_with_markers.runpytest_subprocess(
            '--gremlins', '--gremlin-cache', '--gremlin-targets=core_module.py'
        )

        result.stdout.fnmatch_lines(['*pytest-gremlins mutation report*', 'Zapped: * gremlins*'])
        result.stdout.no_fnmatch_line('Error: *')


class _RaisingCache:
    def close(self) -> None:
        msg = 'close failed'
        raise RuntimeError(msg)


@pytest.mark.medium
class DescribeReleaseSessionWhenCacheCloseRaises:
    """A failing cache close must not strand the global on the dead owned session."""

    def it_restores_the_displaced_session_and_propagates_the_error(
        self, tmp_path: Path, make_pytest_config: Callable[..., Any]
    ) -> None:
        outer = GremlinSession(enabled=True)
        _set_session(outer)
        config = make_pytest_config(tmp_path, gremlins=False)

        pytest_configure(config)
        config.stash[_own_session_key].cache = _RaisingCache()

        with pytest.raises(RuntimeError, match='close failed'):
            _unconfigure(config)

        assert _get_session() is outer


@pytest.mark.medium
class DescribeHooksReadTheSessionTheirConfigOwns:
    """Hooks read the session their own Config owns, even when the global was swapped."""

    def it_reports_the_owned_session_notices_in_the_terminal_summary(
        self, tmp_path: Path, make_pytest_config: Callable[..., Any]
    ) -> None:
        config = make_pytest_config(tmp_path, gremlins=False)
        owned = GremlinSession(enabled=True)
        owned.terminal_notices.append('owned-notice')
        config.stash[_own_session_key] = owned
        _set_session(GremlinSession(enabled=True))
        reporter = MagicMock(spec=TerminalReporter)

        pytest_terminal_summary(reporter, exitstatus=0, config=config)

        reporter.write_line.assert_any_call('owned-notice')

    def it_does_nothing_in_the_terminal_summary_when_the_config_owns_no_session(
        self, tmp_path: Path, make_pytest_config: Callable[..., Any]
    ) -> None:
        config = make_pytest_config(tmp_path, gremlins=False)
        stray = GremlinSession(enabled=True)
        stray.terminal_notices.append('stray-notice')
        _set_session(stray)
        reporter = MagicMock(spec=TerminalReporter)

        pytest_terminal_summary(reporter, exitstatus=0, config=config)

        reporter.write_line.assert_not_called()

    def it_gates_the_sessionfinish_on_the_owned_sessions_baseline(
        self, tmp_path: Path, make_pytest_config: Callable[..., Any]
    ) -> None:
        config = make_pytest_config(tmp_path, gremlins=False)
        owned = GremlinSession(enabled=True)
        config.stash[_own_session_key] = owned
        swapped = GremlinSession(enabled=True)
        _set_session(swapped)
        session = MagicMock(spec=pytest.Session)
        session.config = config

        with patch('pytest_gremlins.plugin._skip_mutation_unless_baseline_is_green') as gate:
            gate.return_value = True
            pytest_sessionfinish(session, exitstatus=1)

        assert gate.call_args.args[0] is owned
