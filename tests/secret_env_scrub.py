"""Scrub secret-shaped environment variables, kept apart from the conftest so tests can import it by name."""

from __future__ import annotations

from collections.abc import MutableMapping
import re

_SECRET_ENV_NAME = re.compile(
    r'^(PYPI|TWINE)_|_PWD$|(^|_)(TOKEN|PAT|SECRETS?|PASSWORD|PASSWD|PASS|PASSPHRASE|CREDENTIALS?|KEY|APIKEY|KEY_ID)$'
)


def is_secret_env_name(name: str) -> bool:
    """Return whether ``name`` looks like the name of a secret variable."""
    return _SECRET_ENV_NAME.search(name.upper()) is not None


def scrub_secret_env(environ: MutableMapping[str, str]) -> dict[str, str]:
    """Remove secret-shaped variables from ``environ`` and return what was removed.

    Pytest's ``-l`` and assertion rewriting print locals such as ``dict(os.environ)``
    on failure, which would leak CI secrets into logs. Scrubbing before any test runs keeps
    pytester and subprocess children, xdist workers included, from inheriting them too.
    """
    removed = {name: value for name, value in environ.items() if is_secret_env_name(name)}
    for name in removed:
        del environ[name]
    return removed
