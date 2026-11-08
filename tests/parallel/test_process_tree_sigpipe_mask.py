"""The SIGPIPE guard around the watchdog write never leaves SIGPIPE blocked (#975)."""

from __future__ import annotations

import signal
import sys

import pytest

from pytest_gremlins import process_tree

pytestmark = [
    pytest.mark.small,
    pytest.mark.skipif(sys.platform == 'win32', reason='signal masks are POSIX'),
]


def _is_blocked() -> bool:
    return signal.SIGPIPE in signal.pthread_sigmask(signal.SIG_BLOCK, set())


class DescribeSigpipeBlocked:
    def it_restores_the_mask_after_the_block(self) -> None:
        with process_tree._sigpipe_blocked():
            assert _is_blocked()

        assert not _is_blocked()

    def it_restores_the_mask_when_the_body_raises(self) -> None:
        with pytest.raises(OSError, match='broken'), process_tree._sigpipe_blocked():
            raise OSError('broken')

        assert not _is_blocked()

    def it_restores_the_mask_when_consuming_the_pending_signal_is_interrupted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = iter([set(), {signal.SIGPIPE}])
        monkeypatch.setattr(signal, 'sigpending', lambda: next(pending))

        def interrupted(_signals: set[signal.Signals]) -> int:
            raise KeyboardInterrupt

        monkeypatch.setattr(signal, 'sigwait', interrupted)

        with pytest.raises(KeyboardInterrupt), process_tree._sigpipe_blocked():
            pass

        assert not _is_blocked()
