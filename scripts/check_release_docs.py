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

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import re
import sys
from typing import Protocol

GATED_SECTIONS = ('Upgrade notes', 'Feature', 'Fix')
EXEMPT_SECTIONS = ('Internal', 'Documentation')
KNOWN_SECTIONS = (*GATED_SECTIONS, *EXEMPT_SECTIONS)
NO_SECTION = ''
HOME_PAGE = ''
DOCS_URL = re.compile(r'https://pytest-gremlins\.readthedocs\.io/en/latest(?=[/#?]|$)')
URL_SCHEME = re.compile(r'[a-zA-Z][a-zA-Z0-9+.-]*:')
BULLET = re.compile(r'\s*(?:[-*+]|\d{1,9}[.)])(?:\s+(.*)|$)')
BULLET_LABEL_LENGTH = 70
PROBLEM_PREFIX = 'PROBLEM: '
DEFAULT_CHANGELOG = Path(__file__).resolve().parents[1] / 'CHANGELOG.md'
FENCE = re.compile(r' {0,3}(`{3,}|~{3,})(.*)')
HTML_COMMENT = re.compile(r'<!--.*?-->', re.DOTALL)
CODE_SPAN = re.compile(r'(`+).+?(?<!`)\1(?!`)', re.DOTALL)
EXEMPTION = re.compile(r'\(no docs:([^)]*)\)')
LINK_TARGET = re.compile(r'\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')


def _outside_fences(changelog: str) -> list[tuple[int, str]]:
    """Return the numbered lines of ``changelog`` that are not part of a fenced code block."""
    lines: list[tuple[int, str]] = []
    fence = ''
    for number, line in enumerate(changelog.splitlines(), start=1):
        opening = FENCE.match(line)
        if not fence and opening and not (opening.group(1)[0] == '`' and '`' in opening.group(2)):
            fence = opening.group(1)
        elif fence and opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence):
            fence = '' if not opening.group(2).strip() else fence
        elif not fence:
            lines.append((number, line))
    return lines


