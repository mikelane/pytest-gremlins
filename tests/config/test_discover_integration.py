"""Integration test for the full source discovery chain via [project].name."""

import pytest


@pytest.mark.medium
class DescribeDiscoveryChainIntegration:
    """Pytester-based test for the full discovery chain."""

    def it_discovers_gremlins_via_project_name_when_no_setuptools(self, pytester_with_markers: pytest.Pytester):
        """Full chain: [project].name heuristic discovers package, gremlins are found."""
        pytester_with_markers.makefile(
            '.toml',
            pyproject="""
[project]
name = "my-fancy-pkg"
""",
        )

        pkg_dir = pytester_with_markers.path / 'my_fancy_pkg'
        pkg_dir.mkdir()
        (pkg_dir / '__init__.py').write_text('')
        (pkg_dir / 'math_utils.py').write_text('def add(a, b):\n    return a + b\n')

        pytester_with_markers.makepyfile(
            test_math="""
from my_fancy_pkg.math_utils import add

def test_add():
    assert add(1, 2) == 3
""",
        )

        result = pytester_with_markers.runpytest('--gremlins', '-v')

        output = result.stdout.str()
        assert 'Zapped:' in output or 'Survived:' in output
