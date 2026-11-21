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

Three line rules cover the whole selected entry, in the preamble, the exempt sections and the gated sections alike:

* Only the exact ``### <section>`` headings (up to 3 leading spaces, optional tab after the hashes, optional
  closing hashes) and the ``## [v]X.Y.Z`` version headings are accepted. Any other line that starts with ``#`` is an
  unsupported heading, whether or not a renderer would make one of it: ``#Feature``, ``####Detail``, ``###Feature``,
  ``#Feature ###``, ``##v2.0.0`` and ``#<TAB>Feature`` all fail. The one exception is an indented continuation
  line directly under an open list item, such as ``  #989-#994)`` or ``  #964 for details``: the renderer reads it
  as paragraph text. It still fails when it is heading-shaped (``  ### Internal``), and a standalone ``    #720)``
  after a blank line renders as a heading and fails.
* A line that starts with an HTML tag (``<div>``, ``</div>``, ``<?php``, ``<![CDATA[``), after any indentation or
  list and block-quote prefix, is rejected: the renderer reads it as a raw HTML block and leaves a ``###`` line
  inside it as literal text. A fence closes only on a closer of exactly the opener's length, as the docs renderer
  reads it, and a longer closer is rejected because CommonMark would close there.
* Every thematic break or setext-underline shape is rejected, in every section and with no attempt to guess the
  previous line: a run of ``=``, a run of one or two ``-``, and ``***``, ``---``, ``___``, ``* * *`` and ``- - -``.
  This also rejects a delimiter under a pipe or inline-HTML line, so ``A | B`` + ``---`` and
  ``<em>Feature</em>`` + ``---`` cannot hide a rendered heading.
* A raw ``<h1>``-``<h6>`` tag is rejected wherever a reader can see it, in any case and with attributes, because the
  renderer turns it into a real heading inside a block quote or a list item too. A tag written as a code span
  (```<h1>```) stays literal text.
* Both rules apply again after the list-marker and block-quote prefixes are stripped, so ``> #Feature``,
  ``- #### Detail``, ``> <em>Feature</em>`` + ``> ---`` and ``- ---`` fail too. A code fence has to start at the
  outer level (up to the leading spaces the scanner already accepts); a fence opener inside a block quote or after
  a list marker is reported as unsupported instead of being read as code.

A second visible copy of the selected version heading is a problem wherever it sits, including the no-space
(``##v2.0.0``), indented and quoted or listed variants, because ``--notes-out`` publishes only the first copy while
readers see both.

A line longer than 1000 characters is a problem wherever it sits in the entry, inside a fence or comment too. It is
reported before any pattern reads it and is then read as a blank line, so no input line can make the check slow.

Nothing skips this check: it has no flag, environment variable or input that turns it off.

``--newest`` checks the topmost ``## [v]X.Y.Z`` entry instead of a named version; it selects, never skips. When
the topmost ``##`` heading is not such an entry (``## Unreleased``), it exits 2 instead of checking an older one.

``--notes-out PATH`` writes the exact text of the entry that was checked (its heading line up to the next version
heading, line breaks unchanged) to ``PATH`` when the check passes, and nothing otherwise. ``release.yml`` publishes that
file, so the release notes are the text that passed the gate and no second parser can choose a different span. A
carriage return that does not belong to a CRLF line ending, and a copy of the version heading inside an HTML comment or
code fence, are problems.

Exit codes: 0 when the entry passes, 1 when the check fails (each problem is printed on stdout with a
``PROBLEM:`` prefix, naming the bullet or link), 2 when the check could not run (bad input, missing changelog
or missing site; the reason is printed on stderr). Exit 2 is never a pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
import io
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
BULLET = re.compile(r'\s*(?:[-*+]|[0-9]{1,9}[.)])(?:\s+(.*)|$)')
BULLET_LABEL_LENGTH = 70
PROBLEM_PREFIX = 'PROBLEM: '
MAX_LINE_LENGTH = 1000
DEFAULT_CHANGELOG = Path(__file__).resolve().parents[1] / 'CHANGELOG.md'
FENCE = re.compile(r' {0,3}(`{3,}|~{3,})(.*)')
ANY_INDENT_FENCE = re.compile(r'\s*(`{3,}|~{3,})(.*)')
COMMENT_OPEN = '<!--'
COMMENT_CLOSE = '-->'
CODE_SPAN = re.compile(r'(?<!\\)(`+).+?(?<!`)\1(?!`)', re.DOTALL)
NEWEST_HEADING = re.compile(r'## v?([0-9]\S*)')
LINE_BREAK = re.compile(r'\r\n|\r|\n')
VERSION_HEADING_START = re.compile(r'## v?[0-9]')
LINE_WITH_BREAK = re.compile(r'[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+')
LONE_CARRIAGE_RETURN = re.compile(r'\r(?!\n)')
NON_MARKDOWN_BREAK = re.compile('[\u2028\u2029\x85\x0c\x0b\x1c\x1d\x1e]')
EXEMPTION = re.compile(r'\(no docs:([^)]*)\)')
LINK_TARGET = re.compile(r'(?<![!\\])\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)')
SECTION_HEADING = re.compile(r' {0,3}(#{1,6})(?:[ \t]+(.*))?$')
HEADING_CLOSER = re.compile(r'(?:^|[ \t]+)#+[ \t]*$')
CONTAINER_PREFIX = re.compile(r'(?: {0,3}>[ \t]?|[ \t]*(?:[-*+]|[0-9]{1,9}[.)])(?:[ \t]+|(?=[ \t]*$)))')
ATX_HEADING_SHAPE = re.compile(r'#{1,6}(?:[ \t]|$)')
BLOCK_HTML_START = re.compile(r'<(?:/?[A-Za-z][A-Za-z0-9-]*(?=[\s/>]|$)|[!?])')
LIST_ITEM = re.compile(r'[ \t]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]+\S')
CONTAINER_QUOTE = re.compile(r'[ \t]*(?:>[ \t]*)+')
HTML_HEADING = re.compile(r'<(/?)h[1-6]\b', re.IGNORECASE)
THEMATIC_OR_SETEXT = re.compile(r'[ \t]*(?:=(?:[ \t]*=)*|-{1,2}|[-*_](?:[ \t]*[-*_]){2,})[ \t]*$')
UNSUPPORTED_SHAPES = (
    (re.compile(r'\s*>'), 'a blockquote'),
    (re.compile(r'\s*[\u2022\u2023\u25e6\u25aa\u25cf]'), 'a pseudo-bullet; write "-"'),
)


@dataclass(frozen=True)
class _ShapeProblem:
    """A line shape the strict format rejects: what the line is, and how the author can fix it."""

    description: str
    fix: str


UNSUPPORTED_HEADING = _ShapeProblem(
    'a heading that is not a known "###" section heading or version heading',
    'use one of the five "###" section names, or keep an issue-number line directly under its bullet with no blank '
    'line, or escape it as "\\#720)"',
)
RAW_HTML_HEADING = _ShapeProblem('a raw HTML heading', 'use a known "###" section heading')
RAW_HTML_BLOCK = _ShapeProblem(
    'a raw HTML block tag', 'move the tag into the middle of a sentence or write it as a code span'
)
NESTED_FENCE_FOUR_COLUMNS = (
    'a renderer reads a fence indented 4 or more columns as an indented code block. Start the fence at the outer '
    'level, indented by at most 3 spaces'
)
NESTED_FENCE_UNDER_LIST_ITEM = (
    'it sits under the list item above it, so a renderer reads it as code inside that item; put the fence at column '
    '0 after a non-list line'
)
DELIMITER_LINE = _ShapeProblem('a thematic break or setext underline', 'remove the line or write it as a code span')


@dataclass(frozen=True)
class _Line:
    """A changelog line as a reader sees it: ``text`` has HTML comments removed; fenced code is not a line.

    ``heading`` is the raw line when it starts outside a comment, else empty. Headings are read from it, not from
    ``text``, because ``<!-- x --> ### Fix`` is one HTML block in Markdown, not a heading.
    """

    number: int
    text: str
    heading: str = ''
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


def _container_content(text: str) -> str:
    """Strip the block-quote and list markers of ``text`` so the content inside them can be read on its own."""
    content = text
    while (match := CONTAINER_PREFIX.match(content)) is not None:
        content = content[match.end() :]
    return content


def _line_shape_problem(text: str, *, list_continuation: bool = False) -> _ShapeProblem | None:
    """Describe a heading or delimiter shape the accepted changelog format rejects, or return ``None``.

    The format is strict on purpose: a visible line is allowed only if it is one of the known ``###`` section
    headings, a version heading, ordinary prose or a list line. Anything that starts with ``#`` in another shape is
    reported, whether or not a renderer would make a heading of it, and every thematic-break or setext-underline
    shape is reported without looking at the line above it. Both readings repeat inside list and block-quote
    markers, which is how ``> #Feature`` and ``- ---`` are caught.

    ``list_continuation`` says the caller read the previous visible line as an open list item. An indented line
    directly under it is a continuation of that item's paragraph, so it can start with a ``#`` that is not an ATX
    heading (``  #716)``, ``  #989-#994)``, ``  #964 for details``). It can never be a heading: an indented ``#``
    heading shape there (``  ### Internal``) is rejected even when it names a known section, because a renderer
    does not agree with the scanner on whether it is a section switch. A standalone ``    #720)`` after a blank
    line is not a continuation: a renderer makes an ``h1`` of it, so it stays an unsupported heading shape.
    """
    if not text.strip():
        return None
    content = _container_content(text)
    if content.lstrip(' \t').startswith('#'):
        under_item = list_continuation and content == text and text.startswith((' ', '\t'))
        if not (under_item and ATX_HEADING_SHAPE.match(text.lstrip(' \t')) is None):
            accepted = (
                content == text
                and not under_item
                and (
                    _structural_title(content, SECTION_LEVEL) is not None
                    or _structural_title(content, ENTRY_LEVEL) is not None
                )
            )
            return None if accepted else UNSUPPORTED_HEADING
    if _is_html_heading(text):
        return RAW_HTML_HEADING
    if _starts_html_tag(text) or _starts_html_tag(content):
        return RAW_HTML_BLOCK
    if THEMATIC_OR_SETEXT.match(text) or THEMATIC_OR_SETEXT.match(content):
        return DELIMITER_LINE
    return None


def _is_html_heading(text: str) -> bool:
    """Return whether ``text`` holds a visible raw ``<h1>``-``<h6>`` tag outside a code span.

    A renderer turns these tags into real headings even inside a block quote or a list item, so the strict format
    rejects them wherever the line is visible. A tag written as a code span (```<h1>```) stays literal text.
    """
    return bool(HTML_HEADING.search(CODE_SPAN.sub(' ', text)))


def _starts_html_tag(text: str) -> bool:
    """Return whether ``text`` starts with an HTML tag, declaration or processing instruction.

    A renderer reads a tag at the start of a line as a raw HTML block and leaves everything inside it as literal
    text, including a ``###`` line the scanner would take for a section heading. The strict format has no use for
    raw HTML blocks, so every such line is rejected, not only the block-level tag names. An autolink
    (``<https://example.com>``) and a tag in the middle of a line are not blocks.
    """
    return BLOCK_HTML_START.match(text.lstrip(' \t')) is not None


def _marker_of(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    marker, info = match.groups()
    return None if marker[0] == '`' and '`' in info else marker


def _fence_marker(text: str) -> str | None:
    """Return the marker when ``text`` opens a fence at the outer level: indented by at most 3 spaces."""
    return _marker_of(FENCE.match(text))


def _indented_fence_marker(text: str, *, in_list_item: bool) -> str | None:
    """Return the marker when ``text`` looks like a fence a renderer reads as indented code or list-item code.

    Four or more columns of indentation make an indented code block, and any indentation under an open list item
    belongs to that item. Neither is the outer-level fence the accepted format supports.
    """
    if not text.startswith((' ', '\t')):
        return None
    if FENCE.match(text) is not None and not in_list_item:
        return None
    return _marker_of(ANY_INDENT_FENCE.match(text))


def _container_fence_marker(text: str) -> str | None:
    """Return the fence marker when ``text`` opens a fence inside a list item or block quote, else ``None``."""
    return _fence_marker(_container_content(text)) if _container_content(text) != text else None


def _fence_closer_length(text: str, marker: str) -> int | None:
    """Return the length of ``text`` when it is a bare run of the opener's fence character, else ``None``."""
    match = ANY_INDENT_FENCE.match(text)
    if match is None:
        return None
    closer, trailing = match.groups()
    return len(closer) if closer[0] == marker[0] and not trailing.strip() else None


def _closes_fence(text: str, marker: str, *, exact: bool = False) -> bool:
    """Return whether ``text`` closes a fence opened with ``marker``.

    ``exact`` closes only on a closer of the opener's own length, which is how pymdownx.superfences (the docs
    renderer) reads it. CommonMark also closes on a longer one, so the two disagree on a longer closer; see
    ``_is_longer_fence_closer``.
    """
    length = _fence_closer_length(text, marker)
    return length is not None and (length == len(marker) if exact else length >= len(marker))


def _is_longer_fence_closer(text: str, marker: str) -> bool:
    length = _fence_closer_length(text, marker)
    return length is not None and length > len(marker)


def _comment_open_index(text: str) -> int:
    """Return the index of the first ``<!--`` that is not inside a code span, or ``-1``.

    A ``<!--`` written as a code span is literal text, so it opens no comment.
    """
    code_spans = [match.span() for match in CODE_SPAN.finditer(text)]
    index = text.find(COMMENT_OPEN)
    while index >= 0:
        if not any(start <= index < end for start, end in code_spans):
            return index
        index = text.find(COMMENT_OPEN, index + 1)
    return -1


def _has_comment_opener_in_code_span(text: str) -> bool:
    """Return whether ``text`` writes an unclosed ``<!--`` inside a code span, which a reader may take for a comment.

    A span that holds the whole comment (``<!-- x -->``) is literal text and is fine.
    """
    spans = (match.group() for match in CODE_SPAN.finditer(text))
    return any(COMMENT_CLOSE not in span[span.rfind(COMMENT_OPEN) :] for span in spans if COMMENT_OPEN in span)


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
        start = _comment_open_index(rest) if allow_open else -1
        if start < 0:
            visible.append(rest)
            return ''.join(visible), opened, False
        visible.append(rest[:start])
        rest = rest[start + len(COMMENT_OPEN) :]
        opened = in_comment = True


class _Scanner:
    """Walks the changelog once, hiding fenced code and HTML comments the way a Markdown renderer does.

    A line inside an outer fence or an HTML comment is invisible, so a fence opener written inside one is literal
    text and is neither reported nor read as code. A fence opener inside a list item or block quote is unsupported by
    the accepted format: it is recorded for a diagnostic, and its lines are read as plain text instead of opening a
    region that would hide what follows.
    """

    def __init__(self, neutralized: frozenset[int]) -> None:
        self.lines: list[_Line] = []
        self.diagnostics: list[tuple[int, str]] = []
        self.hidden_headings: list[tuple[_Region, int]] = []
        self.hidden_version_headings: list[tuple[_Region, int, str]] = []
        self.unsupported_fence_lines: list[int] = []
        self.open_region: _Region | None = None
        self._neutralized = neutralized
        self._fence = ''
        self._container_fence = ''
        self._in_comment = False
        self._comment_midline = False
        self._in_list_item = False

    def feed(self, number: int, text: str) -> None:
        if len(text) > MAX_LINE_LENGTH:
            self.diagnostics.append((number, f'line {number} is longer than {MAX_LINE_LENGTH} characters'))
            text = ''
        if self.open_region is not None and _structural_title(text, SECTION_LEVEL) is not None:
            self.hidden_headings.append((self.open_region, number))
        if self.open_region is not None and VERSION_HEADING_START.match(text):
            self.hidden_version_headings.append((self.open_region, number, text))
        if self._fence or self._in_comment or self._container_fence:
            self._feed_inside_region(number, text)
            return
        indented = (
            None if number in self._neutralized else _indented_fence_marker(text, in_list_item=self._in_list_item)
        )
        if indented:
            self._container_fence = indented
            self.unsupported_fence_lines.append(number)
            reason = NESTED_FENCE_UNDER_LIST_ITEM if self._in_list_item else NESTED_FENCE_FOUR_COLUMNS
            self.diagnostics.append(
                (number, f'an indented code fence at line {number} ({_shorten(text.strip())}) is unsupported: {reason}')
            )
            self._feed_text(number, text, neutralized=True)
            return
        marker = None if number in self._neutralized else _fence_marker(text)
        if marker:
            self._in_list_item = False
            self._fence = marker
            self.open_region = _Region(number, 'code fence')
            self.lines.append(_Line(number, text, opens_fence=True))
            return
        container_marker = None if number in self._neutralized else _container_fence_marker(text)
        if container_marker:
            self._container_fence = container_marker
            self.unsupported_fence_lines.append(number)
            self.diagnostics.append(
                (
                    number,
                    f'a code fence opened inside a list item or block quote at line {number} '
                    f'({_shorten(text.strip())}) is unsupported; start the fence at the outer level',
                )
            )
        self._feed_text(number, text, neutralized=number in self._neutralized or container_marker is not None)

    def _feed_inside_region(self, number: int, text: str) -> None:
        """Feed a line that starts inside an outer fence, an HTML comment or an unsupported container fence."""
        if self._fence:
            self._feed_fenced(number, text)
        elif self._in_comment:
            if self._comment_midline and not text.strip():
                self._end_midline_comment(number)
            self._feed_text(number, text)
        else:
            if _closes_fence(_container_content(text), self._container_fence):
                self._container_fence = ''
            if not BULLET.match(text) and _structural_title(text, SECTION_LEVEL) is None:
                self.unsupported_fence_lines.append(number)
            self._feed_text(number, text, neutralized=True)

    def _track_list_item(self, text: str) -> None:
        """Remember whether a list item is open: it stays open across blank lines and indented continuation lines."""
        if not text.strip():
            return
        if LIST_ITEM.match(text) and not CONTAINER_QUOTE.match(text):
            self._in_list_item = True
        elif not text.startswith((' ', '\t')):
            self._in_list_item = False

    def _end_midline_comment(self, blank_line: int) -> None:
        """End a mid-line comment at ``blank_line``: Markdown reads it as inline HTML, which a blank line ends."""
        if self.open_region is not None:
            opener = self.open_region.number
            self.diagnostics.append(
                (
                    opener,
                    f'HTML comment opened mid-line at line {opener} is still open at the blank line {blank_line}; '
                    'Markdown ends it there, so the lines after it are visible. Close it on the same line or remove it',
                )
            )
        self.open_region = None
        self._in_comment = False
        self._comment_midline = False

    def _feed_fenced(self, number: int, text: str) -> None:
        if _closes_fence(text, self._fence, exact=True):
            self._fence = ''
            self.open_region = None
        elif _is_longer_fence_closer(text, self._fence):
            self.diagnostics.append(
                (
                    number,
                    f'a fence closer longer than its opener at line {number} ({_shorten(text.strip())}): the docs '
                    'renderer keeps the fence open and CommonMark closes it, so they disagree on what follows. Close '
                    'the fence with a line of the same length',
                )
            )

    def _feed_text(self, number: int, text: str, *, neutralized: bool = False) -> None:
        """Record ``text`` as a visible line; ``neutralized`` keeps it from opening a code fence or comment region."""
        heading = '' if self._in_comment else text
        if not self._in_comment:
            self._track_list_item(text)
        visible, opened, still_open = _strip_comments(
            text, self._in_comment, allow_open=not neutralized and number not in self._neutralized
        )
        self.lines.append(_Line(number, visible, heading, opens_comment=opened or _comment_open_index(visible) >= 0))
        if not still_open:
            self.open_region = None
        elif opened:
            self.open_region = _Region(number, 'HTML comment')
            self._comment_midline = bool(visible.strip())
        self._in_comment = still_open


@dataclass(frozen=True)
class _Scan:
    lines: list[_Line]
    unclosed: list[_Region]
    hidden_headings: list[tuple[_Region, int]]
    hidden_version_headings: list[tuple[_Region, int, str]]
    raw_lines: list[str]
    diagnostics: tuple[tuple[int, str], ...]
    unsupported_fence_lines: frozenset[int]


def _scan(changelog: str) -> _Scan:
    """Scan ``changelog``; a fence or comment that is never closed is reported, then read as plain text.

    Reading it as plain text keeps it from hiding the rest of the file, so later sections are still checked. A fence
    marker inside a list item or block quote is never read as code either: such a line is reported as unsupported, so
    it must not open a region that would hide the lines after it. The scanner knows the enclosing fence or comment
    before it reads a line, so literal fence markers inside one are left alone.
    """
    raw = LINE_BREAK.split(changelog)
    neutralized: set[int] = set()
    unclosed: list[_Region] = []
    while True:
        scanner = _Scanner(frozenset(neutralized))
        for number, text in enumerate(raw, start=1):
            scanner.feed(number, text)
        if scanner.open_region is None:
            return _Scan(
                scanner.lines,
                unclosed,
                scanner.hidden_headings,
                scanner.hidden_version_headings,
                LINE_WITH_BREAK.findall(changelog),
                tuple(scanner.diagnostics),
                frozenset(scanner.unsupported_fence_lines),
            )
        unclosed.append(scanner.open_region)
        neutralized.add(scanner.open_region.number)


@dataclass(frozen=True)
class _Entry:
    """The selected entry: its visible lines, its problems, its exact text and the lines its problems reject.

    ``rejected`` holds the lines that already have a problem of their own (an unsupported shape, a stray ``##``
    heading, a second copy of the version heading, an unsupported fence). The section reader skips them, so each such
    line is reported once, not again as a paragraph or as a bullet with no docs reference.
    """

    lines: list[_Line]
    problems: list[str]
    text: str
    rejected: frozenset[int]


def _find_entry(changelog: str, version: str) -> _Entry | None:
    """Return the lines of the ``## vX.Y.Z`` entry and the problems with its fences and comments, or ``None``."""
    scan = _scan(changelog)
    bare_version = version.removeprefix('v')
    heading = re.compile(rf'## v?{re.escape(bare_version)}(\s|$)')
    start = next((i for i, line in enumerate(scan.lines) if heading.match(line.heading)), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(scan.lines)) if VERSION_HEADING_START.match(scan.lines[i].heading)),
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
    problems += [
        f'{region.kind} opened at line {region.number} hides a copy of the "## v{bare_version}" heading '
        f'at line {number}'
        for region, number, text in scan.hidden_version_headings
        if heading.match(text)
    ]
    lines = scan.lines[start + 1 : end]
    diagnostics = [(number, message) for number, message in sorted(scan.diagnostics) if first <= number < last]
    shapes = _entry_shape_problems(lines)
    stray = _stray_heading_problems(lines) + _copy_problems(scan.lines[start + 1 :], bare_version)
    line_problems = shapes + diagnostics + stray
    rejected = frozenset(number for number, _ in shapes + stray) | scan.unsupported_fence_lines
    text = ''.join(scan.raw_lines[first - 1 : last - 1])
    return _Entry(
        lines,
        problems + [message for _, message in line_problems],
        text if text.endswith(('\n', '\r')) else f'{text}\n',
        rejected,
    )


def _stray_heading_problems(lines: list[_Line]) -> list[tuple[int, str]]:
    """Report ``##`` headings inside an entry, which the release notes extraction would not stop at."""
    return [
        (
            line.number,
            f'"##" heading at line {line.number} ({_shorten(line.heading.strip())}) is inside the entry but is not a '
            f'version heading; the release notes would publish what follows it as part of this entry',
        )
        for line in lines
        if _structural_title(line.heading, ENTRY_LEVEL) is not None
    ]


def _copy_problems(later_lines: list[_Line], bare_version: str) -> list[tuple[int, str]]:
    """Report a second visible copy of the selected version heading anywhere after the first one."""
    copy = re.compile(rf'v?{re.escape(bare_version)}(?=$|[ \t(?#\[])')
    return [
        (
            line.number,
            f'a second visible copy of the entry version heading is at line {line.number} '
            f'({_shorten(line.heading.strip())}); remove it so the entry is published once',
        )
        for line in later_lines
        if _is_version_copy(line.heading, copy)
    ]


def _is_version_copy(text: str, copy: re.Pattern[str]) -> bool:
    """Return whether ``text`` is a visible ``##`` heading for the selected version, in any accepted shape."""
    content = _container_content(text).lstrip(' \t')
    is_level_two = content.startswith('##') and not content.startswith('###')
    return is_level_two and copy.match(content[2:].lstrip(' \t')) is not None


def _entry_shape_problems(lines: list[_Line]) -> list[tuple[int, str]]:
    """Report unsupported heading and delimiter shapes on the visible lines of the entry.

    An issue-number line is read as a wrapped bullet reference only while a list item is open above it, so the
    exception cannot accept a standalone ``#720)`` that a renderer turns into a heading.
    """
    problems: list[tuple[int, str]] = []
    in_list_item = False
    for line in lines:
        text = line.text
        shape = _line_shape_problem(text, list_continuation=in_list_item)
        if shape is not None:
            snippet = _shorten(text.strip())
            problems.append((line.number, f'{shape.description} at line {line.number} ({snippet}); {shape.fix}'))
        if _has_comment_opener_in_code_span(text):
            problems.append(
                (
                    line.number,
                    f'an HTML comment opener inside a code span at line {line.number} ({_shorten(text.strip())}) is '
                    'unsupported; reword it without "<!--"',
                )
            )
        if not text.strip():
            in_list_item = False
            continue
        in_list_item = _opens_list_item(text, continued=in_list_item)
    return problems


def _opens_list_item(text: str, *, continued: bool) -> bool:
    """Return whether ``text`` leaves a list item open for an indented continuation line below it.

    A bullet or numbered item starts one. A quoted item (``> - x``) does not count: a quote body is not a plain list
    continuation for the strict format, so those lines are held to the same rules as any other visible line.
    """
    if LIST_ITEM.match(text) and not CONTAINER_QUOTE.match(text):
        return True
    return continued and text[0] in ' \t' and not LIST_ITEM.match(text)


def _unsupported_shape(text: str) -> str | None:
    return next((description for shape, description in UNSUPPORTED_SHAPES if shape.match(text)), None)


@dataclass
class _Item:
    section: str
    number: int
    parts: list[str]


class _EntryReader:
    """Reads an entry line by line, collecting the gated list items and everything the gate cannot accept."""

    def __init__(self, rejected: frozenset[int]) -> None:
        self.section = NO_SECTION
        self.items: list[_Item] = []
        self.problems: list[str] = []
        self._open: _Item | None = None
        self._rejected = rejected

    def read(self, lines: list[_Line]) -> None:
        for line in lines:
            self._read_line(line)

    def _read_line(self, line: _Line) -> None:
        title = None if line.number in self._rejected else _structural_title(line.heading, SECTION_LEVEL)
        if title is not None:
            self._start_section(line.number, title)
        elif line.number in self._rejected:
            self._skip_rejected_line(line)
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

    def _skip_rejected_line(self, line: _Line) -> None:
        """Close the open item at a line that already has its own problem; report only what hides in it."""
        self._open = None
        if self.section in GATED_SECTIONS:
            self._report_hidden_text(line)

    def _read_gated_line(self, line: _Line) -> None:
        self._report_hidden_text(line)
        reason = 'a code fence' if line.opens_fence else _unsupported_shape(line.text)
        if reason:
            self._open = None
            self._reject(line.number, reason)
        elif not line.text.strip():
            self._open = None
        else:
            self._read_list_line(line)

    def _report_hidden_text(self, line: _Line) -> None:
        """Report a comment or a non-Markdown line break, which hide part of a gated line from some readers."""
        separator = NON_MARKDOWN_BREAK.search(line.text)
        if separator:
            self.problems.append(
                f'U+{ord(separator.group()):04X} at line {line.number} under "### {self.section}" is not a Markdown '
                'line break; remove it'
            )
        if line.opens_comment:
            self.problems.append(f'HTML comment at line {line.number} under "### {self.section}"; remove it')

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
    carriage_returns = _lone_carriage_return_problems(changelog)
    entry = _find_entry(changelog, version)
    if entry is None:
        return [*carriage_returns, f'CHANGELOG.md has no "## v{version.removeprefix("v")}" entry']
    reader = _EntryReader(entry.rejected)
    reader.read(entry.lines)
    bullet_problems = [problem for item in reader.items for problem in _bullet_problems(item, site)]
    return carriage_returns + entry.problems + reader.problems + bullet_problems


def entry_preamble(changelog: str, version: str) -> str | None:
    """Return the prose of the ``## vX.Y.Z`` entry before its first ``###`` heading, or ``None`` if it is missing.

    HTML comments and fenced code are not part of it, as they are not part of the rendered entry.

    Args:
        changelog: The text of ``CHANGELOG.md``.
        version: The release version, with or without the leading ``v``.

    Returns:
        The visible lines of the preamble joined with newlines, or ``None`` when the changelog has no such entry.
    """
    entry = _find_entry(changelog, version)
    if entry is None:
        return None
    preamble: list[str] = []
    for line in entry.lines:
        if _structural_title(line.heading, SECTION_LEVEL) is not None:
            break
        if not line.opens_fence:
            preamble.append(line.text)
    return '\n'.join(preamble)


def release_notes(changelog: str, version: str) -> str | None:
    """Return the exact text of the ``## vX.Y.Z`` entry that ``find_problems`` checks, or ``None`` if it is missing.

    The text runs from the version heading up to, not including, the next version heading, with its line breaks
    unchanged. The release notes are this text, so they cannot differ from what the gate checked.

    Args:
        changelog: The text of ``CHANGELOG.md``, read with its line breaks unchanged.
        version: The release version, with or without the leading ``v``.

    Returns:
        The entry text, or ``None`` when the changelog has no such entry.
    """
    entry = _find_entry(changelog, version)
    return None if entry is None else entry.text


def _lone_carriage_return_problems(changelog: str) -> list[str]:
    r"""Report each ``\r`` not followed by ``\n``: it breaks a line here but not in the tools that read the notes."""
    return [
        f'a carriage return at line {1 + len(LINE_BREAK.findall(changelog, 0, match.start()))} is not followed by a '
        'line feed; use "\\n" or "\\r\\n" line endings'
        for match in LONE_CARRIAGE_RETURN.finditer(changelog)
    ]


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
        with path.open(encoding='utf-8', newline='') as file:
            return file.read()
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheckError(f'cannot read {path}: {error}') from error


def _write_notes(path: Path, notes: str) -> None:
    try:
        with path.open('w', encoding='utf-8', newline='') as file:
            file.write(notes)
    except OSError as error:
        raise CannotCheckError(f'cannot write {path}: {error}') from error


def _check(args: argparse.Namespace) -> tuple[str, list[str]]:
    changelog = _read_changelog(args.changelog)
    version = newest_version(changelog) if args.newest else args.version
    if not version.removeprefix('v'):
        raise CannotCheckError('the version is empty')
    problems = find_problems(changelog, version, BuiltSite(args.site_dir))
    if args.notes_out is not None:
        args.notes_out.unlink(missing_ok=True)
        notes = None if problems else release_notes(changelog, version)
        if notes is not None:
            _write_notes(args.notes_out, notes)
    return version, problems


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        'version', nargs='?', help='version being released, with or without the leading v (e.g. 1.12.1)'
    )
    parser.add_argument('--newest', action='store_true', help='check the topmost entry of the changelog instead')
    parser.add_argument('--site-dir', type=Path, required=True, help='output directory of `mkdocs build --strict`')
    parser.add_argument('--changelog', type=Path, default=DEFAULT_CHANGELOG, help='path to CHANGELOG.md')
    parser.add_argument(
        '--notes-out',
        type=Path,
        help='when the check passes, write the exact text of the checked entry here, for the release notes',
    )
    args = parser.parse_args(argv)
    if args.newest == (args.version is not None):
        parser.error('give exactly one of the version and --newest')
    return args


def _write_output_as_utf8() -> None:
    # Windows consoles default to a legacy code page (cp1252) that cannot encode every changelog character.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding='utf-8', errors=stream.errors)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: The command-line arguments; ``sys.argv[1:]`` when ``None``.

    Returns:
        The process exit code: 0 when the entry passes, 1 when it has problems, 2 when the check could not run.
    """
    _write_output_as_utf8()
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
