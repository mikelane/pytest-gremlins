"""The generated pre-scan coveragerc is UTF-8 whatever the interpreter's locale encoding is.

coverage.py reads its rcfile with ``encoding="utf-8"`` (``HandyConfigParser.read``),
but ``_run_tests_with_coverage`` used to write ``.coveragerc.gremlins`` with the locale
encoding. A gremlin source path containing a non-ASCII character (e.g. a Windows
user directory ``C:\\Users\\Jos\xe9``) is written as cp1252 bytes on Windows, which
coverage.py then fails to decode -- the same bug class as #484.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.medium
class DescribeCoveragercEncoding:
    """The coveragerc is UTF-8 whatever the interpreter's locale encoding is."""

    def it_writes_a_non_ascii_include_path_as_utf8_under_an_ascii_locale(self, tmp_path: Path) -> None:
        # Build the non-ASCII path inside the child from an ASCII escape: argv must stay ASCII
        # because Linux decodes it under the C locale.
        script = textwrap.dedent(
            rf"""
            import sys
            from pathlib import Path
            from pytest_gremlins import plugin

            source_path = str(Path({str(tmp_path)!r}) / 'Jos\xe9' / 'mod.py')

            def fake_run(cmd, **kwargs):
                rcfile = next(arg for arg in cmd if arg.startswith('--rcfile=')).split('=', 1)[1]
                sys.stdout.buffer.write(Path(rcfile).read_bytes())
                raise plugin.subprocess.TimeoutExpired(cmd, 0)

            plugin.subprocess.run = fake_run
            try:
                plugin._run_tests_with_coverage(['t.py::t'], Path({str(tmp_path)!r}), coverage_include=[source_path])
            except plugin.CoveragePrescanTimeoutError:
                pass
            """
        )
        assert script.isascii(), 'child script must be ASCII so argv decodes the same on every platform'
        env = {**os.environ, 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0', 'LC_ALL': 'C', 'LANG': 'C'}

        completed = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, check=False)

        assert completed.returncode == 0, completed.stderr.decode('utf-8', 'replace')
        # Verify the path appears in the coveragerc output as UTF-8-encoded escape sequence
        assert 'Jos\xe9' in completed.stdout.decode('utf-8')
