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

from dataclasses import dataclass
import posixpath
import re
from typing import Protocol

GATED_SECTIONS = ('Upgrade notes', 'Feature', 'Fix')
DOCS_URL = re.compile(r'https://pytest-gremlins\.readthedocs\.io/en/latest(?=[/#?]|$)')
URL_SCHEME = re.compile(r'[a-zA-Z][a-zA-Z0-9+.-]*:')
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


class Site(Protocol):
    """The built docs site: which pages exist and which anchors each page has."""

    def anchors_of(self, page: str) -> frozenset[str] | None:
        """Return the anchors on ``page`` (``guide/configuration``; ``''`` is the home page), or ``None`` if absent."""


@dataclass(frozen=True)
class Reference:
    """A docs link as written (``target``), split into the site page it names and its anchor."""

    target: str
    page: str | None
    anchor: str


def _is_docs_reference(target: str) -> bool:
    if DOCS_URL.match(target):
        return True
    return not URL_SCHEME.match(target) and not target.startswith('#')


def _page_of(path: str) -> str | None:
    """Normalize a docs path to a site page name, or ``None`` when it climbs out of the docs root."""
    normalized = posixpath.normpath(path.lstrip('/'))
    if normalized == '..' or normalized.startswith('../'):
        return None
    page = '' if normalized == '.' else normalized.removesuffix('.md')
    if posixpath.basename(page) == 'index':
        page = posixpath.dirname(page)
    return page


def _parse_reference(target: str) -> Reference:
    path = DOCS_URL.sub('', target, count=1)
    path, _, anchor = path.partition('#')
    return Reference(target=target, page=_page_of(path.partition('?')[0]), anchor=anchor)


def _label(section: str, number: int, text: str) -> str:
    shortened = text if len(text) <= BULLET_LABEL_LENGTH else f'{text[:BULLET_LABEL_LENGTH]}...'
    return f'bullet under "### {section}" at line {number} ({shortened})'


def _reference_problem(reference: Reference, site: Site) -> str | None:
    anchors = None if reference.page is None else site.anchors_of(reference.page)
    if anchors is None:
        return f'docs reference {reference.target} points to a page that is not in the built site'
    if reference.anchor and reference.anchor not in anchors:
        return f'docs reference {reference.target} points to an anchor that is not on that page'
    return None


def _bullet_problems(section: str, number: int, text: str, site: Site) -> list[str]:
    label = _label(section, number, text)
    exemptions = EXEMPTION.findall(text)
    if any(not reason.strip() for reason in exemptions):
        return [f'{label} has an empty "(no docs: )" exemption; give a reason']
    references = [_parse_reference(target) for target in LINK_TARGET.findall(text) if _is_docs_reference(target)]
    if not references and not exemptions:
        return [f'{label} has no docs reference and no "(no docs: <reason>)" exemption']
    problems = (_reference_problem(reference, site) for reference in references)
    return [f'{label}: {problem}' for problem in problems if problem]


def find_problems(changelog: str, version: str, site: Site) -> list[str]:
    """Return one readable line per problem in the entry for ``version``; empty when the entry passes."""
    entry = _entry_lines(changelog, version)
    if entry is None:
        return [f'CHANGELOG.md has no "## v{version.removeprefix("v")}" entry']
    return [
        problem
        for section, number, text in _gated_bullets(entry)
        for problem in _bullet_problems(section, number, text, site)
    ]
