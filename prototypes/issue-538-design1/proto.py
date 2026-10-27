"""Throwaway design-1 prototype: collect once, re-run the same items N times in one pytest session."""

import sys
import time

import pytest

ROUNDS = int(sys.argv[2])


class Loop:
    verdicts: list = []
    timings: list = []

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtestloop(self, session) -> bool:
        for _ in range(ROUNDS):
            start = time.perf_counter()
            outcomes = []
            for i, item in enumerate(session.items):
                nextitem = session.items[i + 1] if i + 1 < len(session.items) else None
                item.ihook.pytest_runtest_protocol(item=item, nextitem=nextitem)
                outcomes.append(item.nodeid)
            self.timings.append((time.perf_counter() - start) * 1000)
        return True

    def pytest_runtest_logreport(self, report) -> None:
        if report.when == 'call':
            self.verdicts.append((report.nodeid.split('::')[-1], report.outcome))


loop = Loop()
pytest.main(['-q', '-p', 'no:cacheprovider', '-p', 'no:gremlins', sys.argv[1]], plugins=[loop])
print('VERDICTS', loop.verdicts)
print('ROUND_MS', [f'{t:.1f}' for t in loop.timings])
