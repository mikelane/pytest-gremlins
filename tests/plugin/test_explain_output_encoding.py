"""--gremlin-explain output holding a character stdout cannot encode does not crash the run (#1091)."""

from __future__ import annotations

import re

import pytest

TARGET = 'def add(a, b):\n    return a + b\n'
TEST_WITH_NON_ASCII_NAME = (
    'import pytest\nfrom target import add\n\n\n@pytest.mark.small\ndef test_café():\n    assert add(1, 2) == 3\n'
)
TEST_IMPORTING_NON_ASCII_MODULE = (
    'import pytest\nfrom café import add\n\n\n@pytest.mark.small\ndef test_add():\n    assert add(1, 2) == 3\n'
)


@pytest.mark.medium
class DescribeExplainOutputOnANonUtf8Stdout:
    """An accented test name is outside both ASCII and the Japanese (cp932) code page."""

    @pytest.mark.parametrize('encoding', ['ascii', 'cp932'])
    def it_finishes_an_explain_run_whose_selected_test_name_is_not_encodable(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, encoding: str
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        monkeypatch.setenv('PYTHONIOENCODING', encoding)
        pytester.makepyfile(target=TARGET, test_target=TEST_WITH_NON_ASCII_NAME)

        listing = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py', '-p', 'no:cacheprovider')
        gremlin_id = re.search(r'target_\w+_g001', listing.stdout.str()).group(0)  # type: ignore[union-attr]

        result = pytester.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=target.py', f'--gremlin-explain={gremlin_id}', '-p', 'no:cacheprovider'
        )

        assert (result.ret, 'UnicodeEncodeError' in result.stderr.str(), 'Covering set' in result.stdout.str()) == (
            pytest.ExitCode.OK,
            False,
            True,
        )

    @pytest.mark.parametrize('encoding', ['ascii', 'cp932'])
    def it_finishes_an_explain_run_whose_source_path_is_not_encodable(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, encoding: str
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        # The listing run uses UTF-8: the progress line of a normal run is not encoding-safe (outside #1091).
        monkeypatch.setenv('PYTHONIOENCODING', 'utf-8')
        pytester.makepyfile(café=TARGET, test_cafe=TEST_IMPORTING_NON_ASCII_MODULE)

        listing = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=café.py', '-p', 'no:cacheprovider')
        gremlin_id = re.search(r'\S+_g001', listing.stdout.str()).group(0)  # type: ignore[union-attr]

        monkeypatch.setenv('PYTHONIOENCODING', encoding)
        result = pytester.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=café.py', f'--gremlin-explain={gremlin_id}', '-p', 'no:cacheprovider'
        )

        assert (result.ret, 'UnicodeEncodeError' in result.stderr.str(), 'Covering set' in result.stdout.str()) == (
            pytest.ExitCode.OK,
            False,
            True,
        )