def _without_html_comments(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Blank out ``<!-- ... -->`` comments, keeping every line number."""
    if not lines:
        return lines
    text = HTML_COMMENT.sub(lambda match: re.sub(r'[^\n]', ' ', match.group()), '\n'.join(line for _, line in lines))
    return [(number, line) for (number, _), line in zip(lines, text.split('\n'), strict=True)]


def _entry_lines(changelog: str, version: str) -> list[tuple[int, str]] | None:
    """Return the numbered lines of the ``## vX.Y.Z`` entry, or ``None`` when it is missing."""
    heading = re.compile(rf'## v?{re.escape(version.removeprefix("v"))}(\s|$)')
    entry: list[tuple[int, str]] = []
    in_entry = False
    for number, line in _without_html_comments(_outside_fences(changelog)):
        if in_entry and line.startswith('## '):
            break
        if in_entry:
            entry.append((number, line))
        elif heading.match(line):
            in_entry = True
    return entry if in_entry else None


def _unknown_headings(entry: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Return ``(line number, heading)`` for each ``###`` heading that is not a known section."""
    headings = ((number, line[4:].strip()) for number, line in entry if line.startswith('### '))
    return [(number, heading) for number, heading in headings if heading not in KNOWN_SECTIONS]


def _gated_bullets(entry: list[tuple[int, str]]) -> list[tuple[str, int, str]]:
    """Return ``(section, first line number, text)`` for each bullet that needs a docs reference or exemption."""
    bullets: list[tuple[str, int, str]] = []
    section = NO_SECTION
    current: list[str] = []
    start = 0

    def close() -> None:
        if current:
            bullets.append((section, start, ' '.join(current)))
            current.clear()

    for number, line in entry:
        bullet = BULLET.match(line)
        if line.startswith('### '):
            close()
            section = line[4:].strip()
        elif bullet and section in (NO_SECTION, *GATED_SECTIONS):
            close()
            start = number
            current.append((bullet.group(1) or '').strip())
        elif current and line.strip() and not bullet:
            current.append(line.strip())
        else:
            close()
    close()
    return bullets


class CannotCheckError(Exception):
    """Raised when the check cannot run (bad input, missing changelog, missing site). Never a pass."""


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


def _shorten(text: str) -> str:
    return text if len(text) <= BULLET_LABEL_LENGTH else f'{text[:BULLET_LABEL_LENGTH]}...'


def _label(section: str, number: int, text: str) -> str:
    return f'bullet under "### {section}" at line {number} ({_shorten(text)})'


def _reference_problem(reference: Reference, site: Site) -> str | None:
    anchors = None if reference.page is None else site.anchors_of(reference.page)
    if anchors is None:
        return f'docs reference {reference.target} points to a page that is not in the built site'
    if reference.anchor and reference.anchor not in anchors:
        return f'docs reference {reference.target} points to an anchor that is not on that page'
    return None


def _bullet_problems(section: str, number: int, text: str, site: Site) -> list[str]:
    if section == NO_SECTION:
        return [f'bullet at line {number} ({_shorten(text)}) is under no "###" section heading']
    label = _label(section, number, text)
    visible = CODE_SPAN.sub(' ', text)
    exemptions = EXEMPTION.findall(visible)
    if any(not reason.strip() for reason in exemptions):
        return [f'{label} has an empty "(no docs: )" exemption; give a reason']
    parsed = (_parse_reference(target) for target in LINK_TARGET.findall(visible) if _is_docs_reference(target))
    references = [reference for reference in parsed if reference.page != HOME_PAGE]
    if not references and not exemptions:
        return [f'{label} has no docs reference and no "(no docs: <reason>)" exemption']
    problems = (_reference_problem(reference, site) for reference in references)
    return [f'{label}: {problem}' for problem in problems if problem]


def find_problems(changelog: str, version: str, site: Site) -> list[str]:
    """Return one readable line per problem in the entry for ``version``; empty when the entry passes."""
    entry = _entry_lines(changelog, version)
    if entry is None:
        return [f'CHANGELOG.md has no "## v{version.removeprefix("v")}" entry']
    heading_problems = [
        f'unknown section heading "### {heading}" at line {number}; use one of: {", ".join(KNOWN_SECTIONS)}'
        for number, heading in _unknown_headings(entry)
    ]
    bullet_problems = [
        problem
        for section, number, text in _gated_bullets(entry)
        for problem in _bullet_problems(section, number, text, site)
    ]
    return heading_problems + bullet_problems


class _AnchorCollector(HTMLParser):
    """Collects the fragment targets on a page: every ``id`` and the ``name`` of ``<a>`` tags."""

    def __init__(self) -> None:
        super().__init__()
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fragment_attributes = ('id', 'name') if tag == 'a' else ('id',)
        self.anchors.update(value for name, value in attrs if name in fragment_attributes and value)


class BuiltSite:
    """A site built by ``mkdocs build``; each page ``a/b`` is the file ``a/b/index.html``."""

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise CannotCheckError(f'site directory {root} is not a directory; run `mkdocs build --strict` first')
        if not (root / 'index.html').is_file():
            raise CannotCheckError(f'{root} has no index.html, so it is not a built mkdocs site')
        self._root = root
        self._cache: dict[str, frozenset[str] | None] = {}

    def anchors_of(self, page: str) -> frozenset[str] | None:
        """Return the anchors on ``page``, or ``None`` when the site has no such page."""
        if page not in self._cache:
            self._cache[page] = self._read_anchors(self._root / page / 'index.html')
        return self._cache[page]

    @staticmethod
    def _read_anchors(path: Path) -> frozenset[str] | None:
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as error:
            raise CannotCheckError(f'cannot read {path}: {error}') from error
        collector = _AnchorCollector()
        collector.feed(text)
        return frozenset(collector.anchors)


def _read_changelog(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheckError(f'cannot read {path}: {error}') from error


def _check(version: str, changelog: Path, site_dir: Path) -> list[str]:
    if not version.removeprefix('v'):
        raise CannotCheckError('the version is empty')
    return find_problems(_read_changelog(changelog), version, BuiltSite(site_dir))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('version', help='version being released, with or without the leading v (e.g. 1.12.1)')
    parser.add_argument('--site-dir', type=Path, required=True, help='output directory of `mkdocs build --strict`')
    parser.add_argument('--changelog', type=Path, default=DEFAULT_CHANGELOG, help='path to CHANGELOG.md')
    args = parser.parse_args(argv)
    try:
        problems = _check(args.version, args.changelog, args.site_dir)
    except CannotCheckError as error:
        print(f'could not check the release docs: {error}', file=sys.stderr)
        return 2
    except Exception as error:  # exit 2 must never be confused with a failed check (exit 1) or a pass
        print(f'could not check the release docs: unexpected {type(error).__name__}: {error}', file=sys.stderr)
        return 2
    if problems:
        print(f'{args.changelog} is not ready to release {args.version}:')
        for problem in problems:
            print(f'{PROBLEM_PREFIX}{problem}')
        return 1
    print(f'Every user-facing change in the {args.version} entry links to docs or has an exemption.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
