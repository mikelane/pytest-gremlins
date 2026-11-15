"""Fixtures shared by the parallel-execution tests."""

from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True, scope='session')
def sigint_is_not_ignored() -> Generator[None, None, None]:
    """Give a test run that was started with SIGINT ignored the usual Ctrl-C handler (#1004).

    A non-interactive shell starts a background job (``pytest &``) with SIGINT ignored, and every child inherits that
    across ``exec``. A caller that ignores SIGINT can never be interrupted, so the tests that interrupt
    ``run_bounded`` would wait forever for something that cannot happen, on every Python version. A Python handler,
    unlike an ignored signal, is reset to the default by ``exec``, so the children get Python's own handler again.
    """
    if sys.platform == 'win32' or signal.getsignal(signal.SIGINT) != signal.SIG_IGN:
        yield
        return
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
