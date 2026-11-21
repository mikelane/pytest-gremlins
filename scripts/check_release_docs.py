#!/usr/bin/env python3
"""Release docs gate: refuse a release whose changelog entry has undocumented user-facing changes.

Takes the version being released. In that version's ``## vX.Y.Z`` entry of ``CHANGELOG.md``, every bullet under
``### Upgrade notes``, ``### Feature`` and ``### Fix`` must carry either a docs reference or an explicit exemption.
``### Internal`` and ``### Documentation`` bullets are exempt.

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

These line rules cover the whole selected entry, in the preamble, the exempt sections and the gated sections alike:

* Only the exact ``### <section>`` headings (up to 3 leading spaces, optional tab after the hashes, optional
  closing hashes) and the ``## [v]X.Y.Z`` version headings are accepted. Any other line that starts with ``#`` is an
  unsupported heading, whether or not a renderer would make one of it: ``#Feature``, ``####Detail``, ``###Feature``,
  ``#Feature ###``, ``##v2.0.0`` and ``#<TAB>Feature`` all fail. The one exception is an indented continuation
  line directly under an open list item, such as ``  #989-#994)`` or ``  #964 for details``: the renderer reads it
  as paragraph text. It still fails when it is heading-shaped (``  ### Internal``), and a standalone ``    #720)``
  after a blank line renders as a heading and fails.
* A line that starts with an HTML tag (``<div>``, ``</div>``, ``<?php``, ``<![CDATA[``), after any indentation or
  list and block-quote prefix, is rejected: the renderer reads it as a raw HTML block and leaves a ``###`` line
  inside it as literal text.
* A code fence has to open at the outer level, indented by at most 3 spaces. A fence indented 4 or more columns, one
  under a list item and one inside a block quote or after a list marker are reported as unsupported instead of being
  read as code. A fence closes only on a closer of exactly the opener's length, as the docs renderer reads it, and a
  longer closer is rejected because CommonMark would close there.
* An HTML comment that opens mid-line ends at the next blank line, as Markdown reads it, so one still open there is
  rejected and the lines after it are checked. An unclosed ``<!--`` in a code span is rejected too, because a reader
  may take it for a comment. Code spans pair as the docs renderer pairs them (``code_spans``), and every visible line
  must pair its own backticks exactly, because the renderer pairs across the lines of a paragraph. A run of more than
  ``MAX_BACKTICK_RUN`` backticks is rejected anywhere in the entry, and so is a backtick on a line that shows text
  beside an HTML comment, because the renderer pairs backticks before it reads the comment.
* Every thematic break or setext-underline shape is rejected, in every section and with no attempt to guess the
  previous line: a run of ``=``, a run of one or two ``-``, and ``***``, ``---``, ``___``, ``* * *`` and ``- - -``.
  This also rejects a delimiter under a pipe or inline-HTML line, so ``A | B`` + ``---`` and
  ``<em>Feature</em>`` + ``---`` cannot hide a rendered heading.
* A raw ``<h1>``-``<h6>`` tag is rejected wherever a reader can see it, in any case and with attributes, because the
  renderer turns it into a real heading inside a block quote or a list item too. A tag written as a code span
  (```<h1>```) stays literal text.
* The heading, HTML and delimiter rules apply again after the list-marker and block-quote prefixes are stripped, so
  ``> #Feature``, ``- #### Detail``, ``> <em>Feature</em>`` + ``> ---`` and ``- ---`` fail too.

A rejected line is reported once, with its own problems and a hint on how to fix it, not again as a paragraph or as a
bullet with no docs reference.

A second visible copy of the selected version heading is a problem wherever it sits, including the no-space
(``##v2.0.0``), indented and quoted or listed variants, because ``--notes-out`` publishes only the first copy while
readers see both.

A line longer than 1000 characters is a problem wherever it sits in the entry, inside a fence or comment too. It is
reported before any pattern reads it and is then read as a blank line. With ``--newest``, a long line above the
topmost version heading exits 2, because it could be that heading. Code spans are found in time linear in the length
of the text times ``MAX_BACKTICK_RUN``, so no run of backticks makes the check slow. The cap does not bound a gated
bullet, which
joins its continuation lines: the docs-link and ``(no docs:`` patterns still take time quadratic in the length of one
bullet (a bullet of 100 lines of ``[`` takes seconds).

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
import bisect
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
OUTER_FENCE = re.compile(r' {0,3}(`{3,}|~{3,})(.*)')
ANY_INDENT_FENCE = re.compile(r'\s*(`{3,}|~{3,})(.*)')
COMMENT_OPEN = '<!--'
COMMENT_CLOSE = '-->'
BACKTICK_RUN = re.compile(r'`+')
MAX_BACKTICK_RUN = 8
# The docs renderer's "backtick" inline pattern, copied verbatim from BACKTICK_CODE_RE in pymdownx/inlinehilite.py
# (pymdown-extensions 12.1 in uv.lock). It replaces Python-Markdown's own pattern at priority 190 and runs before
# every other inline pattern, escapes included, so nothing else changes how backticks pair.
RENDERER_BACKTICK = re.compile(r'(?:(?<!\\)((?:\\{2})+)(?=`+)|(?<!\\)`)')
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


def _line_shape_problem(text: str, *, list_continuation: bool) -> _ShapeProblem | None:
    """Describe a heading or delimiter shape the accepted changelog format rejects, or return ``None``.

    The format is strict on purpose: a visible line is allowed only if it is an ATX ``###`` or ``##`` heading
    (unknown titles and stray ``##`` lines are reported elsewhere), ordinary prose or a list line. A ``##``/``###``
    line with a valid title passes here; ``_stray_heading_problems`` and ``_EntryReader._start_section`` decide
    whether the title is allowed. Anything that starts with ``#`` in another shape is
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
    starts_with_hash = content.lstrip(' \t').startswith('#')
    if starts_with_hash and not _is_continuation_text(text, content, list_continuation=list_continuation):
        return _hash_line_problem(text, content, list_continuation=list_continuation)
    if _is_html_heading(text):
        return RAW_HTML_HEADING
    if _starts_html_tag(text) or _starts_html_tag(content):
        return RAW_HTML_BLOCK
    if THEMATIC_OR_SETEXT.match(text) or THEMATIC_OR_SETEXT.match(content):
        return DELIMITER_LINE
    return None


def _is_continuation_text(text: str, content: str, *, list_continuation: bool) -> bool:
    """Return whether ``text`` is paragraph text of the list item above it that no renderer reads as a heading."""
    if not list_continuation or content != text or not text.startswith((' ', '\t')):
        return False
    return ATX_HEADING_SHAPE.match(text.lstrip(' \t')) is None


def _hash_line_problem(text: str, content: str, *, list_continuation: bool) -> _ShapeProblem | None:
    """Judge a line whose content starts with ``#``: only an outer ``###`` or ``##`` heading passes."""
    if content != text:
        return UNSUPPORTED_HEADING
    if list_continuation and text.startswith((' ', '\t')):
        return UNSUPPORTED_HEADING
    if _structural_title(text, SECTION_LEVEL) is None and _structural_title(text, ENTRY_LEVEL) is None:
        return UNSUPPORTED_HEADING
    return None


def _is_html_heading(text: str) -> bool:
    """Return whether ``text`` holds a visible raw ``<h1>``-``<h6>`` tag outside a code span.

    A renderer turns these tags into real headings even inside a block quote or a list item, so the strict format
    rejects them wherever the line is visible. A tag written as a code span (```<h1>```) stays literal text.
    """
    return bool(HTML_HEADING.search(_without_code_spans(text)))


@dataclass(frozen=True)
class _Pairing:
    """The code spans of a text as the docs renderer pairs them, and whether every opener closed at its own length."""

    spans: list[tuple[int, int]]
    exact: bool


class _BacktickRuns:
    """The maximal backtick runs of a text, indexed by length, so finding a closer takes a few bisections."""

    def __init__(self, text: str) -> None:
        self.runs = [match.span() for match in BACKTICK_RUN.finditer(text)]
        self._starts = [start for start, _ in self.runs]
        self._indexes_by_length: dict[int, list[int]] = {}
        for index, (start, end) in enumerate(self.runs):
            self._indexes_by_length.setdefault(end - start, []).append(index)
        self.lengths_longest_first = sorted(self._indexes_by_length, reverse=True)

    def close(self, begin: int) -> tuple[int, bool] | None:
        """Return where the span opened at ``begin`` ends and whether a run of the opener's length closed it.

        This is ``InlineHilitePattern.find_code_spans`` with its consumed range from ``handleMatch``: the opener is
        the rest of the run at ``begin``, the first later run of the same length closes it, and without one the first
        of the longest later runs does. Characters between the opener and the content are dropped then, so the whole
        range is hidden. ``None`` means no backtick follows the run at all.
        """
        run = bisect.bisect_right(self._starts, begin) - 1
        ticks = self.runs[run][1] - begin
        closer = self._first_after(run, ticks)
        if closer is not None:
            return self.runs[closer][1], True
        later = (self._first_after(run, length) for length in self.lengths_longest_first)
        fallback = next((index for index in later if index is not None), None)
        return None if fallback is None else (self.runs[fallback][1], False)

    def _first_after(self, run: int, length: int) -> int | None:
        indexes = self._indexes_by_length.get(length, [])
        position = bisect.bisect_right(indexes, run)
        return indexes[position] if position < len(indexes) else None


def _pair_backticks(text: str) -> _Pairing:
    """Pair the backticks of ``text`` as the docs renderer does; a run over the cap leaves the text with no spans.

    The renderer searches with ``RENDERER_BACKTICK`` from the left. An even run of backslashes before a backtick is
    stashed as escaped backslashes, so the backtick after it opens a span. A backtick after an odd run is escaped, so
    the next backtick of its run opens instead. When an opener has no backtick after its run, no later match can pair
    either, so the search stops. Each opener costs a few bisections, so the time is linear in the length of ``text``
    times ``MAX_BACKTICK_RUN``.
    """
    runs = _BacktickRuns(text)
    if runs.lengths_longest_first and runs.lengths_longest_first[0] > MAX_BACKTICK_RUN:
        return _Pairing([], exact=False)
    spans: list[tuple[int, int]] = []
    exact = True
    position = 0
    while (match := RENDERER_BACKTICK.search(text, position)) is not None:
        begin = match.end() if match.group(1) else match.start()
        closed = runs.close(begin)
        if closed is None:
            return _Pairing(spans, exact=False)
        position, closed_exactly = closed
        exact = exact and closed_exactly
        spans.append((begin, position))
    return _Pairing(spans, exact)


def code_spans(text: str) -> list[tuple[int, int]]:
    r"""Return the ``(start, end)`` bounds of every code span in ``text``, backticks included, as the docs pair them.

    The docs renderer is Python-Markdown with ``pymdownx.inlinehilite``. An opener closes at the next run of its own
    length, or, without one, at the first of the longest later runs, so ```` ``a` ```` is one span. A backslash escapes
    the first backtick of a run, an escaped backslash pair escapes nothing, and a backslash inside a span is literal.
    Text with a run of more than ``MAX_BACKTICK_RUN`` backticks has no spans; the line is reported instead.

    >>> code_spans('a `b` and ``c`d`` and `e')
    [(2, 5), (10, 17)]
    >>> code_spans('\\`b` c`')
    [(3, 7)]
    >>> code_spans('``a`')
    [(0, 4)]
    """
    return _pair_backticks(text).spans


def _backtick_problem(number: int, text: str, visible: str, in_block_comment: bool) -> str | None:
    """Describe how the backticks of the raw line ``text`` could make the gate and the renderer disagree, or ``None``.

    A run over ``MAX_BACKTICK_RUN`` is rejected before anything pairs it. An opener that closes at a run of another
    length, or not at all, is rejected, because the renderer pairs backticks across the lines of a paragraph: when
    every run closes at a run of its own length on its own line, a line, a joined bullet and the rendered paragraph
    pair the same way. A backtick on a line that shows text beside an HTML comment (``visible`` is what is left) is
    rejected, because the renderer pairs backticks before it reads an inline comment: it can pair a backtick inside
    the comment with one outside it, and the gate, which pairs the text left after removing the comment, would not.
    The one exemption is a line that shows nothing inside a comment opened at the start of a line
    (``in_block_comment``): the renderer stores that comment as an HTML block before it pairs any backtick.
    """
    snippet = _shorten(text.strip())
    runs = _BacktickRuns(text)
    if runs.lengths_longest_first and runs.lengths_longest_first[0] > MAX_BACKTICK_RUN:
        return (
            f'a run of more than {MAX_BACKTICK_RUN} backticks at line {number} ({snippet}); '
            f'write code spans with at most {MAX_BACKTICK_RUN} backticks'
        )
    if runs.runs and visible != text and visible.strip():
        return (
            f'a backtick on a line that also has an HTML comment at line {number} ({snippet}); the docs renderer '
            'pairs backticks before it reads comments, so move the comment to its own line'
        )
    if not (in_block_comment and not visible.strip()) and not _pair_backticks(text).exact:
        return (
            f'an unpaired backtick run at line {number} ({snippet}); close every code span on the line it opens on '
            'with a run of the same length, or escape a literal backtick as "\\`"'
        )
    return None


def _without_code_spans(text: str) -> str:
    """Return ``text`` with every code span replaced by one space, so no pattern reads what a span holds."""
    visible: list[str] = []
    position = 0
    for start, end in code_spans(text):
        visible.extend((text[position:start], ' '))
        position = end
    visible.append(text[position:])
    return ''.join(visible)


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


def _outer_fence_marker(text: str) -> str | None:
    """Return the marker when ``text`` opens a fence at the outer level: indented by at most 3 spaces."""
    return _marker_of(OUTER_FENCE.match(text))


def _nested_fence_marker(text: str, *, in_list_item: bool) -> str | None:
    """Return the marker when ``text`` looks like a fence a renderer reads as indented code or list-item code.

    Four or more columns of indentation make an indented code block, and any indentation under an open list item
    belongs to that item. Neither is the outer-level fence the accepted format supports.
    """
    if not text.startswith((' ', '\t')):
        return None
    if OUTER_FENCE.match(text) is not None and not in_list_item:
        return None
    return _marker_of(ANY_INDENT_FENCE.match(text))


def _container_fence_marker(text: str) -> str | None:
    """Return the fence marker when ``text`` opens a fence inside a list item or block quote, else ``None``."""
    content = _container_content(text)
    return _outer_fence_marker(content) if content != text else None


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
    """Return whether ``text`` is a closer longer than ``marker``, where CommonMark and the docs renderer disagree."""
    length = _fence_closer_length(text, marker)
    return length is not None and length > len(marker)


def _comment_open_index(text: str) -> int:
    """Return the index of the first ``<!--`` that is not inside a code span, or ``-1``.

    A ``<!--`` written as a code span is literal text, so it opens no comment.
    """
    spans = iter(code_spans(text))
    span_end = 0
    span_start = -1
    index = text.find(COMMENT_OPEN)
    while index >= 0:
        while index >= span_end:
            span_start, span_end = next(spans, (len(text), len(text) + 1))
        if index < span_start:
            return index
        index = text.find(COMMENT_OPEN, span_end)
    return -1


def _has_unclosed_comment_opener_in_code_span(text: str) -> bool:
    """Return whether ``text`` writes an unclosed ``<!--`` inside a code span, which a reader may take for a comment.

    A span that holds the whole comment (``<!-- x -->``) is literal text and is fine.
    """
    spans = (text[start:end] for start, end in code_spans(text))
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
        self.unsupported_fence_lines: list[tuple[int, int]] = []
        self.open_region: _Region | None = None
        self._neutralized = neutralized
        self._fence = ''
        self._neutralized_fence = ''
        self._neutralized_fence_opener = 0
        self._in_comment = False
        self._comment_midline = False
        self._comment_is_block = False
        self._in_list_item = False

    def feed(self, number: int, text: str) -> None:
        if len(text) > MAX_LINE_LENGTH:
            self.diagnostics.append((number, f'line {number} is longer than {MAX_LINE_LENGTH} characters'))
            text = ''
        if self.open_region is not None and _structural_title(text, SECTION_LEVEL) is not None:
            self.hidden_headings.append((self.open_region, number))
        if self.open_region is not None and VERSION_HEADING_START.match(text):
            self.hidden_version_headings.append((self.open_region, number, text))
        if self._fence or self._in_comment or self._neutralized_fence:
            self._feed_inside_region(number, text)
            return
        neutralized = number in self._neutralized
        if not self._open_fence_or_container(number, text, neutralized=neutralized):
            self._feed_text(number, text, neutralized=neutralized)

    def _open_fence_or_container(self, number: int, text: str, *, neutralized: bool) -> bool:
        """Open the fence that ``text`` starts, if any, and return whether the line has been read."""
        if neutralized:
            return False
        nested = _nested_fence_marker(text, in_list_item=self._in_list_item)
        if nested:
            reason = NESTED_FENCE_UNDER_LIST_ITEM if self._in_list_item else NESTED_FENCE_FOUR_COLUMNS
            self._open_unsupported_fence(
                number,
                nested,
                f'an indented code fence at line {number} ({_shorten(text.strip())}) is unsupported: {reason}',
            )
            self._feed_text(number, text, neutralized=True)
            return True
        marker = _outer_fence_marker(text)
        if marker:
            self._in_list_item = False
            self._fence = marker
            self.open_region = _Region(number, 'code fence')
            self.lines.append(_Line(number, text, opens_fence=True))
            return True
        container_marker = _container_fence_marker(text)
        if container_marker:
            self._open_unsupported_fence(
                number,
                container_marker,
                f'a code fence opened inside a list item or block quote at line {number} ({_shorten(text.strip())}) '
                'is unsupported; start the fence at the outer level',
            )
            self._feed_text(number, text, neutralized=True)
            return True
        return False

    def _open_unsupported_fence(self, number: int, marker: str, diagnostic: str) -> None:
        """Report a fence the format does not support and read its lines as plain text until it closes."""
        self._neutralized_fence = marker
        self._neutralized_fence_opener = number
        self.unsupported_fence_lines.append((number, number))
        self.diagnostics.append((number, diagnostic))

    def _feed_inside_region(self, number: int, text: str) -> None:
        """Feed a line that starts inside an outer fence, an HTML comment or an unsupported container fence."""
        if self._fence:
            self._feed_fenced(number, text)
        elif self._in_comment:
            if self._comment_midline and not text.strip():
                self._end_midline_comment(number)
            self._feed_text(number, text)
        else:
            if _closes_fence(_container_content(text), self._neutralized_fence):
                self._neutralized_fence = ''
            if not BULLET.match(text) and _structural_title(text, SECTION_LEVEL) is None:
                self.unsupported_fence_lines.append((self._neutralized_fence_opener, number))
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
        if opened:
            self._comment_is_block = text.startswith(COMMENT_OPEN)
        in_block_comment = (opened or self._in_comment) and self._comment_is_block
        backtick_problem = None if neutralized else _backtick_problem(number, text, visible, in_block_comment)
        if backtick_problem:
            self.diagnostics.append((number, backtick_problem))
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
    unsupported_fence_lines: tuple[tuple[int, int], ...]


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
                tuple(scanner.unsupported_fence_lines),
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
    span = _entry_span(scan, heading)
    if span is None:
        return None
    start, end = span
    first = scan.lines[start].number
    last = scan.lines[end].number if end < len(scan.lines) else sys.maxsize
    lines = scan.lines[start + 1 : end]
    diagnostics = [(number, message) for number, message in sorted(scan.diagnostics) if first <= number < last]
    shapes = _entry_shape_problems(lines)
    headings = _stray_heading_problems(lines) + _duplicate_version_heading_problems(
        scan.lines[start + 1 :], bare_version
    )
    fence_lines = (number for opener, number in scan.unsupported_fence_lines if first <= opener < last)
    rejected = frozenset(number for number, _ in shapes + headings) | frozenset(fence_lines)
    text = ''.join(scan.raw_lines[first - 1 : last - 1])
    return _Entry(
        lines,
        _region_problems(scan, first, last, heading, bare_version)
        + [message for _, message in shapes + diagnostics + headings],
        text if text.endswith(('\n', '\r')) else f'{text}\n',
        rejected,
    )


def _entry_span(scan: _Scan, heading: re.Pattern[str]) -> tuple[int, int] | None:
    """Return the indexes in ``scan.lines`` of the entry heading and of the next version heading (or the end)."""
    start = next((i for i, line in enumerate(scan.lines) if heading.match(line.heading)), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(scan.lines)) if VERSION_HEADING_START.match(scan.lines[i].heading)),
        len(scan.lines),
    )
    return start, end


