"""Subprocess coverage support for pytest-gremlins.

When COVERAGE_PROCESS_START is set and this file is on PYTHONPATH,
every subprocess Python instance calls coverage.process_startup() and
writes its own .coverage.<pid> data file. The parent process combines
them with ``coverage combine``.

Reference: https://coverage.readthedocs.io/en/latest/subprocess.html
"""

import coverage


coverage.process_startup()
