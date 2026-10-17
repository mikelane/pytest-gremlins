"""A pytest that changes its private assert-rewriting API ends the run instead of fabricating verdicts (#617)."""

from __future__ import annotations

import importlib.machinery
from types import ModuleType

from _pytest.assertion.rewrite import AssertionRewritingHook
import pytest

from pytest_gremlins.instrumentation.origin_finder import (
    REWRITE_API_BROKEN_EXIT_CODE,
    GremlinLoader,
)

ORIGIN = '/project/src/served_mod.py'
SOURCE = 'def check(n):\n    assert n > 0\n'


class _ProcessExitError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def _exit_by_raising(code: int) -> None:
    raise _ProcessExitError(code)


def _served_module() -> ModuleType:
    module = ModuleType('served_mod')
    module.__spec__ = importlib.machinery.ModuleSpec('served_mod', None, origin=ORIGIN)
    return module


@pytest.fixture(autouse=True)
def _intercept_process_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('os._exit', _exit_by_raising)


def _load(hook: AssertionRewritingHook) -> None:
    GremlinLoader(None, hook, source=SOURCE).exec_module(_served_module())


@pytest.mark.small
class DescribeGremlinLoaderWhenPytestsRewriteApiChanged:
    """A gremlin run whose asserts cannot be rewritten ends as a runner error, never as a test failure."""

    def it_exits_with_the_runner_error_code_when_rewrite_asserts_changes_signature(
        self, pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def renamed_signature(*, tree_only: object) -> None:
            raise AssertionError(tree_only)

        monkeypatch.setattr('_pytest.assertion.rewrite.rewrite_asserts', renamed_signature)

        with pytest.raises(_ProcessExitError) as exit_info:
            _load(AssertionRewritingHook(pytestconfig))

        assert exit_info.value.code == REWRITE_API_BROKEN_EXIT_CODE

    def it_exits_when_rewrite_asserts_is_gone(
        self, pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delattr('_pytest.assertion.rewrite.rewrite_asserts')

        with pytest.raises(_ProcessExitError):
            _load(AssertionRewritingHook(pytestconfig))

    def it_exits_when_the_hook_has_no_rewritten_names(self, pytestconfig: pytest.Config) -> None:
        hook = AssertionRewritingHook(pytestconfig)
        del hook._rewritten_names

        with pytest.raises(_ProcessExitError):
            _load(hook)

    def it_exits_when_the_hook_has_no_config(self, pytestconfig: pytest.Config) -> None:
        hook = AssertionRewritingHook(pytestconfig)
        del hook.config

        with pytest.raises(_ProcessExitError):
            _load(hook)

    def it_names_the_pytest_version_on_stderr(
        self, pytestconfig: pytest.Config, capsys: pytest.CaptureFixture[str]
    ) -> None:
        hook = AssertionRewritingHook(pytestconfig)
        del hook.config

        with pytest.raises(_ProcessExitError):
            _load(hook)

        assert f'pytest {pytest.__version__}' in capsys.readouterr().err

    def it_explains_that_assertion_rewriting_could_not_be_applied(
        self, pytestconfig: pytest.Config, capsys: pytest.CaptureFixture[str]
    ) -> None:
        hook = AssertionRewritingHook(pytestconfig)
        del hook.config

        with pytest.raises(_ProcessExitError):
            _load(hook)

        assert 'assertion rewriting' in capsys.readouterr().err

    def it_does_not_exit_when_rewriting_overflows_the_stack(
        self, pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def overflow(*_args: object, **_kwargs: object) -> None:
            raise RecursionError

        monkeypatch.setattr('_pytest.assertion.rewrite.rewrite_asserts', overflow)

        _load(AssertionRewritingHook(pytestconfig))
