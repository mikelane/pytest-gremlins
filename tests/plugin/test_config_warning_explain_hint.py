"""Config warnings must not change the --gremlin-explain skipped-files hint (issue #566)."""

from __future__ import annotations

import pytest

_NO_CATEGORIES = ('-p', 'no:test_categories')
_TARGET = 'def add(a, b):\n    return a + b\n'
_NO_GREMLIN_TARGET = 'X = 1\n'
_TEST = 'from target import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'
_PLAIN_TEST = 'def test_ok():\n    assert True\n'
_UNKNOWN_KEY = '[tool.pytest-gremlins]\nmax_pardon_pct = 5\n'


def _run(pytester: pytest.Pytester, target: str, test_source: str, *args: str) -> str:
    pytester.makepyprojecttoml(_UNKNOWN_KEY)
    pytester.makepyfile(target=target, test_target=test_source)
    result = pytester.runpytest_subprocess('--gremlins', '--gremlin-targets=target.py', *args, *_NO_CATEGORIES)
    return result.stdout.str() + result.stderr.str()


@pytest.mark.medium
def it_does_not_claim_files_were_skipped_for_an_unknown_explain_id_with_an_unknown_config_key(
    pytester: pytest.Pytester,
) -> None:
    output = _run(pytester, _TARGET, _TEST, '--gremlin-explain=g99999')

    assert 'Files were skipped' not in output, output


@pytest.mark.medium
def it_points_at_paths_config_when_explain_finds_no_gremlins_with_an_unknown_config_key(
    pytester: pytest.Pytester,
) -> None:
    output = _run(pytester, _NO_GREMLIN_TARGET, _PLAIN_TEST, '--gremlin-explain=g1')

    assert 'Check your `paths`' in output, output
