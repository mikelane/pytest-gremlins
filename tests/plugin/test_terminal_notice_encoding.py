"""A terminal notice holding a character stdout cannot encode does not crash the run (adversarial QA, #982)."""

from __future__ import annotations

import pytest

PRAGMA_TARGET = 'def add(a, b):\n    return a + b  # gremlin: pardon[no-such-code] because\n'
FAST_TEST = (
    'import pytest\nfrom target import add\n\n\n@pytest.mark.small\ndef test_add():\n    assert add(1, 2) == 3\n'
)


@pytest.mark.medium
class DescribeNoticeOnANonUtf8Stdout:
    """Japanese (cp932) and Korean (cp949) Windows code pages and ASCII cannot encode the em dash in pragma notices."""

    @pytest.mark.parametrize('encoding', ['ascii', 'cp932'])
    def it_finishes_a_gremlin_explain_run_without_an_internal_error(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, encoding: str
    ) -> None:
        monkeypatch.delenv('COVERAGE_PROCESS_START', raising=False)
        monkeypatch.setenv('PYTHONIOENCODING', encoding)
        pytester.makepyfile(target=PRAGMA_TARGET, test_target=FAST_TEST)

        result = pytester.runpytest_subprocess(
            '--gremlins', '--gremlin-targets=target.py', '--gremlin-explain=nope', '-p', 'no:cacheprovider'
        )

        assert (result.ret, 'UnicodeEncodeError' in result.stderr.str()) == (pytest.ExitCode.OK, False)
