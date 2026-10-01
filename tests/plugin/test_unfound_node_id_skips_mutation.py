"""A node id pytest cannot find must not yield a mutation score.

``pytest --gremlins tests/test_sample.py::renamed`` exits USAGE_ERROR with
"ERROR: not found" and "no tests ran", yet the mutation phase still runs and
prints ``Zapped: N gremlins (100%)``: the same unfounded-verdict class as #534 and #540.
"""

from __future__ import annotations

import pytest

SAMPLE_SOURCE = "def classify(value: int) -> str:\n    if value == 0:\n        return 'zero'\n    return 'nonzero'\n"
PASSING_TEST = 'from sample import classify\n\n\ndef test_zero():\n    assert classify(0) == "zero"\n'
PYPROJECT = '[tool.pytest-gremlins]\npaths = ["sample.py"]\n\n[tool.pytest.ini_options]\npythonpath = ["."]\n'
TESTS_CONFTEST = (
    'import pytest\n'
    '\n'
    'def pytest_configure(config):\n'
    "    config.addinivalue_line('markers', 'small: fast unit tests')\n"
    '\n'
    '\n'
    '@pytest.hookimpl(tryfirst=True)\n'
    'def pytest_collection_modifyitems(items):\n'
    '    for item in items:\n'
    '        item.add_marker(pytest.mark.small)\n'
)


@pytest.mark.medium
class DescribeUnfoundNodeIdSkipsMutationTesting:
    def it_prints_no_mutation_score_when_the_requested_test_does_not_exist(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile(sample=SAMPLE_SOURCE)
        pytester.makepyprojecttoml(PYPROJECT)
        pytester.mkdir('tests')
        pytester.path.joinpath('tests', 'conftest.py').write_text(TESTS_CONFTEST)
        pytester.path.joinpath('tests', 'test_sample.py').write_text(PASSING_TEST)

        result = pytester.runpytest_subprocess('--gremlins', '-p', 'no:cacheprovider', 'tests/test_sample.py::renamed')

        assert result.ret == pytest.ExitCode.USAGE_ERROR
        result.stdout.no_fnmatch_line('*Zapped*')
        result.stderr.fnmatch_lines(
            ['pytest-gremlins: skipping mutation testing because pytest reported a usage error (exit 4)']
        )
