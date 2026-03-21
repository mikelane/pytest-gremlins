"""End-to-end tests for the ``exclude`` config option.

These tests use the ``pytester`` fixture to create a real project with
``pyproject.toml`` containing ``exclude`` patterns and verify that matching
files produce no gremlins while non-matching files are still mutated.
"""

from __future__ import annotations

import pytest


@pytest.mark.medium
class DescribeExcludeConfig:
    """Integration tests proving ``exclude`` filters files from mutation."""

    def it_excludes_files_matching_glob_pattern(self, pytester_with_markers: pytest.Pytester) -> None:
        """Files matching an exclude glob produce zero gremlins."""
        pytester_with_markers.makepyprojecttoml(
            """
            [tool.pytest-gremlins]
            exclude = ["generated_schema.py"]
            """
        )

        # Source file that SHOULD be excluded
        pytester_with_markers.makepyfile(
            generated_schema='def add(a, b):\n    return a + b\n',
        )

        # Source file that should NOT be excluded
        pytester_with_markers.makepyfile(
            core_module='def sub(a, b):\n    return a - b\n',
        )

        # Tests covering both files
        pytester_with_markers.makepyfile(
            test_math=(
                'from generated_schema import add\n'
                'from core_module import sub\n'
                '\n'
                'def test_add():\n'
                '    assert add(1, 2) == 3\n'
                '\n'
                'def test_sub():\n'
                '    assert sub(3, 1) == 2\n'
            ),
        )

        result = pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=generated_schema.py,core_module.py',
        )

        output = result.stdout.str()

        # The excluded file must not appear in gremlin output
        assert 'generated_schema' not in output

        # The non-excluded file must appear (it has a mutable operator)
        assert 'core_module' in output

    def it_cli_exclude_overrides_toml_exclude(self, pytester_with_markers: pytest.Pytester) -> None:
        """CLI --gremlin-exclude overrides pyproject.toml exclude patterns."""
        pytester_with_markers.makepyprojecttoml(
            """
            [tool.pytest-gremlins]
            exclude = ["core_module.py"]
            """
        )

        # Source file excluded by TOML but NOT by CLI
        pytester_with_markers.makepyfile(
            core_module='def sub(a, b):\n    return a - b\n',
        )

        # Source file excluded by CLI but NOT by TOML
        pytester_with_markers.makepyfile(
            generated_schema='def add(a, b):\n    return a + b\n',
        )

        # Tests covering both files
        pytester_with_markers.makepyfile(
            test_math=(
                'from generated_schema import add\n'
                'from core_module import sub\n'
                '\n'
                'def test_add():\n'
                '    assert add(1, 2) == 3\n'
                '\n'
                'def test_sub():\n'
                '    assert sub(3, 1) == 2\n'
            ),
        )

        result = pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=generated_schema.py,core_module.py',
            '--gremlin-exclude=generated_schema.py',
        )

        output = result.stdout.str()

        # CLI exclude wins: generated_schema is excluded (not in output)
        assert 'generated_schema' not in output

        # TOML exclude is overridden: core_module is NOT excluded (appears in output)
        assert 'core_module' in output

    def it_does_not_exclude_when_no_patterns_configured(self, pytester_with_markers: pytest.Pytester) -> None:
        """Without exclude config, all source files are mutated."""
        pytester_with_markers.makepyprojecttoml(
            """
            [tool.pytest-gremlins]
            """
        )

        pytester_with_markers.makepyfile(
            generated_schema='def add(a, b):\n    return a + b\n',
        )

        pytester_with_markers.makepyfile(
            core_module='def sub(a, b):\n    return a - b\n',
        )

        pytester_with_markers.makepyfile(
            test_math=(
                'from generated_schema import add\n'
                'from core_module import sub\n'
                '\n'
                'def test_add():\n'
                '    assert add(1, 2) == 3\n'
                '\n'
                'def test_sub():\n'
                '    assert sub(3, 1) == 2\n'
            ),
        )

        result = pytester_with_markers.runpytest(
            '--gremlins',
            '--gremlin-targets=generated_schema.py,core_module.py',
        )

        output = result.stdout.str()

        # Both files appear when no exclude is configured
        assert 'generated_schema' in output
        assert 'core_module' in output
