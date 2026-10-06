"""Tests for the generated lightweight runner script.

The runner must never fabricate a verdict: a test that cannot be run as a bare
callable exits with ``LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE`` instead of 1 (zapped)
or 0 (survived).
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from pytest_gremlins.instrumentation.origin_finder import normalize_origin
from pytest_gremlins.parallel.lightweight import LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE
from pytest_gremlins.plugin import _get_lightweight_runner_script

CANNOT_VERIFY = LIGHTWEIGHT_CANNOT_VERIFY_EXIT_CODE


def _run_runner(
    tmp_path: Path,
    test_source: str,
    *node_ids: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    runner = tmp_path / 'runner.py'
    runner.write_text(_get_lightweight_runner_script(), encoding='utf-8')
    (tmp_path / 'test_sample.py').write_text(textwrap.dedent(test_source), encoding='utf-8')
    env = {'GREMLIN_ROOTDIR': str(tmp_path), 'PATH': '', 'PYTHONWARNINGS': 'default', **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(runner), *node_ids],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.mark.small
class DescribeLightweightRunnerScriptSource:
    """The generated source is self-consistent."""

    def it_is_ascii_only(self) -> None:
        assert _get_lightweight_runner_script().isascii()

    def it_embeds_the_shared_exit_code(self) -> None:
        script = _get_lightweight_runner_script()

        assert f'CANNOT_VERIFY_EXIT_CODE = {CANNOT_VERIFY}' in script

    def it_uses_an_exit_code_that_pytest_and_verdicts_do_not(self) -> None:
        assert CANNOT_VERIFY not in {0, 1, 2, 3, 4, 5}


@pytest.mark.medium
class DescribeLightweightRunnerExitCodes:
    """Verdict exit codes are 0 survived and 1 caught; anything unverifiable is distinct."""

    def it_exits_zero_when_the_test_passes(self, tmp_path: Path) -> None:
        result = _run_runner(tmp_path, 'def test_a():\n    assert True\n', 'test_sample.py::test_a')

        assert result.returncode == 0

    @pytest.mark.parametrize(
        'body',
        ['assert False', 'raise ValueError("boom")', 'raise TypeError("a real test error")'],
    )
    def it_exits_one_when_the_test_body_raises(self, tmp_path: Path, body: str) -> None:
        result = _run_runner(tmp_path, f'def test_a():\n    {body}\n', 'test_sample.py::test_a')

        assert result.returncode == 1

    def it_exits_one_when_a_method_on_a_class_fails(self, tmp_path: Path) -> None:
        source = 'class TestC:\n    def test_m(self):\n        assert False\n'

        result = _run_runner(tmp_path, source, 'test_sample.py::TestC::test_m')

        assert result.returncode == 1

    @pytest.mark.parametrize(
        ('source', 'node_id'),
        [
            pytest.param('def test_a():\n    pass\n', 'test_sample.py::test_a[1-2]', id='parametrized-id'),
            pytest.param('def test_a():\n    pass\n', 'test_sample.py::test_missing', id='missing-function'),
            pytest.param('def test_a():\n    pass\n', 'missing_file.py::test_a', id='missing-module-file'),
            pytest.param('def test_a():\n    pass\n', 'test_sample.py::TestMissing::test_a', id='missing-class'),
            pytest.param('class TestC:\n    pass\n', 'test_sample.py::TestC::test_missing', id='missing-method'),
            pytest.param('def test_a():\n    pass\n', 'test_sample.py::A::B::test_a', id='unexpected-node-id-format'),
            pytest.param('raise RuntimeError("import time")\n', 'test_sample.py::test_a', id='module-load-failure'),
            pytest.param('def test_a(tmp_path):\n    pass\n', 'test_sample.py::test_a', id='fixture-argument'),
            pytest.param('async def test_a():\n    assert False\n', 'test_sample.py::test_a', id='coroutine'),
            pytest.param(
                'import pytest\n\ndef test_a():\n    pytest.skip("nope")\n', 'test_sample.py::test_a', id='skipped'
            ),
            pytest.param(
                'import unittest\n\ndef test_a():\n    raise unittest.SkipTest("nope")\n',
                'test_sample.py::test_a',
                id='unittest-skip',
            ),
        ],
    )
    def it_exits_with_the_distinct_code_when_it_cannot_verify(self, tmp_path: Path, source: str, node_id: str) -> None:
        result = _run_runner(tmp_path, source, node_id)

        assert result.returncode == CANNOT_VERIFY

    def it_explains_why_it_could_not_verify_on_stderr(self, tmp_path: Path) -> None:
        result = _run_runner(tmp_path, 'def test_a():\n    pass\n', 'test_sample.py::test_a[1]')

        assert 'test_a[1]' in result.stderr

    def it_does_not_emit_a_never_awaited_warning_for_a_coroutine(self, tmp_path: Path) -> None:
        result = _run_runner(tmp_path, 'async def test_a():\n    assert True\n', 'test_sample.py::test_a')

        assert 'never awaited' not in result.stderr

    def it_exits_one_when_a_later_test_catches_after_an_unverifiable_one(self, tmp_path: Path) -> None:
        source = 'def test_a():\n    pass\n\ndef test_b():\n    assert False\n'

        result = _run_runner(tmp_path, source, 'test_sample.py::test_a[1]', 'test_sample.py::test_b')

        assert result.returncode == 1

    def it_exits_with_the_distinct_code_when_an_unverifiable_test_precedes_passing_ones(self, tmp_path: Path) -> None:
        source = 'def test_a():\n    pass\n\ndef test_b():\n    pass\n'

        result = _run_runner(tmp_path, source, 'test_sample.py::test_a[1]', 'test_sample.py::test_b')

        assert result.returncode == CANNOT_VERIFY

    def it_exits_with_the_distinct_code_when_setup_crashes(self, tmp_path: Path) -> None:
        bad_sources = tmp_path / 'sources.json'
        bad_sources.write_text('not json', encoding='utf-8')

        result = _run_runner(
            tmp_path,
            'def test_a():\n    pass\n',
            'test_sample.py::test_a',
            env_extra={'PYTEST_GREMLINS_SOURCES_FILE': str(bad_sources)},
        )

        assert result.returncode == CANNOT_VERIFY


@pytest.mark.medium
class DescribeLightweightRunnerInstrumentedModules:
    """A module the runner's import hook loads keeps the path of the source it was built from."""

    def it_gives_the_instrumented_module_its_origin_as_file(self, tmp_path: Path) -> None:
        origin = tmp_path / 'target.py'
        origin.write_text('VALUE = 0\n', encoding='utf-8')
        sources = tmp_path / 'sources.json'
        entry = {'source': 'VALUE = 1\n', 'origin': str(origin)}
        sources.write_text(json.dumps({normalize_origin(str(origin)): entry}), encoding='utf-8')
        test_source = f"""
            import os
            import target

            def test_a():
                # The import system may spell the path through a '.' sys.path entry; it must still be the file.
                assert target.VALUE == 1
                assert os.path.realpath(target.__file__) == {str(origin)!r}
                assert target.__spec__.origin == target.__file__
            """

        result = _run_runner(
            tmp_path,
            test_source,
            'test_sample.py::test_a',
            env_extra={'PYTEST_GREMLINS_SOURCES_FILE': str(sources)},
        )

        assert result.returncode == 0, result.stdout + result.stderr
