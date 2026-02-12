"""pytest-gremlins: Fast-first mutation testing for pytest.

Let the gremlins loose. See which ones survive.

pytest-gremlins is a mutation testing plugin that helps you evaluate the quality
of your test suite by injecting small changes (gremlins) into your code and
checking if your tests catch them.

Example:
    Run mutation testing on your project::

        $ pytest --gremlins

    Run with specific operators only::

        $ pytest --gremlins --gremlin-operators=comparison,boolean

    Generate an HTML report::

        $ pytest --gremlins --gremlin-report=html

For more information, see https://pytest-gremlins.readthedocs.io
"""

from __future__ import annotations


__version__ = '1.1.0'
__all__ = ['__version__']
