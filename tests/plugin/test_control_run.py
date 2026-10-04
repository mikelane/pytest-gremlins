"""The unmutated control run decides whether a load failure can be blamed on a mutant (issue #550)."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from pytest_gremlins.control_run import (
    DIAGNOSTIC_TAIL_LINES,
    build_diagnostic,
    chunk_node_ids,
    run_control,
)


@pytest.mark.small
class DescribeChunkNodeIds:
    def it_returns_one_chunk_when_everything_fits(self) -> None:
        assert chunk_node_ids(['a.py::t1', 'a.py::t2'], max_chars=100) == [['a.py::t1', 'a.py::t2']]

    def it_splits_so_that_no_chunk_exceeds_the_limit(self) -> None:
        node_ids = ['aaaa', 'bbbb', 'cccc', 'dddd']

        assert chunk_node_ids(node_ids, max_chars=10) == [['aaaa', 'bbbb'], ['cccc', 'dddd']]

    def it_keeps_an_oversized_node_id_in_a_chunk_of_its_own(self) -> None:
        assert chunk_node_ids(['x' * 20, 'y'], max_chars=5) == [['x' * 20], ['y']]

    def it_returns_a_single_empty_chunk_for_no_node_ids(self) -> None:
        assert chunk_node_ids([], max_chars=100) == [[]]


@pytest.mark.small
class DescribeBuildDiagnostic:
    def it_starts_with_the_attribution_explanation(self) -> None:
        message = build_diagnostic('boom')

        assert message.startswith(
            'pytest-gremlins: the unmutated test suite fails to load in the gremlin subprocess, so load failures '
            "can't be attributed to mutants; they're reported as errors. Cause:"
        )

    def it_keeps_only_the_tail_of_a_long_output(self) -> None:
        output = '\n'.join(f'line {number}' for number in range(100))

        message = build_diagnostic(output)

        assert 'line 99' in message
        assert 'line 0\n' not in message
        assert message.count('line ') == DIAGNOSTIC_TAIL_LINES

    @pytest.mark.parametrize(
        ('output', 'hint'),
        [
            pytest.param('import file mismatch:\nimported module', '--import-mode', id='import-mode'),
            pytest.param('ERROR: not found: x.py::test_a[abc]', 'parametrize', id='parametrize-ids'),
            pytest.param(
                'collected 1 item\nERROR: not found: test_x.py::test_y[3f9a]\n(no match in any of [<Module>])',
                'make the ids deterministic',
                id='parametrize-ids-real-shape',
            ),
        ],
    )
    def it_adds_a_hint_for_the_common_causes(self, output: str, hint: str) -> None:
        assert hint in build_diagnostic(output)

    def it_does_not_blame_the_dunder_file_issue_for_an_import_file_mismatch(self) -> None:
        output = (
            "import file mismatch:\nimported module 'test_same_name' has this __file__ attribute:\n"
            '  /p/first/test_same_name.py\nwhich is not the same as the test file we want to collect:'
        )

        assert 'issues/525' not in build_diagnostic(output)

    @pytest.mark.parametrize(
        'output',
        [
            pytest.param("    raise ImportError('required module not found: helperlib')", id='source-line'),
            pytest.param('E   ImportError: required module not found: helperlib', id='exception-message'),
        ],
    )
    def it_ignores_not_found_text_that_is_not_pytests_own_error_line(self, output: str) -> None:
        assert 'make the ids deterministic' not in build_diagnostic(output)

    def it_adds_no_hint_for_an_unrecognized_cause(self) -> None:
        assert 'Hint' not in build_diagnostic('something else entirely')


@pytest.mark.medium
class DescribeRunControl:
    @staticmethod
    def _command(code: str) -> list[str]:
        return [sys.executable, '-c', code]

    def it_loads_cleanly_when_the_command_exits_zero(self, tmp_path: Path) -> None:
        outcome = run_control(self._command('import sys; sys.exit(0)'), [], tmp_path, {}, timeout=30)

        assert outcome.loads_cleanly is True

    @pytest.mark.parametrize('exit_code', [1, 2, 4, 5, 71])
    def it_fails_on_any_non_zero_exit(self, tmp_path: Path, exit_code: int) -> None:
        outcome = run_control(self._command(f'import sys; sys.exit({exit_code})'), [], tmp_path, {}, timeout=30)

        assert outcome.loads_cleanly is False

    def it_captures_the_output_of_a_failure(self, tmp_path: Path) -> None:
        code = 'import sys; print("out-text"); print("err-text", file=sys.stderr); sys.exit(4)'

        outcome = run_control(self._command(code), [], tmp_path, {}, timeout=30)

        assert 'out-text' in outcome.output
        assert 'err-text' in outcome.output

    def it_asks_pytest_to_only_collect_the_given_node_ids(self, tmp_path: Path) -> None:
        code = 'import sys; print(*sys.argv[1:]); sys.exit(4)'
        script = tmp_path / 'echo_args.py'
        script.write_text(code)

        outcome = run_control([sys.executable, str(script)], ['a.py::t1', 'b.py::t2'], tmp_path, {}, timeout=30)

        assert outcome.output.strip() == '--collect-only --tb=short a.py::t1 b.py::t2'

    def it_overrides_an_earlier_tb_no_so_collection_errors_keep_their_cause(self, tmp_path: Path) -> None:
        code = 'import sys; print(*sys.argv[1:]); sys.exit(4)'
        script = tmp_path / 'echo_args.py'
        script.write_text(code)

        outcome = run_control([sys.executable, str(script), '--tb=no', '-q'], [], tmp_path, {}, timeout=30)

        assert outcome.output.split()[-1] == '--tb=short'

    def it_stops_at_the_first_failing_chunk(self, tmp_path: Path) -> None:
        marker = tmp_path / 'runs.txt'
        code = f'import sys; open({str(marker)!r}, "a").write("x"); sys.exit(4)'

        outcome = run_control(
            self._command(code), ['a' * 10, 'b' * 10, 'c' * 10], tmp_path, {}, timeout=30, max_chars_per_command=12
        )

        assert outcome.loads_cleanly is False
        assert marker.read_text() == 'x'

    def it_treats_a_timeout_as_a_failure_to_load(self, tmp_path: Path) -> None:
        outcome = run_control(self._command('import time; time.sleep(30)'), [], tmp_path, {}, timeout=1)

        assert outcome.loads_cleanly is False
        assert 'timed out' in outcome.output

    def it_reports_how_long_the_control_run_took(self, tmp_path: Path) -> None:
        outcome = run_control(self._command('import time; time.sleep(0.2)'), [], tmp_path, {}, timeout=30)

        assert outcome.seconds >= 0.2
