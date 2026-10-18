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

The accepted format is strict, because the changelog is authored here and this check is a release gate. Under a
gated heading the only accepted lines are blank lines and list items with their indented continuation lines;
prose, blockquotes, fences, HTML comments, other headings, thematic breaks and setext underlines are problems, as
is any ``###`` heading that is not one of the known sections. A fence or HTML comment is allowed in the exempt
sections (``Internal``, ``Documentation``) and before the first heading, but it must be closed and must not hide a
``###`` heading. The check fails closed: whatever it does not understand is reported, never skipped.

Nothing skips this check: it has no flag, environment variable or input that turns it off.

``--newest`` checks the topmost ``## [v]X.Y.Z`` entry instead of a named version; it selects, never skips. When
the topmost ``##`` heading is not such an entry (``## Unreleased``), it exits 2 instead of checking an older one.

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
ENTRY_LEVEL = 2
SECTION_LEVEL = 3
DOCS_URL = re.compile(r'https://pytest-gremlins\.readthedocs\.io/en/latest(?=[/#?]|$)')
URL_SCHEME = re.compile(r'[a-zA-Z][a-zA-Z0-9+.-]*:')
BULLET = re.compile(r'\s*(?:[-*+]|\d{1,9}[.)])(?:\s+(.*)|$)')
BULLET_LABEL_LENGTH = 70
PROBLEM_PREFIX = 'PROBLEM: '
DEFAULT_CHANGELOG = Path(__file__).resolve().parents[1] / 'CHANGELOG.md'
FENCE = re.compile(r'\s*(`{3,}|~{3,})(.*)')
COMMENT_OPEN = '<!--'
COMMENT_CLOSE = '-->'
CODE_SPAN = re.compile(r'(`+).+?(?<!`)\1(?!`)', re.DOTALL)
NEWEST_HEADING = re.compile(r'## v?(\d\S*)')
EXEMPTION = re.compile(r'\(no docs:([^)]*)\)')
LINK_TARGET = re.compile(r'(?<![!\\])\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
SECTION_HEADING = re.compile(r' {0,3}(#{1,6})(?:[ \t]+(.*))?$')
HEADING_CLOSER = re.compile(r'(?:^|[ \t]+)#+[ \t]*$')
UNSUPPORTED_SHAPES = (
    (re.compile(r'\s*>'), 'a blockquote'),
    (re.compile(r'\s*#{1,6}(?:[ \t]|$)'), 'a heading other than a "###" section heading'),
    (re.compile(r'\s*(?:=+|-{2,}|(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$'), 'a thematic break or setext underline'),
    (re.compile(r'\s*[\u2022\u2023\u25e6\u25aa\u25cf]'), 'a pseudo-bullet; write "-"'),
)


@dataclass(frozen=True)
class _Line:
    """A changelog line as a reader sees it: ``text`` has HTML comments removed; fenced code is not a line."""

    number: int
    text: str
    opens_fence: bool = False
    opens_comment: bool = False


@dataclass(frozen=True)
class _Region:
    """A fence or HTML comment, identified by the line it opens on."""

    number: int
    kind: str


def _structural_title(text: str, level: int) -> str | None:
    """Return the title when ``text`` is an ATX heading of ``level`` indented by at most 3 spaces."""
    match = SECTION_HEADING.match(text)
    if match is None or len(match.group(1)) != level:
        return None
    return HEADING_CLOSER.sub('', match.group(2) or '').strip()


def _fence_marker(text: str) -> str | None:
    match = FENCE.match(text)
    if match is None:
        return None
    marker, info = match.groups()
    return None if marker[0] == '`' and '`' in info else marker


def _closes_fence(text: str, marker: str) -> bool:
    match = FENCE.match(text)
    if match is None:
        return False
    closer, trailing = match.groups()
    return closer[0] == marker[0] and len(closer) >= len(marker) and not trailing.strip()


def _strip_comments(text: str, in_comment: bool, allow_open: bool) -> tuple[str, bool, bool]:
    """Remove HTML comments from ``text``; return its visible text, if one opened here, and if one is still open."""
    visible: list[str] = []
    opened = False
    rest = text
    while True:
        if in_comment:
            end = rest.find(COMMENT_CLOSE)
            if end < 0:
                return ''.join(visible), opened, True
            rest = rest[end + len(COMMENT_CLOSE) :]
            in_comment = False
            continue
        start = rest.find(COMMENT_OPEN) if allow_open else -1
        if start < 0:
            visible.append(rest)
            return ''.join(visible), opened, False
        visible.append(rest[:start])
        rest = rest[start + len(COMMENT_OPEN) :]
        opened = in_comment = True


class _Scanner:
    """Walks the changelog once, hiding fenced code and HTML comments the way a Markdown renderer does."""

    def __init__(self, neutralized: frozenset[int]) -> None:
        self.lines: list[_Line] = []
        self.hidden_headings: list[tuple[_Region, int]] = []
        self.open_region: _Region | None = None
        self._neutralized = neutralized
        self._fence = ''
        self._in_comment = False

    def feed(self, number: int, text: str) -> None:
        if self.open_region is not None and _structural_title(text, SECTION_LEVEL) is not None:
            self.hidden_headings.append((self.open_region, number))
        if self._fence:
            self._feed_fenced(text)
            return
        marker = None if self._in_comment or number in self._neutralized else _fence_marker(text)
        if marker:
            self._fence = marker
            self.open_region = _Region(number, 'code fence')
            self.lines.append(_Line(number, text, opens_fence=True))
        else:
            self._feed_text(number, text)

    def _feed_fenced(self, text: str) -> None:
        if _closes_fence(text, self._fence):
            self._fence = ''
            self.open_region = None

    def _feed_text(self, number: int, text: str) -> None:
        visible, opened, still_open = _strip_comments(
            text, self._in_comment, allow_open=number not in self._neutralized
        )
        self.lines.append(_Line(number, visible, opens_comment=opened or COMMENT_OPEN in visible))
        if not still_open:
            self.open_region = None
        elif opened:
            self.open_region = _Region(number, 'HTML comment')
        self._in_comment = still_open


@dataclass(frozen=True)
class _Scan:
    lines: list[_Line]
    unclosed: list[_Region]
    hidden_headings: list[tuple[_Region, int]]


def _scan(changelog: str) -> _Scan:
    """Scan ``changelog``; a fence or comment that is never closed is reported, then read as plain text.

    Reading it as plain text keeps it from hiding the rest of the file, so later sections are still checked.
    """
    raw = changelog.splitlines()
    neutralized: set[int] = set()
    unclosed: list[_Region] = []
    while True:
        scanner = _Scanner(frozenset(neutralized))
        for number, text in enumerate(raw, start=1):
            scanner.feed(number, text)
        if scanner.open_region is None:
            return _Scan(scanner.lines, unclosed, scanner.hidden_headings)
        unclosed.append(scanner.open_region)
        neutralized.add(scanner.open_region.number)


@dataclass(frozen=True)
class _Entry:
    lines: list[_Line]
    problems: list[str]


def _find_entry(changelog: str, version: str) -> _Entry | None:
    """Return the lines of the ``## vX.Y.Z`` entry and the problems with its fences and comments, or ``None``."""
    scan = _scan(changelog)
    heading = re.compile(rf'## v?{re.escape(version.removeprefix("v"))}(\s|$)')
    start = next((i for i, line in enumerate(scan.lines) if heading.match(line.text)), None)
    if start is None:
        return None
    end = next(
        (
            i
            for i in range(start + 1, len(scan.lines))
            if _structural_title(scan.lines[i].text, ENTRY_LEVEL) is not None
        ),
        len(scan.lines),
    )
    first = scan.lines[start].number
    last = scan.lines[end].number if end < len(scan.lines) else sys.maxsize
    problems = [
        f'{region.kind} opened at line {region.number} is never closed'
        for region in scan.unclosed
        if first <= region.number < last
    ] + [
        f'{region.kind} opened at line {region.number} hides the "###" heading at line {number}'
        for region, number in scan.hidden_headings
        if first <= number < last
    ]
    return _Entry(scan.lines[start + 1 : end], problems)


def _unsupported_shape(text: str) -> str | None:
    return next((description for shape, description in UNSUPPORTED_SHAPES if shape.match(text)), None)


@dataclass
class _Item:
    section: str
    number: int
    parts: list[str]


class _EntryReader:
    """Reads an entry line by line, collecting the gated list items and everything the gate cannot accept."""

    def __init__(self) -> None:
        self.section = NO_SECTION
        self.items: list[_Item] = []
        self.problems: list[str] = []
        self._open: _Item | None = None

    def read(self, lines: list[_Line]) -> None:
        for line in lines:
            self._read_line(line)

    def _read_line(self, line: _Line) -> None:
        title = _structural_title(line.text, SECTION_LEVEL)
        if title is not None:
            self._start_section(line.number, title)
        elif self.section in GATED_SECTIONS:
            self._read_gated_line(line)
        elif self.section == NO_SECTION:
            self._read_preamble_line(line)

    def _start_section(self, number: int, title: str) -> None:
        self._open = None
        self.section = title
        if title not in KNOWN_SECTIONS:
            self.problems.append(
                f'unknown section heading "### {title}" at line {number}; use one of: {", ".join(KNOWN_SECTIONS)}'
            )

    def _read_preamble_line(self, line: _Line) -> None:
        bullet = BULLET.match(line.text)
        if bullet:
            text = _shorten((bullet.group(1) or '').strip())
            self.problems.append(f'bullet at line {line.number} ({text}) is under no "###" section heading')

    def _read_gated_line(self, line: _Line) -> None:
        if line.opens_comment:
            self.problems.append(f'HTML comment at line {line.number} under "### {self.section}"; remove it')
        reason = 'a code fence' if line.opens_fence else _unsupported_shape(line.text)
        if reason:
            self._open = None
            self._reject(line.number, reason)
        elif not line.text.strip():
            self._open = None
        else:
            self._read_list_line(line)

    def _read_list_line(self, line: _Line) -> None:
        bullet = BULLET.match(line.text)
        if bullet:
            self._open = _Item(self.section, line.number, [(bullet.group(1) or '').strip()])
            self.items.append(self._open)
        elif self._open is not None and line.text[0] in ' \t':
            self._open.parts.append(line.text.strip())
        else:
            self._open = None
            self._reject(line.number, 'a paragraph that is not part of a list item')

    def _reject(self, number: int, reason: str) -> None:
        self.problems.append(
            f'{reason} at line {number} under "### {self.section}"; this section may hold only list items'
        )


def newest_version(changelog: str) -> str:
    """Return the version of the topmost ``## [v]X.Y.Z`` entry.

    Args:
        changelog: The text of ``CHANGELOG.md``.

    Returns:
        The version without its leading ``v``.

    Raises:
        CannotCheckError: When the changelog has no ``##`` heading, or the topmost one is not a version entry. An
            older entry is never selected instead.
    """
    for line in _scan(changelog).lines:
        if _structural_title(line.text, ENTRY_LEVEL) is None:
            continue
        heading = NEWEST_HEADING.match(line.text)
        if heading is None:
            raise CannotCheckError(
                f'the topmost "##" heading, "{line.text.strip()}" at line {line.number}, is not a "## vX.Y.Z" entry'
            )
        return heading.group(1)
    raise CannotCheckError('CHANGELOG.md has no "## vX.Y.Z" entry')


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


def _bullet_problems(item: _Item, site: Site) -> list[str]:
    section, number, text = item.section, item.number, ' '.join(item.parts)
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
    """Return one readable line per problem in the entry for ``version``; empty when the entry passes.

    Args:
        changelog: The text of ``CHANGELOG.md``.
        version: The release version, with or without the leading ``v``.
        site: The built docs site that references are resolved against.

    Returns:
        One line per problem: content the gate does not accept, an unknown ``###`` heading, a bullet under no
        heading, a gated bullet with no reference or exemption, or a reference that does not resolve.
    """
    entry = _find_entry(changelog, version)
    if entry is None:
        return [f'CHANGELOG.md has no "## v{version.removeprefix("v")}" entry']
    reader = _EntryReader()
    reader.read(entry.lines)
    bullet_problems = [problem for item in reader.items for problem in _bullet_problems(item, site)]
    return entry.problems + reader.problems + bullet_problems


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


def _check(args: argparse.Namespace) -> tuple[str, list[str]]:
    changelog = _read_changelog(args.changelog)
    version = newest_version(changelog) if args.newest else args.version
    if not version.removeprefix('v'):
        raise CannotCheckError('the version is empty')
    return version, find_problems(changelog, version, BuiltSite(args.site_dir))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        'version', nargs='?', help='version being released, with or without the leading v (e.g. 1.12.1)'
    )
    parser.add_argument('--newest', action='store_true', help='check the topmost entry of the changelog instead')
    parser.add_argument('--site-dir', type=Path, required=True, help='output directory of `mkdocs build --strict`')
    parser.add_argument('--changelog', type=Path, default=DEFAULT_CHANGELOG, help='path to CHANGELOG.md')
    args = parser.parse_args(argv)
    if args.newest == (args.version is not None):
        parser.error('give exactly one of the version and --newest')
    return args


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: The command-line arguments; ``sys.argv[1:]`` when ``None``.

    Returns:
        The process exit code: 0 when the entry passes, 1 when it has problems, 2 when the check could not run.
    """
    args = _parse_args(argv)
    try:
        version, problems = _check(args)
    except CannotCheckError as error:
        print(f'could not check the release docs: {error}', file=sys.stderr)
        return 2
    except Exception as error:  # exit 2 must never be confused with a failed check (exit 1) or a pass
        print(f'could not check the release docs: unexpected {type(error).__name__}: {error}', file=sys.stderr)
        return 2
    if problems:
        print(f'{args.changelog} is not ready to release {version}:')
        for problem in problems:
            print(f'{PROBLEM_PREFIX}{problem}')
        return 1
    print(f'Every user-facing change in the {version} entry links to docs or has an exemption.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