def _region_problems(scan: _Scan, first: int, last: int, heading: re.Pattern[str], bare_version: str) -> list[str]:
    """Report fences and comments in the entry that never close or that hide a heading, and hidden version copies."""
    never_closed = [
        f'{region.kind} opened at line {region.number} is never closed'
        for region in scan.unclosed
        if first <= region.number < last
    ]
    hiding = [
        f'{region.kind} opened at line {region.number} hides the "###" heading at line {number}'
        for region, number in scan.hidden_headings
        if first <= number < last
    ]
    hidden_copies = [
        f'{region.kind} opened at line {region.number} hides a copy of the "## v{bare_version}" heading '
        f'at line {number}'
        for region, number, text in scan.hidden_version_headings
        if heading.match(text)
    ]
    return never_closed + hiding + hidden_copies


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


def _duplicate_version_heading_problems(later_lines: list[_Line], bare_version: str) -> list[tuple[int, str]]:
    """Report a second visible copy of the selected version heading anywhere after the first one."""
    version_heading_pattern = re.compile(rf'v?{re.escape(bare_version)}(?=$|[ \t(?#\[])')
    return [
        (
            line.number,
            f'a second visible copy of the entry version heading is at line {line.number} '
            f'({_shorten(line.heading.strip())}); remove it so the entry is published once',
        )
        for line in later_lines
        if _is_duplicate_version_heading(line.heading, version_heading_pattern)
    ]


