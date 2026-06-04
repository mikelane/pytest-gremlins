"""Adversarial test: coverage_include must match source paths with glob-special chars.

The cold coverage run writes the resolved gremlin source paths into the
``[run] include =`` section of the generated coveragerc.  coverage.py treats
``include`` entries as fnmatch globs, so a path containing ``[``/``]``/``?``/``*``
is interpreted as a glob pattern and fails to match its own literal path.

When that happens the gremlin source file gets NO coverage -> no covering tests
are selected -> the gremlin survives falsely.  This is the #387 false-survivor
class.  The old ``source = .`` behavior did not have this problem.
"""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from pytest_gremlins.plugin import _run_tests_with_coverage


@pytest.mark.medium
class DescribeCoverageIncludeGlobSpecialChars:
    """coverage_include with glob-special chars in the path."""

    def it_records_coverage_for_source_in_bracketed_directory(self) -> None:
        """A gremlin source file in a dir containing ``[`` still gets coverage."""
        root = Path(tempfile.mkdtemp())
        srcdir = root / 'mod[v2]'
        srcdir.mkdir()
        (srcdir / '__init__.py').write_text('')
        src = srcdir / 'calc.py'
        src.write_text('def add(a, b):\n    return a + b\n')
        test = root / 'test_calc.py'
        test.write_text(
            'import sys\n'
            f'sys.path.insert(0, {str(root)!r})\n'
            'from importlib import import_module\n'
            "m = import_module('mod[v2].calc')\n"
            'def test_add():\n'
            '    assert m.add(1, 2) == 3\n'
        )

        include = [str(src.resolve())]
        data = _run_tests_with_coverage(['test_calc.py'], root, coverage_include=include)

        covered_files = {Path(f).resolve() for file_cov in data.values() for f in file_cov}
        assert src.resolve() in covered_files, (
            f'Source file in bracketed dir got no coverage. covered_files={covered_files}. '
            'coverage_include glob failed to match the literal path -> false survivor.'
        )
