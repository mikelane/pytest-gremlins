#!/usr/bin/env python3
"""Release docs gate: refuse a release whose changelog entry has undocumented user-facing changes.

Takes the version being released. In that version's ``## vX.Y.Z`` entry of ``CHANGELOG.md``, every bullet under
``### Upgrade notes``, ``### Feature`` and ``### Fix`` must carry either a docs reference or an explicit exemption.
``### Internal`` bullets are exempt.

* A docs reference is a Markdown link to a readthedocs ``latest`` URL
  (``https://pytest-gremlins.readthedocs.io/en/latest/<page>/#<anchor>``) or to a docs path relative to ``docs/``
  (``guide/configuration.md#<anchor>``). Every reference must resolve to a page, and to an anchor if it names
  one, in the built site (``mkdocs build --strict --site-dir <dir>``).
* An exemption is ``(no docs: <reason>)`` with a non-empty reason. The reason is public and is reviewed in the
  changelog PR.

Nothing skips this check: it has no flag, environment variable or input that turns it off.

Exit codes: 0 when the entry passes, 1 when the check fails (each problem is printed on stdout with a
``PROBLEM:`` prefix, naming the bullet or link), 2 when the check could not run (bad input, missing changelog
or missing site; the reason is printed on stderr). Exit 2 is never a pass.
"""

from __future__ import annotations

import re

GATED_SECTIONS = ('Upgrade notes', 'Feature', 'Fix')
DOCS_BASE_URL = 'https://pytest-gremlins.readthedocs.io/en/latest/'
BULLET_MARKERS = ('- ', '* ')
BULLET_LABEL_LENGTH = 70
EXEMPTION = re.compile(r'\(no docs:([^)]*)\)')
LINK_TARGET = re.compile(r'\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')


def _entry_lines(changelog: str, version: str) -> list[tuple[int, str]] | None:
    """Return the numbered lines of the ``## vX.Y.Z`` entry, or ``None`` when it is missing."""
    heading = re.compile(rf'## v?{re.escape(version.removeprefix("v"))}(\s|$)')
    entry: list[tuple[int, str]] = []
    in_entry = False
    for number, line in enumerate(changelog.splitlines(), start=1):
        if in_entry and line.startswith('## '):
            break
        if in_entry:
            entry.append((number, line))
        elif heading.match(line):
            in_entry = True
    return entry if in_entry else None


def _gated_bullets(entry: list[tuple[int, str]]) -> list[tuple[str, int, str]]:
    """Return ``(section, first line number, text)`` for each bullet in a gated section."""
    bullets: list[tuple[str, int, str]] = []
    section = ''
    current: list[str] = []
    start = 0

    def close() -> None:
        if current:
            bullets.append((section, start, ' '.join(current)))
            current.clear()

    for number, line in entry:
        if line.startswith('### '):
            close()
            section = line[4:].strip()
        elif section in GATED_SECTIONS and line.startswith(BULLET_MARKERS):
            close()
            start = number
            current.append(line[2:].strip())
        elif current and line.strip():
            current.append(line.strip())
        else:
            close()
    close()
    return bullets


def _is_docs_reference(target: str) -> bool:
    if target.startswith(DOCS_BASE_URL):
        return True
    return not re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', target) and not target.startswith('#')


def _label(section: str, number: int, text: str) -> str:
    shortened = text if len(text) <= BULLET_LABEL_LENGTH else f'{text[:BULLET_LABEL_LENGTH]}...'
    return f'bullet under "### {section}" at line {number} ({shortened})'


def _bullet_problems(section: str, number: int, text: str) -> list[str]:
    label = _label(section, number, text)
    exemptions = EXEMPTION.findall(text)
    if any(not reason.strip() for reason in exemptions):
        return [f'{label} has an empty "(no docs: )" exemption; give a reason']
    references = [target for target in LINK_TARGET.findall(text) if _is_docs_reference(target)]
    if not references and not exemptions:
        return [f'{label} has no docs reference and no "(no docs: <reason>)" exemption']
    return []


def find_problems(changelog: str, version: str) -> list[str]:
    """Return one readable line per problem in the entry for ``version``; empty when the entry passes."""
    entry = _entry_lines(changelog, version)
    if entry is None:
        return [f'CHANGELOG.md has no "## v{version.removeprefix("v")}" entry']
    return [
        problem
        for section, number, text in _gated_bullets(entry)
        for problem in _bullet_problems(section, number, text)
    ]