def _is_duplicate_version_heading(text: str, version_heading_pattern: re.Pattern[str]) -> bool:
    """Return whether ``text`` is a visible ``##`` heading for the selected version, in any accepted shape."""
    content = _container_content(text).lstrip(' \t')
    is_level_two = content.startswith('##') and not content.startswith('###')
    return is_level_two and version_heading_pattern.match(content[2:].lstrip(' \t')) is not None


def _entry_shape_problems(lines: list[_Line]) -> list[tuple[int, str]]:
    """Report unsupported heading and delimiter shapes on the visible lines of the entry.

    An indented line that starts with ``#`` but is not heading-shaped is read as a continuation of a list item only
    while one is open directly above it, so a standalone ``#720)`` that a renderer turns into a heading is still
    rejected.
    """
    problems: list[tuple[int, str]] = []
    in_list_item = False
    for line in lines:
        text = line.text
        shape = _line_shape_problem(text, list_continuation=in_list_item)
        if shape is not None:
            snippet = _shorten(text.strip())
            problems.append((line.number, f'{shape.description} at line {line.number} ({snippet}); {shape.fix}'))
        if _has_unclosed_comment_opener_in_code_span(text):
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
        CannotCheckError: When the changelog has no ``##`` heading, the topmost one is not a version entry, or a line
            above it is too long to read (it could be the topmost heading). An older entry is never selected instead.
    """
    for line in _scan(changelog).lines:
        if _structural_title(line.text, ENTRY_LEVEL) is None:
            continue
        heading = NEWEST_HEADING.match(line.text)
        if heading is None:
            raise CannotCheckError(
                f'the topmost "##" heading, "{line.text.strip()}" at line {line.number}, is not a "## vX.Y.Z" entry'
            )
        _refuse_an_overlong_line_above(changelog, line.number)
        return heading.group(1)
    _refuse_an_overlong_line_above(changelog, sys.maxsize)
    raise CannotCheckError('CHANGELOG.md has no "## vX.Y.Z" entry')


def _refuse_an_overlong_line_above(changelog: str, line_number: int) -> None:
    """Raise when a line above ``line_number`` is too long to read, since it may hide the topmost heading."""
    lines = LINE_BREAK.split(changelog)[: line_number - 1]
    overlong = next((number for number, text in enumerate(lines, start=1) if len(text) > MAX_LINE_LENGTH), None)
    if overlong is not None:
        raise CannotCheckError(
            f'line {overlong} is longer than {MAX_LINE_LENGTH} characters, so the topmost entry cannot be found'
        )


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
    visible = _without_code_spans(text)
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
