"""Tests for scripts/check_release_docs.py -- the gate that blocks a release with undocumented changes."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

import pytest
import yaml

if TYPE_CHECKING:
    from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_release_docs.py'
WORKFLOWS = Path(__file__).resolve().parents[2] / '.github' / 'workflows'
GATE_COMMAND = 'check_release_docs.py'
DOCS_URL = 'https://pytest-gremlins.readthedocs.io/en/latest'
SITE_PAGES = {'guide/configuration': frozenset({'batch-size', 'caching'}), '': frozenset()}
LINEAR_TIME_BUDGET_SECONDS = 0.5


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_release_docs', SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules['check_release_docs'] = module
    spec.loader.exec_module(module)
    return module


class FakeSite:
    def __init__(self, pages: dict[str, frozenset[str]]) -> None:
        self._pages = pages

    def anchors_of(self, page: str) -> frozenset[str] | None:
        return self._pages.get(page)


SITE = FakeSite(SITE_PAGES)


def _entry(gated_bullets: str, section: str = 'Fix') -> str:
    return f"""\
# Changelog

## v2.0.0 (2026-11-01)

Intro paragraph.

### {section}

{gated_bullets}

### Internal

- Bumped a dev dependency. (#1)

## v1.9.0 (2026-10-01)

### Fix

- An old bullet with no docs reference at all. (#2)
"""


@pytest.mark.small
class DescribeEntryLookup:
    def it_reports_a_missing_entry(self) -> None:
        checker = _load_checker()

        problems = checker.find_problems('# Changelog\n\n## v1.0.0 (2026-01-01)\n', 'v2.0.0', SITE)

        assert len(problems) == 1
        assert 'v2.0.0' in problems[0]

    @pytest.mark.parametrize('version', ['2.0.0', 'v2.0.0'])
    def it_accepts_the_version_with_or_without_the_v_prefix(self, version: str) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/) (#3)'

        assert checker.find_problems(_entry(bullet), version, SITE) == []

    def it_does_not_match_a_longer_version_with_the_same_prefix(self) -> None:
        checker = _load_checker()

        problems = checker.find_problems('## v2.0.01 (2026-01-01)\n\n### Fix\n\n- x\n', '2.0.0', SITE)

        assert problems == ['CHANGELOG.md has no "## v2.0.0" entry']

    def it_only_checks_the_requested_entry(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/) (#3)'

        assert checker.find_problems(_entry(bullet), '2.0.0', SITE) == []


@pytest.mark.small
class DescribeGatedBullets:
    @pytest.mark.parametrize('section', ['Upgrade notes', 'Feature', 'Fix'])
    def it_fails_a_bullet_with_no_reference_in_each_gated_section(self, section: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry('- **Changed a thing.** (#3)', section), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'Changed a thing' in problems[0]
        assert section in problems[0]

    def it_names_the_bullet_by_line_number(self) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry('- **Changed a thing.** (#3)'), '2.0.0', SITE)

        assert 'line 9' in problems[0]

    def it_exempts_the_internal_section(self) -> None:
        checker = _load_checker()

        assert checker.find_problems(_entry('- **Changed a thing.** [docs](x)', 'Internal'), '2.0.0', SITE) == []

    def it_accepts_an_exemption_with_a_reason(self) -> None:
        checker = _load_checker()

        bullet = '- **Restored documented behavior.** (no docs: restores the behavior the docs already describe) (#3)'

        assert checker.find_problems(_entry(bullet), '2.0.0', SITE) == []

    @pytest.mark.parametrize('exemption', ['(no docs: )', '(no docs:)', '(no docs:   )'])
    def it_rejects_an_empty_exemption(self, exemption: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry(f'- **Fixed it.** {exemption}'), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'empty' in problems[0]

    def it_rejects_an_empty_exemption_even_beside_a_reference(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/) (no docs: )'

        problems = checker.find_problems(_entry(bullet), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'has an empty "(no docs: )" exemption' in problems[0]
        assert 'Fixed it' in problems[0]

    def it_reads_a_reference_on_a_continuation_line(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** A long\n  description that wraps. [docs]({DOCS_URL}/guide/configuration/)'

        assert checker.find_problems(_entry(bullet), '2.0.0', SITE) == []

    def it_treats_a_non_docs_link_as_no_reference(self) -> None:
        checker = _load_checker()
        bullet = '- **Fixed it.** [issue](https://github.com/mikelane/pytest-gremlins/issues/3)'

        problems = checker.find_problems(_entry(bullet), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'has no docs reference' in problems[0]
        assert 'Fixed it' in problems[0]

    def it_treats_a_non_latest_docs_url_as_no_reference(self) -> None:
        checker = _load_checker()
        bullet = '- **Fixed it.** [docs](https://pytest-gremlins.readthedocs.io/en/stable/guide/configuration/)'

        problems = checker.find_problems(_entry(bullet), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'has no docs reference' in problems[0]
        assert 'Fixed it' in problems[0]

    def it_reports_every_failing_bullet(self) -> None:
        checker = _load_checker()
        bullets = '- **First.** (#3)\n- **Second.** (#4)'

        problems = checker.find_problems(_entry(bullets), '2.0.0', SITE)

        assert len(problems) == 2
        assert 'First' in problems[0]
        assert 'Second' in problems[1]


@pytest.mark.small
class DescribeSectionHeadings:
    @pytest.mark.parametrize('heading', ['Feat', 'Features', 'Fixed', 'Fixes', 'Upgrade Notes', 'Changed', 'Perf'])
    def it_names_a_heading_outside_the_known_sections(self, heading: str) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/)'

        problems = checker.find_problems(_entry(bullet, heading), '2.0.0', SITE)

        assert len(problems) == 1
        assert f'"### {heading}"' in problems[0]

    @pytest.mark.parametrize('heading', ['Upgrade notes', 'Feature', 'Fix', 'Internal', 'Documentation'])
    def it_accepts_each_known_section(self, heading: str) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/)'

        assert checker.find_problems(_entry(bullet, heading), '2.0.0', SITE) == []

    def it_exempts_the_documentation_section(self) -> None:
        checker = _load_checker()

        assert checker.find_problems(_entry('- **Reworded a page.** (#3)', 'Documentation'), '2.0.0', SITE) == []

    def it_fails_a_bullet_that_sits_under_no_section_heading(self) -> None:
        checker = _load_checker()
        changelog = '## v2.0.0 (2026-11-01)\n\n- **The default batch size is now 10.** (#1)\n'

        problems = checker.find_problems(changelog, '2.0.0', SITE)

        assert len(problems) == 1
        assert 'no "###" section heading' in problems[0]
        assert 'default batch size' in problems[0]


@pytest.mark.small
class DescribeBulletMarkers:
    MARKERS = ('- ', '* ', '+ ', '1. ', '1) ', ' - ', '   * ', '  12) ')

    @pytest.mark.parametrize('marker', MARKERS)
    def it_gates_a_bullet_written_with_any_commonmark_list_marker(self, marker: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry(f'{marker}**Changed a thing.** (#3)'), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'Changed a thing' in problems[0]

    @pytest.mark.parametrize('marker', MARKERS)
    def it_accepts_a_linked_bullet_written_with_any_commonmark_list_marker(self, marker: str) -> None:
        checker = _load_checker()
        bullet = f'{marker}**Fixed it.** [docs]({DOCS_URL}/guide/configuration/)'

        assert checker.find_problems(_entry(bullet), '2.0.0', SITE) == []


@pytest.mark.small
class DescribeNestedSubBullets:
    def it_gates_a_sub_bullet_separately_from_its_linked_parent(self) -> None:
        checker = _load_checker()
        bullets = (
            f'- **Parent change.** [docs]({DOCS_URL}/guide/configuration/)\n'
            '  - **A second, unrelated user-visible change with no docs.**'
        )

        problems = checker.find_problems(_entry(bullets), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'second, unrelated' in problems[0]

    def it_gates_a_parent_separately_from_its_linked_sub_bullet(self) -> None:
        checker = _load_checker()
        bullets = f'- **Parent change.**\n  - **Child change.** [docs]({DOCS_URL}/guide/configuration/)'

        problems = checker.find_problems(_entry(bullets), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'Parent change' in problems[0]

    def it_reads_a_link_alone_on_an_indented_continuation_line(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** (#3)\n  [docs]({DOCS_URL}/guide/configuration/)'

        assert checker.find_problems(_entry(bullet), '2.0.0', SITE) == []


@pytest.mark.small
class DescribeInvisibleReferences:
    @pytest.mark.parametrize(
        'text',
        [
            '`[docs](guide/configuration.md#batch-size)`',
            '``[docs](guide/configuration.md#batch-size)``',
            'Write `(no docs: <reason>)` to exempt a bullet.',
            '![docs](guide/configuration.md#batch-size)',
            r'\[docs](guide/configuration.md#batch-size)',
        ],
    )
    def it_ignores_a_reference_or_exemption_a_reader_cannot_see(self, text: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry(f'- **Changed a thing.** {text}'), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'no docs reference' in problems[0]
        assert 'Changed a thing' in problems[0]

    def it_still_reads_a_visible_reference_beside_a_code_span(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed `it`.** [docs]({DOCS_URL}/guide/configuration/)'

        assert checker.find_problems(_entry(bullet), '2.0.0', SITE) == []

    def it_keeps_the_line_numbers_of_bullets_after_a_multi_line_comment(self) -> None:
        checker = _load_checker()
        changelog = '## v2.0.0\n\n<!--\nnote\n-->\n\n### Fix\n\n- **Changed a thing.** (#3)\n'

        assert 'line 9' in checker.find_problems(changelog, '2.0.0', SITE)[0]


@pytest.mark.small
class DescribeFencedCode:
    def it_does_not_end_the_entry_at_a_heading_inside_a_fence(self) -> None:
        checker = _load_checker()
        changelog = (
            '## v2.0.0\n\n### Internal\n\n'
            '```markdown\n## v1.0.0\n```\n\n'
            '### Fix\n\n- **Changed a thing after the fence.** (#3)\n'
        )

        problems = checker.find_problems(changelog, '2.0.0', SITE)

        assert len(problems) == 1
        assert 'after the fence' in problems[0]

    @pytest.mark.parametrize('fence', ['```', '~~~', '````'])
    def it_does_not_gate_a_bullet_shaped_line_inside_a_fence(self, fence: str) -> None:
        checker = _load_checker()
        changelog = f'## v2.0.0\n\n{fence}\n- not a real bullet\n{fence}\n'

        assert checker.find_problems(changelog, '2.0.0', SITE) == []

    def it_does_not_find_an_entry_heading_inside_a_fence(self) -> None:
        checker = _load_checker()
        changelog = '```markdown\n## v2.0.0\n```\n'

        assert 'no "## v2.0.0" entry' in checker.find_problems(changelog, '2.0.0', SITE)[0]


def _problems_of(body: str) -> str:
    """Return every problem the checker reports for a ``v2.0.0`` entry made of ``body``, one per line."""
    checker = _load_checker()
    changelog = f'# Changelog\n\n## v2.0.0 (2026-11-01)\n\n{body}\n\n## v1.9.0 (2026-10-01)\n\n### Internal\n\n- x\n'
    return '\n'.join(checker.find_problems(changelog, '2.0.0', SITE))


LINKED = f'[docs]({DOCS_URL}/guide/configuration/)'
INDENTED_HEADING_AT = 'an indented heading at line'
INDENTED_HEADING_FIX = (
    'start the heading at column 0; the docs renderer makes a heading only from a "#" at column 0 and shows an '
    'indented one as text, so the section does not change there'
)
INDENTED_INTERNAL_UNDER_FEATURE = '## v1.0.0\n\n### Feature\n\n  ### Internal\n\n- New --foo option.\n'


@pytest.mark.small
class DescribeGatedSectionContent:
    @pytest.mark.parametrize('section', ['Upgrade notes', 'Feature', 'Fix'])
    def it_rejects_a_paragraph_in_each_gated_section(self, section: str) -> None:
        problems = _problems_of(f'### {section}\n\nFixed a crash when the cache is read-only. (#1)\n')

        assert 'paragraph' in problems
        assert 'line 7' in problems
        assert f'"### {section}"' in problems

    @pytest.mark.parametrize(
        ('content', 'shape'),
        [
            ('\u2022 Fixed a crash. (#1)', 'pseudo-bullet'),
            ('  \u2022 Fixed a crash. (#1)', 'pseudo-bullet'),
            ('> - Fixed a crash. (#1)', 'blockquote'),
            ('>- Fixed a crash. (#1)', 'blockquote'),
            ('  > - Fixed a crash. (#1)', 'blockquote'),
            ('#### Detail', 'heading'),
            ('    ### Internal', 'heading'),
            ('\t### Internal', 'heading'),
            ('# Title', 'heading'),
            ('---', 'thematic break'),
            ('***', 'thematic break'),
            ('* * *', 'thematic break'),
            ('___', 'thematic break'),
            ('- - -', 'thematic break'),
            ('===', 'thematic break or setext underline'),
            ('--', 'thematic break or setext underline'),
            ('```\ncode\n```', 'code fence'),
            ('~~~\ncode\n~~~', 'code fence'),
            ('  ```shell', 'code fence'),
            ('<!-- note -->', 'HTML comment'),
            ('- Fixed `<!--` handling. (no docs: x)', 'HTML comment'),
            ('Fixed. <!--', 'HTML comment'),
        ],
    )
    def it_rejects_anything_in_a_gated_section_that_is_not_a_list_item(self, content: str, shape: str) -> None:
        problems = _problems_of(f'### Fix\n\n{content}\n')

        assert shape in problems

    def it_rejects_a_blockquoted_bullet_after_a_linked_bullet(self) -> None:
        problems = _problems_of(f'### Fix\n\n- **Fixed A.** {LINKED}\n> - **Fixed B.** (#2)\n')

        assert 'blockquote' in problems
        assert 'line 8' in problems

    def it_rejects_a_blockquote_nested_in_a_linked_bullet(self) -> None:
        problems = _problems_of(f'### Fix\n\n- **Fixed A.** {LINKED}\n  > - **Fixed B.** (#2)\n')

        assert 'blockquote' in problems

    def it_rejects_a_heading_nested_in_a_linked_bullet(self) -> None:
        problems = _problems_of(f'### Fix\n\n- **Fixed A.** {LINKED}\n    ### Internal\n')

        assert 'heading' in problems

    def it_rejects_an_indented_line_that_follows_a_blank_line(self) -> None:
        problems = _problems_of(f'### Fix\n\n- **Fixed A.** (#1)\n\n  {LINKED}\n')

        assert 'paragraph' in problems

    def it_rejects_text_that_follows_a_closing_comment(self) -> None:
        problems = _problems_of(f'### Fix\n\n- **Fixed A.** (#1)\n<!--\nnote\n--> {LINKED}\n')

        assert 'HTML comment' in problems
        assert 'paragraph' in problems

    def it_reads_a_list_with_blank_lines_between_bullets(self) -> None:
        assert (
            _problems_of(f'### Fix\n\n- **Fixed A.** {LINKED}\n\n- **Fixed B.** {LINKED}\n\n  - **C.** {LINKED}\n')
            == ''
        )


@pytest.mark.small
class DescribeExemptSectionContent:
    @pytest.mark.parametrize('section', ['Internal', 'Documentation'])
    @pytest.mark.parametrize(
        'content',
        [
            'Plain prose. <!-- a comment --> more prose.',
            '> quoted',
            '```shell\npytest --gremlins\n```',
            '~~~\n- a bullet-shaped line\n~~~',
            '<!--\nmulti-line\ncomment\n-->',
            '- Wrote a `<!-- x -->` example. (#1)',
        ],
    )
    def it_allows_prose_fences_and_comments_that_are_closed(self, section: str, content: str) -> None:
        assert _problems_of(f'### {section}\n\n{content}\n') == ''

    @pytest.mark.parametrize('section', ['Internal', 'Documentation'])
    def it_rejects_a_heading_other_than_a_known_section_heading(self, section: str) -> None:
        problems = _problems_of(f'### {section}\n\n#### Detail\n\n- Bumped. (#1)\n')

        assert f'{UNSUPPORTED_HEADING_AT} 7 (#### Detail);' in problems

    @pytest.mark.parametrize(
        ('opener', 'kind'),
        [('```shell', 'code fence'), ('~~~', 'code fence'), ('<!-- note', 'HTML comment')],
    )
    def it_reports_a_construct_that_is_never_closed(self, opener: str, kind: str) -> None:
        problems = _problems_of(f'### Internal\n\n{opener}\n\n### Fix\n\n- **Changed a thing.** (#3)\n')

        assert f'{kind} opened at line 7 is never closed' in problems

    @pytest.mark.parametrize('opener', ['```shell', '~~~', '<!-- note'])
    def it_still_gates_the_sections_after_a_construct_that_is_never_closed(self, opener: str) -> None:
        problems = _problems_of(f'### Internal\n\n{opener}\n\n### Fix\n\n- **Changed a thing.** (#3)\n')

        assert 'Changed a thing' in problems

    def it_does_not_let_an_unclosed_fence_swallow_the_next_entry(self) -> None:
        checker = _load_checker()
        changelog = '## v2.0.0\n\n### Internal\n\n```\n\n## v1.9.0\n\n### Fix\n\n- x\n'

        problems = checker.find_problems(changelog, '2.0.0', SITE)

        assert problems == ['code fence opened at line 5 is never closed']

    def it_reports_an_unclosed_fence_in_a_list_item_and_still_gates_the_next_bullet(self) -> None:
        body = (
            '### Fix\n\n- **Fixed `--gremlins`.** (no docs: restores it)\n'
            '  ```shell\n  pytest --gremlins\n- **Fixed a crash.** (#5)\n'
        )

        problems = _problems_of(body)

        assert 'code fence' in problems
        assert 'Fixed a crash' in problems


@pytest.mark.small
class DescribeConstructsThatHideHeadings:
    def it_reports_a_comment_opener_written_in_a_code_span_without_hiding_what_follows(self) -> None:
        body = (
            '**The HTML report no longer drops text after a `<!--` in a docstring.**\n\n'
            '### Fix\n\n- **Fixed a crash on Windows.** (#5)\n\n'
            '### Internal\n\n- Renamed the `opener --> closer` helper. (#6)\n'
        )

        problems = _problems_of(body)

        assert 'HTML comment opener inside a code span at line 5' in problems
        assert 'hides' not in problems

    def it_reports_a_code_span_comment_opener_in_an_exempt_section_without_hiding_a_gated_section(self) -> None:
        body = (
            '### Internal\n\n- Wrote `<!--` in a docstring.\n\n'
            '### Fix\n\n- **Fixed a crash on Windows.** (#5)\n\n'
            '### Documentation\n\n- Wrote `-->` in a docstring.\n'
        )

        problems = _problems_of(body)

        assert 'HTML comment opener inside a code span at line 7' in problems
        assert 'hides' not in problems

    def it_reports_a_fence_that_hides_a_gated_section(self) -> None:
        body = '### Internal\n\n- A step.\n```\n### Fix\n\n- **Fixed a crash on Windows.** (#5)\n\n```\n'

        problems = _problems_of(body)

        assert 'code fence opened at line 8 hides the "###" heading at line 9' in problems

    def it_reports_a_fence_line_inside_a_comment(self) -> None:
        body = '### Fix\n\n<!--\n```\n-->\n- **Fixed a crash.** (#1)\n<!--\n```\n-->\n'

        problems = _problems_of(body)

        assert 'Fixed a crash' in problems
        assert 'HTML comment' in problems

    def it_does_not_report_a_hash_line_in_a_fence_that_is_not_a_section_heading(self) -> None:
        assert _problems_of('### Internal\n\n```shell\n# install\n#### note\n```\n') == ''


@pytest.mark.small
class DescribeSectionHeadingSyntax:
    @pytest.mark.parametrize('heading', ['###\tFix', '### Fix ###'])
    def it_gates_the_bullets_under_a_tabbed_or_closed_gated_heading_after_internal(self, heading: str) -> None:
        body = f'### Internal\n\n- Bumped a dev dependency. (#1)\n\n{heading}\n\n- **Fixed a crash.** (#2)\n'

        problems = _problems_of(body)

        assert 'Fixed a crash' in problems

    @pytest.mark.parametrize('heading', ['### Internal ###', '### Internal #', '###\tInternal'])
    def it_accepts_an_internal_heading_written_with_extra_syntax(self, heading: str) -> None:
        assert _problems_of(f'{heading}\n\n- Bumped a dev dependency. (#1)\n') == ''

    @pytest.mark.parametrize('heading', ['### Fixes ###', '###', '### ###'])
    def it_names_an_unknown_heading_written_with_extra_syntax(self, heading: str) -> None:
        assert 'unknown section heading' in _problems_of(f'{heading}\n\n- x\n')

    @pytest.mark.parametrize(
        'heading', [' ### Fix', '  ### Feature', '   ### Upgrade notes', '\t### Fix', ' ### Fixes', '  ## Notes']
    )
    def it_rejects_an_indented_heading_and_says_to_start_it_at_column_0(self, heading: str) -> None:
        problems = _problems_of(f'### Internal\n\n- Bumped a dev dependency. (#1)\n\n{heading}\n\n- **Fixed.** (#2)\n')

        assert problems == f'{INDENTED_HEADING_AT} 9 ({heading.strip()}); {INDENTED_HEADING_FIX}'

    def it_keeps_the_section_of_the_heading_above_an_indented_known_heading(self) -> None:
        problems = _load_checker().find_problems(INDENTED_INTERNAL_UNDER_FEATURE, '1.0.0', SITE)

        assert problems == [
            f'{INDENTED_HEADING_AT} 5 (### Internal); {INDENTED_HEADING_FIX}',
            'bullet under "### Feature" at line 7 (New --foo option.) has no docs reference and no '
            '"(no docs: <reason>)" exemption',
        ]

    def it_still_reports_an_indented_heading_hidden_in_a_comment(self) -> None:
        problems = _problems_of('### Internal\n\n<!--\n  ### Fix\n-->\n')

        assert problems == 'HTML comment opened at line 7 hides the "###" heading at line 8'

    def it_does_not_report_a_heading_indented_four_columns_inside_a_fence(self) -> None:
        assert _problems_of('### Internal\n\n```text\n    ### Fix\n```\n') == ''

    def it_calls_a_heading_left_after_a_removed_comment_unsupported_not_indented(self) -> None:
        problems = _problems_of('### Internal\n\n<!-- x --> ### Fix\n')

        assert problems.startswith(f'{UNSUPPORTED_HEADING_AT} 7 (### Fix);')

    def it_rejects_an_indented_heading_on_a_bullet_continuation_line(self) -> None:
        problems = _problems_of('### Fix\n\n- **A.** (no docs: r)\n  ### Internal\n- **B.** (#2)\n')

        assert problems.splitlines() == [
            f'{INDENTED_HEADING_AT} 8 (### Internal); {INDENTED_HEADING_FIX}',
            'bullet under "### Fix" at line 9 (**B.** (#2)) has no docs reference and no "(no docs: <reason>)" '
            'exemption',
        ]

    def it_rejects_a_hash_start_that_is_not_a_known_section_heading(self) -> None:
        problems = _problems_of('### Fix\n\n- **Fixed #12.** (no docs: x)\n#hashtag\n')

        assert 'unknown section heading' not in problems
        assert f'{UNSUPPORTED_HEADING_AT} 8 (#hashtag);' in problems


@pytest.mark.small
class DescribeReferenceResolution:
    @pytest.mark.parametrize(
        'target',
        [
            f'{DOCS_URL}/guide/configuration/',
            f'{DOCS_URL}/guide/configuration/#batch-size',
            f'{DOCS_URL}/guide/configuration',
            'guide/configuration.md',
            'guide/configuration.md#caching',
            'guide/configuration/#caching',
            '/guide/configuration/',
        ],
    )
    def it_accepts_a_reference_to_an_existing_page_or_anchor(self, target: str) -> None:
        checker = _load_checker()

        assert checker.find_problems(_entry(f'- **Fixed it.** [docs]({target})'), '2.0.0', SITE) == []

    @pytest.mark.parametrize('target', ['.', 'index.md', './index.md', 'index.md#home', '/', DOCS_URL, f'{DOCS_URL}/'])
    def it_does_not_count_a_link_to_the_home_page_as_a_docs_reference(self, target: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry(f'- **Fixed it.** [docs]({target})'), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'no docs reference' in problems[0]

    def it_accepts_a_home_page_link_beside_a_real_reference(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [home](index.md) [docs]({DOCS_URL}/guide/configuration/)'

        assert checker.find_problems(_entry(bullet), '2.0.0', SITE) == []

    def it_accepts_an_exemption_beside_a_home_page_link(self) -> None:
        checker = _load_checker()

        assert checker.find_problems(_entry('- **Fixed it.** [home](index.md) (no docs: reason)'), '2.0.0', SITE) == []

    @pytest.mark.parametrize(
        ('target', 'reason'),
        [
            (f'{DOCS_URL}/guide/missing/', 'page'),
            ('guide/missing.md', 'page'),
            (f'{DOCS_URL}/guide/configuration/#no-such-anchor', 'anchor'),
            ('guide/configuration.md#No-Such-Anchor', 'anchor'),
            ('../outside.md', 'page'),
        ],
    )
    def it_names_a_reference_to_a_missing_page_or_anchor(self, target: str, reason: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(_entry(f'- **Fixed it.** [docs]({target})'), '2.0.0', SITE)

        assert len(problems) == 1
        assert target in problems[0]
        assert reason in problems[0]

    def it_checks_every_reference_on_a_bullet(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** [a]({DOCS_URL}/guide/configuration/) [b]({DOCS_URL}/guide/gone/)'

        problems = checker.find_problems(_entry(bullet), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'guide/gone' in problems[0]

    def it_checks_a_reference_beside_an_exemption(self) -> None:
        checker = _load_checker()
        bullet = f'- **Fixed it.** (no docs: reason) [b]({DOCS_URL}/guide/gone/)'

        problems = checker.find_problems(_entry(bullet), '2.0.0', SITE)

        assert len(problems) == 1
        assert 'guide/gone' in problems[0]


def _write_site(root: Path) -> Path:
    site = root / 'site'
    (site / 'guide' / 'configuration').mkdir(parents=True)
    (site / 'index.html').write_text('<html><body><h1 id="home">Home</h1></body></html>', encoding='utf-8')
    (site / 'guide' / 'configuration' / 'index.html').write_text(
        '<html><head><meta name="description" content="x"><meta name="viewport" content="y"></head>'
        '<body><input name="query"><h2 id="batch-size">Batch size</h2><a name="legacy-anchor"></a></body></html>',
        encoding='utf-8',
    )
    return site


@pytest.mark.medium
class DescribeBuiltSite:
    def it_reads_the_anchors_of_a_page(self, tmp_path: Path) -> None:
        checker = _load_checker()

        site = checker.BuiltSite(_write_site(tmp_path))

        assert site.anchors_of('guide/configuration') == {'batch-size', 'legacy-anchor'}

    def it_reads_the_home_page_as_the_empty_page_name(self, tmp_path: Path) -> None:
        checker = _load_checker()

        assert checker.BuiltSite(_write_site(tmp_path)).anchors_of('') == {'home'}

    def it_returns_none_for_a_page_that_was_not_built(self, tmp_path: Path) -> None:
        checker = _load_checker()

        assert checker.BuiltSite(_write_site(tmp_path)).anchors_of('guide/missing') is None

    def it_rejects_a_directory_that_is_not_a_built_site(self, tmp_path: Path) -> None:
        checker = _load_checker()

        with pytest.raises(checker.CannotCheckError, match=r'index\.html'):
            checker.BuiltSite(tmp_path)

    def it_rejects_a_directory_that_does_not_exist(self, tmp_path: Path) -> None:
        checker = _load_checker()

        with pytest.raises(checker.CannotCheckError, match='not a directory'):
            checker.BuiltSite(tmp_path / 'nope')


@pytest.mark.medium
class DescribeCommandLine:
    @staticmethod
    def _run(
        tmp_path: Path, changelog: str, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        changelog_path = tmp_path / 'CHANGELOG.md'
        changelog_path.write_text(changelog, encoding='utf-8')
        site = _write_site(tmp_path)
        return subprocess.run(
            [sys.executable, str(SCRIPT), '--site-dir', str(site), '--changelog', str(changelog_path), *args],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def it_exits_zero_when_the_entry_passes(self, tmp_path: Path) -> None:
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/#batch-size)'

        result = self._run(tmp_path, _entry(bullet), '2.0.0')

        assert result.returncode == 0, result.stderr

    def it_exits_one_and_names_the_bullet_when_the_check_fails(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, _entry('- **Changed a thing.** (#3)'), '2.0.0')

        assert result.returncode == 1
        assert 'PROBLEM: ' in result.stdout
        assert 'Changed a thing' in result.stdout

    def it_exits_one_and_names_the_link_when_an_anchor_is_missing(self, tmp_path: Path) -> None:
        bullet = f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/#gone)'

        result = self._run(tmp_path, _entry(bullet), '2.0.0')

        assert result.returncode == 1
        assert f'{DOCS_URL}/guide/configuration/#gone' in result.stdout

    def it_exits_one_when_the_entry_is_missing(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, _entry('- x [docs](index.md)'), '9.9.9')

        assert result.returncode == 1
        assert 'v9.9.9' in result.stdout

    def it_exits_two_when_the_site_is_missing(self, tmp_path: Path) -> None:
        changelog = tmp_path / 'CHANGELOG.md'
        changelog.write_text(_entry('- x'), encoding='utf-8')

        result = subprocess.run(
            [sys.executable, str(SCRIPT), '2.0.0', '--site-dir', str(tmp_path / 'nope'), '--changelog', str(changelog)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
        assert 'could not check' in result.stderr

    def it_exits_two_when_the_changelog_is_missing(self, tmp_path: Path) -> None:
        site = _write_site(tmp_path)

        result = subprocess.run(
            [sys.executable, str(SCRIPT), '2.0.0', '--site-dir', str(site), '--changelog', str(tmp_path / 'nope.md')],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
        assert 'could not check' in result.stderr

    NO_V_CHANGELOG = (
        '# Changelog\n\n## 2.0.0 (2026-11-01)\n\n### Fix\n\n{bullet}\n\n## v1.9.0 (2026-10-01)\n\n### Fix\n\n- x\n'
    )

    def it_checks_the_topmost_entry_in_newest_mode_even_without_a_v_prefix(self, tmp_path: Path) -> None:
        changelog = self.NO_V_CHANGELOG.format(bullet='- **Changed a thing.** (#3)')

        result = self._run(tmp_path, changelog, '--newest')

        assert result.returncode == 1
        assert 'Changed a thing' in result.stdout

    def it_passes_in_newest_mode_when_the_topmost_entry_passes(self, tmp_path: Path) -> None:
        changelog = self.NO_V_CHANGELOG.format(bullet=f'- **Fixed it.** [docs]({DOCS_URL}/guide/configuration/)')

        result = self._run(tmp_path, changelog, '--newest')

        assert result.returncode == 0, result.stderr
        assert '2.0.0' in result.stdout

    def it_ignores_a_version_heading_inside_a_fence_in_newest_mode(self, tmp_path: Path) -> None:
        changelog = '# Changelog\n\n```markdown\n## v9.9.9\n```\n\n' + self.NO_V_CHANGELOG.format(bullet='- x (#3)')

        result = self._run(tmp_path, changelog, '--newest')

        assert result.returncode == 1
        assert 'v9.9.9' not in result.stdout
        assert 'x (#3)' in result.stdout

    def it_exits_two_in_newest_mode_when_the_changelog_has_no_entry_at_all(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, '# Changelog\n\nNothing yet.\n', '--newest')

        assert result.returncode == 2
        assert 'no "## vX.Y.Z" entry' in result.stderr

    @pytest.mark.parametrize(
        'heading',
        [
            '## Unreleased',
            '## [2.0.0](https://example.com/compare) (2026-11-01)',
            '##  v2.0.0',
            '## V2.0.0',
            ' ## v2.0.0',
        ],
    )
    def it_exits_two_in_newest_mode_when_the_topmost_heading_is_not_a_version_entry(
        self, tmp_path: Path, heading: str
    ) -> None:
        changelog = (
            f'# Changelog\n\n{heading}\n\n### Fix\n\n- unlinked (#9)\n\n## v1.0.0\n\n### Fix\n\n- ok (no docs: r)\n'
        )

        result = self._run(tmp_path, changelog, '--newest')

        assert result.returncode == 2
        assert heading.strip() in result.stderr
        assert 'line 3' in result.stderr
        assert result.stdout == ''

    def it_exits_two_in_newest_mode_when_a_line_above_the_topmost_entry_is_too_long(self, tmp_path: Path) -> None:
        changelog = (
            '# Changelog\n\n## v2.0.0 ' + 'x' * 1000 + '\n\n### Fix\n\n- unlinked (#9)\n\n'
            '## v1.0.0\n\n### Fix\n\n- ok (no docs: r)\n'
        )

        result = self._run(tmp_path, changelog, '--newest')

        assert result.returncode == 2
        assert 'line 3 is longer than 1000 characters' in result.stderr

    def it_refuses_newest_mode_when_the_only_heading_is_too_long_to_read(self) -> None:
        checker = _load_checker()

        with pytest.raises(checker.CannotCheckError, match='line 3 is longer than 1000 characters'):
            checker.newest_version('# Changelog\n\n## v2.0.0 ' + 'x' * 1000 + '\n')

    @pytest.mark.parametrize('args', [['--newest', '2.0.0'], []])
    def it_exits_two_unless_exactly_one_of_the_version_and_newest_mode_is_given(
        self, tmp_path: Path, args: list[str]
    ) -> None:
        result = self._run(tmp_path, _entry('- x'), *args)

        assert result.returncode == 2
        assert 'exactly one' in result.stderr

    def it_exits_two_when_the_version_is_empty(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, _entry('- x'), 'v')

        assert result.returncode == 2
        assert 'the version is empty' in result.stderr

    def it_accepts_only_the_version_the_newest_mode_the_two_input_paths_and_the_notes_output(self) -> None:
        result = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True, check=False)

        flags = set(re.findall(r'--[a-z][a-z-]*', result.stdout.split('\n\n')[0]))

        assert flags == {'--site-dir', '--changelog', '--newest', '--notes-out'}

    @pytest.mark.parametrize('variable', ['SKIP_RELEASE_DOCS_CHECK', 'CI_SKIP_DOCS', 'FORCE', 'SKIP_DOCS_CHECK'])
    def it_ignores_environment_variables(self, tmp_path: Path, variable: str) -> None:
        env = {**os.environ, variable: '1'}

        result = self._run(tmp_path, _entry('- **Changed a thing.** (#3)'), '2.0.0', env=env)

        assert result.returncode == 1


def _jobs(workflow: str) -> dict[str, Any]:
    document = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding='utf-8'))
    jobs: dict[str, Any] = document['jobs']
    return jobs


def _steps(workflow: str, job_id: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _jobs(workflow)[job_id]['steps']
    return steps


def _step_index(workflow: str, job_id: str, command: str) -> int:
    matches = [i for i, step in enumerate(_steps(workflow, job_id)) if command in step.get('run', '')]
    assert len(matches) == 1, f'expected exactly one step running {command!r} in {workflow}:{job_id}'
    return matches[0]


def _ancestors(jobs: dict[str, Any], job_id: str) -> set[str]:
    needs = jobs[job_id].get('needs', [])
    direct = {needs} if isinstance(needs, str) else set(needs)
    return direct.union(*(_ancestors(jobs, parent) for parent in direct))


@pytest.mark.medium
class DescribeReleaseWorkflowGate:
    def it_runs_the_check_in_verify_tag_after_a_strict_docs_build(self) -> None:
        gate = _step_index('release.yml', 'verify-tag', GATE_COMMAND)
        build = _step_index('release.yml', 'verify-tag', 'mkdocs build --strict')

        assert build < gate

    def it_checks_the_tagged_commit_before_building_the_docs(self) -> None:
        checkout = _step_index('release.yml', 'verify-tag', 'git checkout --detach "refs/tags/$RELEASE_TAG"')
        build = _step_index('release.yml', 'verify-tag', 'mkdocs build --strict')

        assert checkout < build

    @pytest.mark.parametrize('command', [GATE_COMMAND, 'mkdocs build --strict'])
    def it_never_skips_or_tolerates_failure_of_a_gate_step(self, command: str) -> None:
        step = _steps('release.yml', 'verify-tag')[_step_index('release.yml', 'verify-tag', command)]

        assert 'if' not in step
        assert 'continue-on-error' not in step
        assert 'if' not in _jobs('release.yml')['verify-tag']
        assert 'continue-on-error' not in _jobs('release.yml')['verify-tag']

    def it_makes_every_other_job_depend_on_verify_tag(self) -> None:
        jobs = _jobs('release.yml')
        others = [job_id for job_id in jobs if job_id != 'verify-tag']

        assert all('verify-tag' in _ancestors(jobs, job_id) for job_id in others)

    @pytest.mark.parametrize('workflow', ['release.yml', 'cut-release.yml'])
    def it_has_no_input_that_mentions_the_docs_check(self, workflow: str) -> None:
        document = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding='utf-8'))
        inputs = document[True]['workflow_dispatch']['inputs']

        assert not [name for name in inputs if 'doc' in name.lower()]

    def it_does_not_pass_the_skip_test_pypi_input_to_the_check(self) -> None:
        step = _steps('release.yml', 'verify-tag')[_step_index('release.yml', 'verify-tag', GATE_COMMAND)]

        assert 'skip_test_pypi' not in str(step)


@pytest.mark.medium
class DescribeCutReleaseWorkflowGate:
    def it_runs_the_check_before_the_version_is_bumped(self) -> None:
        gate = _step_index('cut-release.yml', 'cut-release', GATE_COMMAND)
        bump = _step_index('cut-release.yml', 'cut-release', 'cz bump --yes')

        assert gate < bump

    def it_asks_commitizen_for_the_version_the_bump_will_produce(self) -> None:
        step = _steps('cut-release.yml', 'cut-release')[_step_index('cut-release.yml', 'cut-release', GATE_COMMAND)]

        assert 'cz bump --get-next' in step['run']

    def it_never_skips_or_tolerates_failure_of_the_check(self) -> None:
        step = _steps('cut-release.yml', 'cut-release')[_step_index('cut-release.yml', 'cut-release', GATE_COMMAND)]

        assert 'if' not in step
        assert 'continue-on-error' not in step


@pytest.mark.medium
class DescribePullRequestWorkflowGate:
    def it_runs_the_check_when_the_changelog_changes(self) -> None:
        step = _steps('ci.yml', 'docs')[_step_index('ci.yml', 'docs', GATE_COMMAND)]

        assert step['if'] == "needs.changes.outputs.changelog == 'true'"

    def it_checks_the_topmost_changelog_entry_against_a_strict_docs_build(self) -> None:
        gate = _step_index('ci.yml', 'docs', GATE_COMMAND)
        build = _step_index('ci.yml', 'docs', 'mkdocs build --strict')

        assert build < gate

    def it_does_not_tolerate_failure_of_the_check(self) -> None:
        step = _steps('ci.yml', 'docs')[_step_index('ci.yml', 'docs', GATE_COMMAND)]

        assert 'continue-on-error' not in step

    def it_selects_the_version_with_the_newest_mode_not_with_shell_text_processing(self) -> None:
        step = _steps('ci.yml', 'docs')[_step_index('ci.yml', 'docs', GATE_COMMAND)]

        assert '--newest' in step['run']
        assert 'sed' not in step['run']


LINKED_BULLET = '- **Fixed A.** [docs](guide/configuration.md#batch-size)'
UNLINKED_BULLET = '- **Fixed a crash on Windows.** (#5)'
LS = chr(0x2028)
PS = chr(0x2029)
OLDER_ENTRY = '\n## v1.0.0 (2026-01-01)\n\n### Fix\n\n- ok (no docs: r)\n'


def _v2_problems(entry_body: str) -> list[str]:
    checker = _load_checker()
    changelog = f'# Changelog\n\n## v2.0.0 (2026-11-01)\n\n{entry_body}\n{OLDER_ENTRY}'

    return cast('list[str]', checker.find_problems(changelog, '2.0.0', SITE))


@pytest.mark.small
class DescribeNonVersionLevelTwoHeadingInsideAnEntry:
    def it_reports_an_h2_that_would_hide_later_bullets_from_the_check(self) -> None:
        entry = f'## Highlights\n\n{LINKED_BULLET}\n\n### Fix\n\n{UNLINKED_BULLET}\n'

        problems = _v2_problems(entry)

        assert any('line 5' in problem and 'Highlights' in problem for problem in problems)

    def it_still_checks_the_bullets_that_follow_the_h2(self) -> None:
        entry = f'## Highlights\n\n### Fix\n\n{UNLINKED_BULLET}\n'

        problems = _v2_problems(entry)

        assert any('Fixed a crash on Windows' in problem for problem in problems)

    def it_reports_an_h2_inside_a_details_block(self) -> None:
        entry = (
            f'### Internal\n\n- Bumped. (#1)\n\n<details>\n## Full list\n</details>\n\n### Fix\n\n{UNLINKED_BULLET}\n'
        )

        problems = _v2_problems(entry)

        assert any('Full list' in problem for problem in problems)

    def it_reports_an_indented_version_heading_that_the_release_notes_do_not_stop_at(self) -> None:
        entry = f'### Fix\n\n{LINKED_BULLET}\n\n ## v1.9.9\n\n{UNLINKED_BULLET}\n'

        problems = _v2_problems(entry)

        assert any('v1.9.9' in problem for problem in problems)

    def it_ends_the_entry_at_the_next_version_heading(self) -> None:
        assert _v2_problems(f'### Fix\n\n{LINKED_BULLET}\n') == []


@pytest.mark.small
class DescribeUnicodeLineSeparators:
    @pytest.mark.parametrize(
        'separator', [LS, PS, '\x85', '\x0c', '\x0b', '\x1c', '\x1d', '\x1e'], ids=lambda c: f'U+{ord(c):04X}'
    )
    def it_does_not_see_a_section_heading_after_a_non_markdown_line_separator(self, separator: str) -> None:
        entry = f'### Fix\n\n{LINKED_BULLET}{separator}### Internal\n{UNLINKED_BULLET}\n'

        problems = _v2_problems(entry)

        assert any(f'U+{ord(separator):04X}' in problem and 'line 7' in problem for problem in problems)

    def it_still_gates_the_bullet_that_follows_the_separator(self) -> None:
        entry = f'### Fix\n\n{LINKED_BULLET}{LS}### Internal\n{UNLINKED_BULLET}\n'

        problems = _v2_problems(entry)

        assert any('Fixed a crash on Windows' in problem for problem in problems)

    @pytest.mark.parametrize('line_break', ['\r\n', '\r'])
    def it_keeps_line_numbers_correct_across_crlf_and_cr_line_endings(self, line_break: str) -> None:
        entry = f'### Fix{line_break}{line_break}{UNLINKED_BULLET}{line_break}'

        problems = _v2_problems(entry)

        assert any('line 7' in problem for problem in problems)

    def it_accepts_a_separator_in_an_exempt_section(self) -> None:
        entry = f'### Internal\n\n- Bumped{LS}a dependency. (#1)\n\n### Fix\n\n{LINKED_BULLET}\n'

        assert _v2_problems(entry) == []


@pytest.mark.small
class DescribeOneLineCommentBeforeAHeading:
    @pytest.mark.parametrize('line', ['<!-- old --> ### Internal', '<!-- old -->### Internal'])
    def it_reports_the_comment_and_does_not_switch_section(self, line: str) -> None:
        entry = f'### Fix\n\n{LINKED_BULLET}\n\n{line}\n\n{UNLINKED_BULLET}\n'

        problems = _v2_problems(entry)

        assert any('HTML comment at line 9' in problem for problem in problems)
        assert any('Fixed a crash on Windows' in problem for problem in problems)

    def it_does_not_end_the_entry_at_a_commented_version_heading(self) -> None:
        entry = f'### Fix\n\n{LINKED_BULLET}\n<!-- old --> ## v1.9.9\n{UNLINKED_BULLET}\n'

        problems = _v2_problems(entry)

        assert any('HTML comment at line 8' in problem for problem in problems)
        assert any('Fixed a crash on Windows' in problem for problem in problems)


LINK = '[docs](guide/configuration.md#batch-size)'
ENTRY_V2 = f'## v2.0.0 (2026-11-01)\n\n### Fix\n\n- A {LINK}\n'


REJECTED_HASH_LINES = [
    '# Feature',
    '#### Fix',
    '###Feature',
    '####Detail',
    '##v2.0.0',
    '#\tFeature',
    '#Feature ###',
    '###Feature ###',
    ' ##v2.0.0',
    '> #Feature',
    '>- #Feature',
    '> > #Feature',
    '- #### Detail',
    '1. #### Detail',
    '  - ###Feature',
]
REJECTED_DELIMITER_LINES = [
    '=',
    '===',
    '= =',
    '-',
    '--',
    '---',
    '***',
    '___',
    '* * *',
    '- - -',
    '   ---',
    '> ---',
    '> ===',
    '- ---',
    '1. ---',
    '  ---',
]
REJECTED_DELIMITERS_UNDER_CONTENT = [
    'A | B\n---',
    'A | B\n===',
    '<em>Feature</em>\n---',
    '<em>Feature</em> | x\n===',
    '> A | B\n> ---',
    '> <em>Feature</em>\n> ---',
    'Feature\n\n=======',
    'Highlights\n\n---',
]


UNSUPPORTED_HEADING_AT = 'a heading that is not a known "###" section heading or version heading at line'
SECTIONS_WITH_A_LINE_BEFORE = [('', 5), ('Internal', 9), ('Documentation', 9), ('Fix', 9)]


def _section_body(section: str, content: str, *, before: str | None = None) -> str:
    """Return ``content`` in ``section``, or in the preamble with a linked ``### Fix`` section after it."""
    if not section:
        return f'{content}\n\n### Fix\n\n{LINKED_BULLET}\n'
    prefix = f'{before}\n\n' if before else ''
    return f'### {section}\n\n{prefix}{content}\n'


@pytest.mark.small
class DescribeStrictEntryFormat:
    @pytest.mark.parametrize(('section', 'number'), SECTIONS_WITH_A_LINE_BEFORE)
    @pytest.mark.parametrize('line', REJECTED_HASH_LINES)
    def it_rejects_an_unsupported_hash_start_in_every_section(self, section: str, number: int, line: str) -> None:
        body = _section_body(section, line, before='- **Bumped.** (no docs: x)')

        problems = _problems_of(body)

        assert f'{UNSUPPORTED_HEADING_AT} {number} ({line.strip()});' in problems

    @pytest.mark.parametrize(('section', 'number'), SECTIONS_WITH_A_LINE_BEFORE)
    @pytest.mark.parametrize('line', REJECTED_DELIMITER_LINES)
    def it_rejects_a_thematic_break_or_setext_underline_in_every_section(
        self, section: str, number: int, line: str
    ) -> None:
        body = _section_body(section, line, before=LINKED_BULLET)

        problems = _problems_of(body)

        assert f'a thematic break or setext underline at line {number} ({line.strip()});' in problems

    def it_reads_a_long_run_of_spaces_after_an_equals_sign_in_linear_time(self) -> None:
        delimiter = _load_checker().THEMATIC_OR_SETEXT
        started = time.perf_counter()

        matched = delimiter.match('=' + ' ' * 40000 + 'x')

        assert matched is None
        assert time.perf_counter() - started < LINEAR_TIME_BUDGET_SECONDS

    @pytest.mark.parametrize(
        ('line', 'expected'),
        [
            (
                '#Feature',
                'a heading that is not a known "###" section heading or version heading at line 7 (#Feature); use one '
                'of the five "###" section names, or keep an issue-number line directly under its bullet with no blank '
                'line, or escape it as "\\#720)"',
            ),
            ('<h1>Feature</h1>', 'a raw HTML heading at line 7 (<h1>Feature</h1>); use a known "###" section heading'),
            (
                '<div>',
                'a raw HTML block tag at line 7 (<div>); move the tag into the middle of a sentence or write it as a '
                'code span',
            ),
            ('---', 'a thematic break or setext underline at line 7 (---); remove the line or write it as a code span'),
        ],
    )
    def it_tells_the_author_how_to_fix_a_rejected_shape(self, line: str, expected: str) -> None:
        assert _problems_of(f'### Internal\n\n{line}\n') == expected

    def it_rejects_a_line_longer_than_1000_characters_without_reading_it(self) -> None:
        long_line = '- ' + 'a`' * 499 + 'a'

        assert _problems_of(f'### Internal\n\n{long_line}\n') == 'line 7 is longer than 1000 characters'

    def it_reports_only_the_length_of_a_long_gated_bullet(self) -> None:
        assert _problems_of('### Fix\n\n- ' + 'x' * 999 + '\n') == 'line 7 is longer than 1000 characters'

    def it_accepts_a_line_of_exactly_1000_characters(self) -> None:
        line = '- ' + 'a`' * 498 + 'aa'

        assert _problems_of(f'### Internal\n\n{line}\n') == ''

    def it_rejects_a_long_line_inside_a_fence(self) -> None:
        problems = _problems_of('### Internal\n\n```\n' + 'x' * 1001 + '\n```\n')

        assert problems == 'line 8 is longer than 1000 characters'

    @pytest.mark.parametrize('content', ['A | B\n---|---\n1 | 2', 'prose -- with --- dashes', '= x', '-- x', '*-*x'])
    def it_accepts_delimiter_characters_that_do_not_make_a_whole_delimiter_line(self, content: str) -> None:
        assert _problems_of(f'### Internal\n\n{content}\n') == ''

    @pytest.mark.parametrize(('section', 'first_line'), [('', 5), ('Internal', 7), ('Documentation', 7), ('Fix', 7)])
    @pytest.mark.parametrize('content', REJECTED_DELIMITERS_UNDER_CONTENT)
    def it_rejects_a_delimiter_after_pipe_or_inline_html_content(
        self, section: str, first_line: int, content: str
    ) -> None:
        delimiter_line = first_line + content.count('\n')

        problems = _problems_of(_section_body(section, content))

        assert f'a thematic break or setext underline at line {delimiter_line} (' in problems

    @pytest.mark.parametrize(
        ('fence', 'opener'),
        [('> ```\n> code\n> ```', '> ```'), ('- ```\n  code\n  ```', '- ```'), ('1. ~~~\n   code\n   ~~~', '1. ~~~')],
    )
    def it_reports_a_fence_inside_a_container_as_unsupported(self, fence: str, opener: str) -> None:
        problems = _problems_of(f'### Internal\n\n{fence}\n\n### Fix\n\n{LINKED_BULLET}\n')

        assert (
            f'a code fence opened inside a list item or block quote at line 7 ({opener}) is unsupported; start the '
            'fence at the outer level'
        ) in problems

    def it_does_not_let_a_container_fence_swallow_the_gated_section(self) -> None:
        body = '### Internal\n\n> ```\n> #Feature\n\n### Fix\n\n- **Changed a thing.** (#3)\n'

        problems = _problems_of(body)

        assert (
            'bullet under "### Fix" at line 12 (**Changed a thing.** (#3)) has no docs reference and no '
            '"(no docs: <reason>)" exemption'
        ) in problems
        assert 'is unsupported' in problems

    @pytest.mark.parametrize(
        'literal',
        [
            '````markdown\n> ```\n> example\n> ```\n````',
            '````markdown\n> ```\n````',
            '~~~markdown\n- ```\n  example\n  ```\n~~~',
            '<!--\n> ```\n> text\n> ```\n-->',
            '<!--\n> ```\n-->',
            '```\n<!--\n> ```\n-->\n```',
        ],
    )
    def it_keeps_literal_container_fence_text_inside_an_outer_fence_or_comment(self, literal: str) -> None:
        assert _problems_of(f'### Internal\n\n{literal}\n\n### Fix\n\n{LINKED_BULLET}\n') == ''

    def it_still_reports_a_container_fence_after_an_outer_fence_closes(self) -> None:
        body = f'### Internal\n\n````\n> ```\n````\n\n> ```\n> code\n> ```\n\n### Fix\n\n{LINKED_BULLET}\n'

        assert _problems_of(body) == (
            'a code fence opened inside a list item or block quote at line 11 (> ```) is unsupported; start the fence '
            'at the outer level'
        )

    def it_still_reports_a_container_fence_after_an_outer_comment_closes(self) -> None:
        body = f'### Internal\n\n<!--\n> ```\n-->\n\n- ```\n  code\n  ```\n\n### Fix\n\n{LINKED_BULLET}\n'

        assert _problems_of(body) == (
            'a code fence opened inside a list item or block quote at line 11 (- ```) is unsupported; start the fence '
            'at the outer level'
        )

    @pytest.mark.parametrize('section', ['', 'Internal', 'Documentation', 'Fix'])
    @pytest.mark.parametrize(
        'line',
        [
            '<h1>Feature</h1>',
            '<h6>Detail</h6>',
            '<H2 class="x">Feature</H2>',
            '<h3 id="anchor">Feature</h3>',
            '> <h1>Feature</h1>',
            '- <h4>Detail</h4>',
            '1. <h5>Detail</h5>',
        ],
    )
    def it_rejects_a_raw_html_heading_in_every_section(self, section: str, line: str) -> None:
        problems = _problems_of(_section_body(section, line, before='- **Bumped.** (no docs: x)'))

        assert 'raw HTML heading' in problems

    def it_keeps_a_raw_html_tag_that_is_a_code_span(self) -> None:
        assert _problems_of('### Internal\n\n- Wrote `<h1>Feature</h1>` in a docstring. (#1)\n') == ''

    @pytest.mark.parametrize('line', ['    #720)', '  #720)', '\t#720)', '      #709, #714)'])
    def it_rejects_a_standalone_issue_number_line(self, line: str) -> None:
        problems = _problems_of(f'### Internal\n\nParagraph before it.\n\n{line}\n')

        assert f'{UNSUPPORTED_HEADING_AT} 9 ({line.strip()});' in problems

    def it_does_not_read_an_issue_number_as_a_continuation_after_a_blank_line(self) -> None:
        problems = _problems_of('### Internal\n\n- **Bumped.** (no docs: x)\n\n  #716)\n')

        assert f'{UNSUPPORTED_HEADING_AT} 9 (#716));' in problems

    @pytest.mark.parametrize(
        'continuation',
        ['- **A.** (#598,\n  #716)', '- **A.** (#701,\n  #709, #714)', '  - **Nested.** (#1,\n    #2)'],
    )
    def it_keeps_a_wrapped_bullet_reference(self, continuation: str) -> None:
        assert _problems_of(f'### Internal\n\n{continuation}\n') == ''

    @pytest.mark.parametrize(
        'content',
        [
            'Plain prose about the release.',
            '```shell\n# Feature\n---\n#### Detail\n```',
            '~~~markdown\n##v2.0.0\n~~~',
            '<!--\n# Feature\n---\n-->',
            '- **Fixed it.** [docs](guide/configuration.md#batch-size)',
            '- **Fixed it.** (no docs: restores documented behavior)\n  #716)',
            '- a wrapped reference. (#598,\n  #716)',
            '- **Bumped.** (no docs: x)\n  - **Nested.** (no docs: x)',
        ],
    )
    def it_accepts_prose_closed_fences_and_comments_and_wrapped_bullets(self, content: str) -> None:
        assert _problems_of(f'### Internal\n\n{content}\n') == ''

    @pytest.mark.parametrize('heading', ['### Fix', '###\tDocumentation', '### Feature ###'])
    def it_keeps_accepting_the_known_section_headings(self, heading: str) -> None:
        assert _problems_of(f'{heading}\n\n- **Bumped.** (no docs: x)\n') == ''


NOTES_V2 = f'{ENTRY_V2}\n'
UNLINKED = '- **Fixed a crash on Windows.** (#5)'
OLDER = '\n## v1.0.0 (2026-01-01)\n\n### Fix\n\n- ok (no docs: r)\n'
CHANGELOG_V2 = f'# Changelog\n\n{ENTRY_V2}{OLDER}'
HIDDEN_COPY_ABOVE = {
    'html comment': f'# Changelog\n\n<!--\n## v2.0.0\n\n### Fix\n\n{UNLINKED}\n-->\n\n{ENTRY_V2}{OLDER}',
    'code fence': f'# Changelog\n\n```\n## v2.0.0\n\n### Fix\n\n{UNLINKED}\n```\n\n{ENTRY_V2}{OLDER}',
}
NON_ASCII_DIGIT_HEADINGS = {
    'arabic-indic': f'## v{chr(0x0661)} highlights',
    'fullwidth': f'## {chr(0xFF12)}{chr(0xFF10)}{chr(0xFF12)}{chr(0xFF16)} roadmap',
}


def _run_gate_on_bytes(
    tmp_path: Path, changelog: bytes, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    changelog_path = tmp_path / 'CHANGELOG.md'
    changelog_path.write_bytes(changelog)
    site = _write_site(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT), '--site-dir', str(site), '--changelog', str(changelog_path), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        env=env,
    )


@pytest.mark.medium
class DescribeNotesOut:
    @pytest.mark.parametrize(
        ('content', 'expected'),
        [
            ('#Feature', f'{UNSUPPORTED_HEADING_AT} 9 (#Feature);'),
            ('#### Fix', f'{UNSUPPORTED_HEADING_AT} 9 (#### Fix);'),
            ('###Feature', f'{UNSUPPORTED_HEADING_AT} 9 (###Feature);'),
            ('A | B\n---', 'a thematic break or setext underline at line 10 (---);'),
            ('<em>Feature</em>\n---', 'a thematic break or setext underline at line 10 (---);'),
            ('> #Feature', f'{UNSUPPORTED_HEADING_AT} 9 (> #Feature);'),
            ('> <em>Feature</em>\n> ---', 'a thematic break or setext underline at line 10 (> ---);'),
            ('---', 'a thematic break or setext underline at line 9 (---);'),
        ],
    )
    def it_fails_the_cli_and_writes_no_notes_for_an_unsupported_shape(
        self, tmp_path: Path, content: str, expected: str
    ) -> None:
        notes = tmp_path / 'notes.md'
        changelog = f'# Changelog\n\n## v2.0.0 (2026-11-01)\n\n### Internal\n\n- Bumped. (#1)\n\n{content}\n\n{OLDER}'

        result = _run_gate_on_bytes(tmp_path, changelog.encode(), '2.0.0', '--notes-out', str(notes))

        assert result.returncode == 1, result.stdout
        assert expected in result.stdout
        assert not notes.exists()

    def it_fails_the_cli_for_a_second_visible_copy_and_writes_no_notes(self, tmp_path: Path) -> None:
        notes = tmp_path / 'notes.md'
        changelog = f'# Changelog\n\n{ENTRY_V2}\n##v2.0.0\n\n### Fix\n\n{UNLINKED}\n\n{OLDER}'

        result = _run_gate_on_bytes(tmp_path, changelog.encode(), '2.0.0', '--notes-out', str(notes))

        assert result.returncode == 1, result.stdout
        assert 'second visible copy' in result.stdout
        assert not notes.exists()

    def it_writes_the_entry_that_passed_the_check(self, tmp_path: Path) -> None:
        notes = tmp_path / 'notes.md'

        result = _run_gate_on_bytes(tmp_path, CHANGELOG_V2.encode(), '2.0.0', '--notes-out', str(notes))

        assert result.returncode == 0, result.stdout
        assert notes.read_bytes() == NOTES_V2.encode()

    def it_keeps_crlf_line_endings_in_the_notes(self, tmp_path: Path) -> None:
        notes = tmp_path / 'notes.md'
        changelog = CHANGELOG_V2.replace('\n', '\r\n').encode()

        result = _run_gate_on_bytes(tmp_path, changelog, '2.0.0', '--notes-out', str(notes))

        assert result.returncode == 0, result.stdout
        assert notes.read_bytes() == NOTES_V2.replace('\n', '\r\n').encode()

    def it_writes_the_entry_up_to_the_end_of_the_file_for_the_oldest_entry(self, tmp_path: Path) -> None:
        notes = tmp_path / 'notes.md'

        result = _run_gate_on_bytes(tmp_path, CHANGELOG_V2.encode(), '1.0.0', '--notes-out', str(notes))

        assert result.returncode == 0, result.stdout
        assert notes.read_text(encoding='utf-8') == OLDER.lstrip('\n')

    def it_writes_the_newest_entry_in_newest_mode(self, tmp_path: Path) -> None:
        notes = tmp_path / 'notes.md'

        result = _run_gate_on_bytes(tmp_path, CHANGELOG_V2.encode(), '--newest', '--notes-out', str(notes))

        assert result.returncode == 0, result.stdout
        assert notes.read_bytes() == NOTES_V2.encode()

    def it_writes_nothing_when_the_check_fails(self, tmp_path: Path) -> None:
        notes = tmp_path / 'notes.md'
        changelog = CHANGELOG_V2.replace(LINK, '(#3)')

        result = _run_gate_on_bytes(tmp_path, changelog.encode(), '2.0.0', '--notes-out', str(notes))

        assert result.returncode == 1
        assert not notes.exists()

    def it_writes_nothing_when_the_check_could_not_run(self, tmp_path: Path) -> None:
        notes = tmp_path / 'notes.md'

        result = _run_gate_on_bytes(tmp_path, CHANGELOG_V2.encode(), '--newest', '2.0.0', '--notes-out', str(notes))

        assert result.returncode == 2
        assert not notes.exists()

    def it_replaces_notes_left_by_an_earlier_run_when_the_check_fails(self, tmp_path: Path) -> None:
        notes = tmp_path / 'notes.md'
        notes.write_text('stale', encoding='utf-8')
        changelog = CHANGELOG_V2.replace(LINK, '(#3)')

        _run_gate_on_bytes(tmp_path, changelog.encode(), '2.0.0', '--notes-out', str(notes))

        assert not notes.exists()


@pytest.mark.medium
class DescribeInputsThatMadeTheReleaseNotesDifferFromTheCheckedEntry:
    @pytest.mark.parametrize('changelog', HIDDEN_COPY_ABOVE.values(), ids=HIDDEN_COPY_ABOVE.keys())
    def it_fails_a_hidden_copy_of_the_version_heading(self, tmp_path: Path, changelog: str) -> None:
        notes = tmp_path / 'notes.md'

        result = _run_gate_on_bytes(tmp_path, changelog.encode(), '2.0.0', '--notes-out', str(notes))

        assert result.returncode == 1
        assert 'line 4' in result.stdout
        assert not notes.exists()

    def it_fails_a_lone_carriage_return_before_a_version_heading(self, tmp_path: Path) -> None:
        changelog = f'# Changelog\n\n{ENTRY_V2.rstrip()}\r## v1.9.9\r\r### Fix\r\r{UNLINKED}\n{OLDER}'

        result = _run_gate_on_bytes(tmp_path, changelog.encode(), '2.0.0')

        assert result.returncode == 1
        assert 'carriage return' in result.stdout

    @pytest.mark.parametrize('heading', NON_ASCII_DIGIT_HEADINGS.values(), ids=NON_ASCII_DIGIT_HEADINGS.keys())
    def it_reports_a_level_two_heading_that_starts_with_a_non_ascii_digit(self, tmp_path: Path, heading: str) -> None:
        changelog = f'# Changelog\n\n{ENTRY_V2}\n{heading}\n\n### Fix\n\n{UNLINKED}\n{OLDER}'

        result = _run_gate_on_bytes(tmp_path, changelog.encode(), '2.0.0')

        assert result.returncode == 1
        assert 'line 9' in result.stdout

    def it_prints_a_problem_with_non_ascii_text_when_stdout_is_cp1252(self, tmp_path: Path) -> None:
        heading = NON_ASCII_DIGIT_HEADINGS['arabic-indic']
        changelog = f'# Changelog\n\n{ENTRY_V2}\n{heading}\n\n### Fix\n\n{UNLINKED}\n{OLDER}'
        env = {**os.environ, 'PYTHONIOENCODING': 'cp1252'}

        result = _run_gate_on_bytes(tmp_path, changelog.encode(), '2.0.0', env=env)

        assert result.returncode == 1, result.stderr
        assert 'PROBLEM: ' in result.stdout


@pytest.mark.medium
class DescribeStderrAfterTheUtf8Reconfigure:
    @pytest.mark.skipif(sys.platform == 'win32', reason='argv bytes that are not UTF-8 exist only on POSIX')
    def it_exits_2_when_the_could_not_check_reason_has_a_path_that_is_not_utf8(self, tmp_path: Path) -> None:
        site = _write_site(tmp_path)
        changelog = os.fsencode(tmp_path) + b'/missing-\xff.md'
        command = [os.fsencode(sys.executable), os.fsencode(SCRIPT), b'2.0.0', b'--site-dir', os.fsencode(site)]

        result = subprocess.run([*command, b'--changelog', changelog], capture_output=True, check=False)

        assert result.returncode == 2, result.stderr
        assert b'could not check the release docs' in result.stderr


@pytest.mark.small
class DescribeHiddenCopyOfTheVersionHeading:
    @pytest.mark.parametrize('changelog', HIDDEN_COPY_ABOVE.values(), ids=HIDDEN_COPY_ABOVE.keys())
    def it_names_the_region_and_the_line_of_the_hidden_copy(self, changelog: str) -> None:
        checker = _load_checker()

        problems = checker.find_problems(changelog, '2.0.0', SITE)

        assert any('hides a copy of the "## v2.0.0" heading at line 4' in problem for problem in problems)

    def it_ignores_a_hidden_heading_of_another_version(self) -> None:
        checker = _load_checker()
        changelog = f'# Changelog\n\n```\n## v1.5.0\n```\n\n{ENTRY_V2}{OLDER}'

        assert checker.find_problems(changelog, '2.0.0', SITE) == []


DUPLICATE_VERSION_COPIES = {
    'dated': '## v2.0.0 (2026-11-02)',
    'without v': '## 2.0.0 (2026-11-02)',
    'closing hashes': '## v2.0.0 ##',
    'no space': '##v2.0.0',
    'indented': '  ## v2.0.0',
    'quoted': '> ## v2.0.0',
    'listed': '- ## v2.0.0',
}


@pytest.mark.small
class DescribeVisibleDuplicateOfTheVersionEntry:
    @pytest.mark.parametrize('copy', DUPLICATE_VERSION_COPIES.values(), ids=DUPLICATE_VERSION_COPIES.keys())
    def it_reports_a_second_visible_copy_of_the_version_heading(self, copy: str) -> None:
        changelog = f'# Changelog\n\n{ENTRY_V2}\n{copy}\n\n### Fix\n\n{UNLINKED}\n\n{OLDER}'

        problems = _load_checker().find_problems(changelog, '2.0.0', SITE)

        expected = 'second visible copy of the entry version heading is at line 9'
        assert any(expected in problem for problem in problems), problems

    def it_keeps_publishing_only_the_first_entry(self) -> None:
        checker = _load_checker()
        changelog = f'# Changelog\n\n{ENTRY_V2}\n## v2.0.0 (2026-11-02)\n\n### Fix\n\n{UNLINKED}\n\n{OLDER}'

        assert checker.release_notes(changelog, '2.0.0') == NOTES_V2

    def it_does_not_report_the_next_distinct_version(self) -> None:
        checker = _load_checker()
        changelog = f'# Changelog\n\n{ENTRY_V2}\n## v1.9.0 (2026-10-01)\n\n### Fix\n\n{UNLINKED}\n'

        assert checker.find_problems(changelog, '2.0.0', SITE) == []

    @pytest.mark.parametrize('near_miss', ['## v2.0.0rc1', '## v2.0.01', '## v2.0.0.1', '### v2.0.0'])
    def it_does_not_read_a_near_miss_as_a_copy_of_the_version_heading(self, near_miss: str) -> None:
        changelog = f'# Changelog\n\n{ENTRY_V2}\n{near_miss}\n\n{OLDER}'

        problems = '\n'.join(_load_checker().find_problems(changelog, '2.0.0', SITE))

        assert 'second visible copy' not in problems


@pytest.mark.small
class DescribeEscapedBacktickBeforeCode:
    """A backslash-escaped backtick is literal text, so it opens no code span and hides nothing."""

    def it_reports_a_raw_heading_after_an_escaped_backtick(self) -> None:
        problems = _problems_of('### Internal\n\n- Bump \\`<h2>Feature</h2>`\n')

        assert 'a raw HTML heading' in problems
        assert 'at line 7' in problems

    def it_still_ignores_a_raw_heading_inside_a_real_code_span(self) -> None:
        assert _problems_of('### Internal\n\n- Bump `<h2>Feature</h2>`\n') == ''

    def it_does_not_let_an_escaped_backtick_hide_a_link_from_a_gated_bullet(self) -> None:
        problems = _problems_of(f'### Fix\n\n- Fixed \\`a [docs]({DOCS_URL}/guide/configuration/) b\\`.\n')

        assert problems == ''


@pytest.mark.small
class DescribeCommentOpenerInsideACodeSpan:
    """A ``<!--`` written as a code span is literal text, so it opens no comment and hides nothing."""

    @pytest.mark.parametrize('span', ['`<!--`', '``a <!-- b``'])
    def it_reports_a_heading_after_a_code_span_comment_opener(self, span: str) -> None:
        problems = _problems_of(f'### Internal\n\n- Use {span} here.\n\n# Feature\n\n- Undocumented. (#1)\n\n-->\n')

        assert 'a heading that is not a known "###" section heading or version heading at line 9' in problems

    def it_reports_a_code_span_comment_opener_in_a_gated_bullet_as_unsupported_not_as_a_comment(self) -> None:
        problems = _problems_of('### Fix\n\n- Fixed `<!--` parsing. (no docs: fixes a crash)\n')

        assert 'HTML comment opener inside a code span at line 7' in problems
        assert 'remove it' not in problems

    def it_still_hides_a_real_comment_that_follows_a_code_span(self) -> None:
        problems = _problems_of('### Fix\n\n- Fixed `x`. <!-- note --> (no docs: fixes a crash)\n')

        assert 'HTML comment at line 7' in problems


@pytest.mark.small
class DescribeCommentOpenedMidLine:
    """Only a ``<!--`` that starts its line, after at most 3 spaces, hides the lines after it; any other must close."""

    def it_reports_a_mid_line_comment_that_does_not_close_on_its_line(self) -> None:
        problems = _problems_of('### Internal\n\n- Bump <!-- x\n\n# Feature\n\n- Undocumented. (#1)\n\n-->\n')

        assert _inline_opener_problem(7, '- Bump <!-- x') in problems

    def it_reads_the_lines_after_a_blank_line_that_ends_a_mid_line_comment_as_visible(self) -> None:
        problems = _problems_of('### Internal\n\n- Bump <!-- x\n\n# Feature\n\n- Undocumented. (#1)\n\n-->\n')

        assert 'a heading that is not a known "###" section heading or version heading at line 9' in problems

    def it_accepts_a_comment_that_starts_a_line_and_spans_a_blank_line(self) -> None:
        assert _problems_of('### Internal\n\n<!--\nnote\n\nmore\n-->\n\n- x\n') == ''

    def it_rejects_a_mid_line_comment_that_closes_on_a_later_line(self) -> None:
        assert _problems_of('### Internal\n\n- Bump <!-- x\n  y --> done.\n') == _inline_opener_problem(
            7, '- Bump <!-- x'
        )

    def it_accepts_a_mid_line_comment_that_closes_on_its_line(self) -> None:
        assert _problems_of('### Internal\n\n- Bump <!-- x --> done.\n') == ''

    @pytest.mark.parametrize('opener', ['<!-- x', '   <!-- x', '- a\n  <!-- x', '> a\n<!-- x'])
    def it_hides_the_lines_after_a_comment_that_starts_its_line(self, opener: str) -> None:
        assert _problems_of(f'### Internal\n\n{opener}\n# Hidden\n-->\n') == ''

    def it_rejects_a_comment_opened_after_a_comment_that_starts_the_line(self) -> None:
        problems = _problems_of(f'### Internal\n\n{TAIL_COMMENT_OPENER}\n-->\n')

        assert _inline_opener_problem(7, TAIL_COMMENT_OPENER) in problems


def _inline_opener_problem(line: int, text: str) -> str:
    return (
        f'HTML comment at line {line} ({text}) does not close on its line and does not start it, so the docs renderer '
        'does not hide the lines after it; close it on the same line, or start the line with it, indented by at most '
        '3 spaces'
    )


@pytest.mark.small
class DescribeCommentTheRendererDoesNotOpen:
    def it_reports_a_quoted_comment_opener_and_the_section_heading_it_no_longer_hides(self) -> None:
        changelog = (
            '## v1.0.0\n\n> <!-- note\n> ### Feature\n> - New --foo option.\n-->\n\n### Fix\n\n- a (no docs: r)\n'
        )

        assert _load_checker().find_problems(changelog, '1.0.0', SITE) == [
            'a raw HTML block tag at line 3 (> <!-- note); move the tag into the middle of a sentence or write it as a '
            'code span',
            'a heading that is not a known "###" section heading or version heading at line 4 (> ### Feature); use one '
            'of the five "###" section names, or keep an issue-number line directly under its bullet with no blank '
            'line, or escape it as "\\#720)"',
            _inline_opener_problem(3, '> <!-- note'),
        ]

    @pytest.mark.parametrize('opener', ['\\<!-- x', '\\\\<!-- x', '    <!-- x', '\t<!-- x', '> > <!-- x', '1. <!-- x'])
    def it_reports_an_opener_the_renderer_reads_as_text_or_inline_html(self, opener: str) -> None:
        problems = _problems_of(f'### Internal\n\n{opener}\n-->\n')

        assert _inline_opener_problem(7, opener.strip()) in problems

    def it_ends_the_entry_at_a_version_heading_an_escaped_opener_no_longer_hides(self) -> None:
        problems = _problems_of('### Internal\n\n\\<!-- x\n## v0.9.9 (2020-01-01)\n-->\n\n### Fix\n\n- a (#1)\n')

        assert problems == _inline_opener_problem(7, '\\<!-- x')

    def it_reports_a_comment_closed_by_a_bang_closer_on_its_opening_line(self) -> None:
        problems = _problems_of('### Internal\n\n<!-- a --!>\n# Big\n-->\n')

        assert problems.splitlines() == [
            'a raw HTML block tag at line 7 (<!-- a --!>); move the tag into the middle of a sentence or write it as a '
            'code span',
            'a heading that is not a known "###" section heading or version heading at line 8 (# Big); use one of the '
            'five "###" section names, or keep an issue-number line directly under its bullet with no blank line, or '
            'escape it as "\\#720)"',
            'HTML comment opened at line 7 meets "--!>" at line 7 before its "-->"; the docs renderer then opens no '
            'comment and shows the lines after it. Remove the "--!>"',
        ]

    def it_reports_a_bang_closer_on_a_later_line_of_the_comment(self) -> None:
        problems = _problems_of('### Internal\n\n<!-- a\nb --!>\nc -->\n')

        assert (
            'HTML comment opened at line 7 meets "--!>" at line 8 before its "-->"; the docs renderer then opens no '
            'comment and shows the lines after it. Remove the "--!>"'
        ) in problems

    def it_accepts_a_bang_closer_after_the_closer_of_a_comment(self) -> None:
        assert _problems_of('### Internal\n\n<!-- a\nb --> c --!>\n') == ''

    @pytest.mark.parametrize('line', ['x <a', 'x <a title="', 'x </a', '- `<a`'])
    def it_reports_a_tag_that_does_not_end_on_its_line(self, line: str) -> None:
        problems = _problems_of(f'### Internal\n\n{line}\n')

        assert problems == (
            f'an HTML tag at line 7 ({line}) does not end on its line; the docs renderer reads the lines after it as '
            'part of the tag, so end it with ">" on the same line'
        )

    @pytest.mark.parametrize('line', ['x <a> y', 'a < b', 'x <https://example.com>', 'x `<a>` y'])
    def it_accepts_a_tag_that_ends_on_its_line_and_a_bare_angle_bracket(self, line: str) -> None:
        assert _problems_of(f'### Internal\n\n{line}\n') == ''


FOUR_COLUMN_FENCE_PROBLEM = (
    'an indented code fence at line {line} (```) is unsupported: a renderer reads a fence indented 4 or more columns '
    'as an indented code block. Start the fence at the outer level, indented by at most 3 spaces'
)
UNDER_LIST_ITEM_FENCE_PROBLEM = (
    'an indented code fence at line {line} (```) is unsupported: it sits under the list item above it, so a renderer '
    'reads it as code inside that item; put the fence at column 0 after a non-list line'
)


@pytest.mark.small
class DescribeIndentedCodeFence:
    """Markdown reads a fence indented 4 or more spaces as code, and one under a list item as that item's code."""

    HEADING_PROBLEM = 'a heading that is not a known "###" section heading or version heading at line 9'

    @pytest.mark.parametrize('indent', ['    ', '\t', '          '])
    def it_reports_a_fence_indented_four_or_more_columns_and_reads_the_lines_after_it(self, indent: str) -> None:
        body = f'### Internal\n\n{indent}```\n\n# Feature\n\n- Undocumented. (#1)\n\n{indent}```\n'

        problems = _problems_of(body)

        assert FOUR_COLUMN_FENCE_PROBLEM.format(line=7) in problems
        assert self.HEADING_PROBLEM in problems

    @pytest.mark.parametrize('indent', ['    ', '  '])
    def it_reports_an_indented_fence_that_follows_a_list_item(self, indent: str) -> None:
        body = f'### Internal\n\n- Bump.\n\n{indent}```\n\n# Feature\n\n- Undocumented. (#1)\n\n{indent}```\n'

        problems = _problems_of(body)

        assert UNDER_LIST_ITEM_FENCE_PROBLEM.format(line=9) in problems
        assert 'a heading that is not a known "###" section heading or version heading at line 11' in problems

    def it_reports_an_indented_fence_directly_under_a_list_item_without_hiding_a_gated_section(self) -> None:
        body = '### Internal\n\n- A step.\n  ```\n### Fix\n\n- **Fixed a crash on Windows.** (#5)\n\n  ```\n'

        problems = _problems_of(body)

        assert UNDER_LIST_ITEM_FENCE_PROBLEM.format(line=8) in problems
        assert 'Fixed a crash on Windows' in problems

    @pytest.mark.parametrize('indent', ['', ' ', '  ', '   '])
    def it_keeps_a_fence_with_up_to_three_spaces_outside_a_list_as_code(self, indent: str) -> None:
        assert _problems_of(f'### Internal\n\n{indent}```\n# install\n{indent}```\n') == ''

    def it_keeps_an_outer_fence_after_a_list_item_as_code(self) -> None:
        assert _problems_of('### Internal\n\n- Bump.\n\n```\n# install\n```\n') == ''


@pytest.mark.small
class DescribeRawHtmlBlocks:
    def it_rejects_a_raw_html_block_that_hides_a_section_heading(self) -> None:
        body = '### Fix\n\n- **A.** (no docs: r)\n  <div>\n### Internal\n</div>\n\n- **Undocumented.**\n'

        problems = _problems_of(body)

        assert 'a raw HTML block tag at line 8' in problems

    @pytest.mark.parametrize(
        'line',
        [
            '<div>',
            '  <div>',
            '</div>',
            '<details markdown="1">',
            '<PRE>',
            '<table>',
            '<custom-tag>',
            '<?php',
            '<![CDATA[',
            '<br/>',
        ],
    )
    @pytest.mark.parametrize('section', ['Fix', 'Internal'])
    def it_rejects_a_line_that_starts_with_an_html_tag_in_every_section(self, section: str, line: str) -> None:
        problems = _problems_of(f'### {section}\n\n- A. (no docs: r)\n\n{line}\n')

        assert f'a raw HTML block tag at line 9 ({line.strip()});' in problems

    @pytest.mark.parametrize('prefix', ['- ', '> ', '- > '])
    def it_rejects_an_html_tag_after_a_list_or_quote_marker(self, prefix: str) -> None:
        assert 'a raw HTML block tag' in _problems_of(f'### Internal\n\n{prefix}<div>\n')

    @pytest.mark.parametrize(
        'line',
        [
            '- Use `<div>` in prose. (no docs: r)',
            '- Mid-line <div> stays text. (no docs: r)',
            '- <https://example.com> links. (no docs: r)',
            '- <user@example.com> mails. (no docs: r)',
            '- A < B and C > D. (no docs: r)',
        ],
    )
    def it_accepts_html_that_does_not_start_a_block(self, line: str) -> None:
        assert _problems_of(f'### Fix\n\n{line}\n') == ''


@pytest.mark.small
class DescribeFenceCloserLength:
    def it_rejects_a_fence_closer_longer_than_its_opener(self) -> None:
        body = '### Internal\n\n````\nx\n`````\n````\n#### Hidden\n````\n'

        problems = _problems_of(body)

        assert 'a fence closer longer than its opener at line 9 (`````): the docs renderer' in problems
        assert 'a heading that is not a known "###" section heading or version heading at line 11' in problems

    @pytest.mark.parametrize('marker', ['```', '````', '~~~', '~~~~~'])
    def it_closes_a_fence_on_a_closer_of_the_same_length(self, marker: str) -> None:
        assert _problems_of(f'### Internal\n\n{marker}\n# install\n{marker}\n') == ''

    def it_does_not_close_a_fence_on_a_shorter_closer(self) -> None:
        problems = _problems_of('### Internal\n\n````\n# x\n```\n')

        assert 'code fence opened at line 7 is never closed' in problems


HEADING_FIX = (
    'use one of the five "###" section names, or keep an issue-number line directly under its bullet with no blank '
    'line, or escape it as "\\#720)"'
)
ONE_PROBLEM_PER_REJECTED_LINE = {
    'thematic break': (
        '---',
        ['a thematic break or setext underline at line 9 (---); remove the line or write it as a code span'],
    ),
    'unspaced heading': (
        '#Feature',
        [
            'a heading that is not a known "###" section heading or version heading at line 9 (#Feature); '
            f'{HEADING_FIX}',
        ],
    ),
    'html block': (
        '<div>',
        [
            'a raw HTML block tag at line 9 (<div>); move the tag into the middle of a sentence or write it as a code '
            'span'
        ],
    ),
    'stray h2': (
        '## Highlights',
        [
            '"##" heading at line 9 (## Highlights) is inside the entry but is not a version heading; the release '
            'notes would publish what follows it as part of this entry'
        ],
    ),
    'unspaced version copy': (
        '##v2.0.0',
        [
            'a heading that is not a known "###" section heading or version heading at line 9 (##v2.0.0); '
            f'{HEADING_FIX}',
            'a second visible copy of the entry version heading is at line 9 (##v2.0.0); remove it so the entry is '
            'published once',
        ],
    ),
    'listed delimiter': (
        '- ---',
        ['a thematic break or setext underline at line 9 (- ---); remove the line or write it as a code span'],
    ),
    'indented fence': (
        '    ```\n    code\n    ```',
        [
            'an indented code fence at line 9 (```) is unsupported: it sits under the list item above it, so a '
            'renderer reads it as code inside that item; put the fence at column 0 after a non-list line'
        ],
    ),
}


@pytest.mark.small
class DescribeOneReportPerRejectedLine:
    """A rejected line gets only its specific problems, not a second "paragraph" or "no docs reference" report."""

    @pytest.mark.parametrize(
        ('line', 'expected'), ONE_PROBLEM_PER_REJECTED_LINE.values(), ids=ONE_PROBLEM_PER_REJECTED_LINE.keys()
    )
    def it_reports_a_rejected_line_in_a_gated_section_once(self, line: str, expected: list[str]) -> None:
        assert _problems_of(f'### Fix\n\n{LINKED_BULLET}\n\n{line}\n').splitlines() == expected

    def it_reports_a_quoted_fence_in_a_gated_section_once(self) -> None:
        problems = _problems_of(f'### Fix\n\n{LINKED_BULLET}\n\n> ```\n> code\n> ```\n')

        assert problems.splitlines() == [
            'a code fence opened inside a list item or block quote at line 9 (> ```) is unsupported; start the fence '
            'at the outer level'
        ]

    def it_reports_a_rejected_bullet_before_the_first_section_once(self) -> None:
        problems = _problems_of(f'- ---\n\n### Fix\n\n{LINKED_BULLET}\n')

        assert problems.splitlines() == [
            'a thematic break or setext underline at line 5 (- ---); remove the line or write it as a code span'
        ]

    def it_still_reports_a_comment_on_a_rejected_line(self) -> None:
        problems = _problems_of(f'### Fix\n\n{LINKED_BULLET}\n<!-- old --> ## v1.9.9\n')

        assert problems.splitlines() == [
            'a heading that is not a known "###" section heading or version heading at line 8 (## v1.9.9); '
            f'{HEADING_FIX}',
            'HTML comment at line 8 under "### Fix"; remove it',
        ]

    @pytest.mark.parametrize(
        ('opener', 'line', 'expected'),
        [
            ('> ```', '> - **Undocumented.** (#5)', 'a blockquote at line 9 under "### Fix"'),
            ('    ```', 'Undocumented prose.', 'a paragraph that is not part of a list item at line 9 under "### Fix"'),
        ],
    )
    def it_reads_the_lines_of_a_fence_left_open_above_the_entry(self, opener: str, line: str, expected: str) -> None:
        changelog = f'# Changelog\n\n{opener}\n\n## v2.0.0\n\n### Fix\n\n{line}\n'

        problems = _load_checker().find_problems(changelog, '2.0.0', SITE)

        assert any(expected in problem for problem in problems), problems

    def it_still_gates_a_bullet_inside_an_unsupported_fence_body(self) -> None:
        body = f'### Fix\n\n{LINKED_BULLET}\n  ```\n  code\n{UNLINKED_BULLET}\n  ```\n'

        assert _problems_of(body).splitlines() == [
            'an indented code fence at line 8 (```) is unsupported: it sits under the list item above it, so a '
            'renderer reads it as code inside that item; put the fence at column 0 after a non-list line',
            'bullet under "### Fix" at line 10 (**Fixed a crash on Windows.** (#5)) has no docs reference and no '
            '"(no docs: <reason>)" exemption',
        ]


@pytest.mark.small
class DescribeWrappedIssueReferences:
    @pytest.mark.parametrize(
        'continuation',
        [
            '  #989-#994)',
            '  #964) Thanks to a contributor. (no docs: r)',
            '  #964 for details (no docs: r)',
            '  #964,#965',
            '    #964)',
            '  #Feature',
            '  ####Detail',
            '  ####### seven',
        ],
    )
    def it_accepts_an_indented_continuation_line_that_starts_with_a_hash(self, continuation: str) -> None:
        body = f'### Fix\n\n- **A.** (no docs: r) (#963,\n{continuation}\n'

        assert _problems_of(body) == ''

    @pytest.mark.parametrize('continuation', ['  # Feature', '  ## Feature', '  ### Internal', '  #', '  ###### x'])
    def it_rejects_a_continuation_line_that_could_render_a_heading(self, continuation: str) -> None:
        body = f'### Fix\n\n- **A.** (no docs: r) (#963,\n{continuation}\n'

        assert f'{INDENTED_HEADING_AT} 8 ({continuation.strip()})' in _problems_of(body)

    def it_rejects_a_hash_line_after_a_blank_line_below_a_bullet(self) -> None:
        body = '### Fix\n\n- **A.** (no docs: r)\n\n  #964)\n'

        assert 'a heading that is not a known' in _problems_of(body)

    def it_rejects_an_unindented_hash_line_below_a_bullet(self) -> None:
        assert 'a heading that is not a known' in _problems_of('### Fix\n\n- **A.** (no docs: r)\n#964)\n')

    def it_rejects_an_html_heading_on_a_continuation_line(self) -> None:
        assert 'a raw HTML heading' in _problems_of('### Fix\n\n- **A.** (no docs: r)\n  #1 <h1>x</h1>\n')

    def it_rejects_a_hash_line_under_a_quoted_bullet(self) -> None:
        assert f'{UNSUPPORTED_HEADING_AT} 8 (#716));' in _problems_of('### Internal\n\n> - x\n  #716)\n')


MKDOCS_CONFIG = Path(__file__).resolve().parents[2] / 'mkdocs.yml'
ORACLE_EXTENSIONS_NOT_IN_MKDOCS = frozenset({'toc', 'tables', 'fenced_code'})
REJECTED_SHAPES_THE_RENDERER_SHOWS = [
    ('#Feature', '<h1'),
    ('####Detail', '<h4'),
    ('###Feature', '<h3'),
    ('#Feature ###', '<h1'),
    ('#\tFeature', '<h1'),
    ('##v2.0.0', '<h2'),
    ('###Feature ###', '<h3'),
    ('Feature\n=======', '<h1'),
    ('Highlights\n---', '<h2'),
    ('x\n--', '<h2'),
    ('A | B\n---', '<h2'),
    ('<em>Feature</em>\n---', '<h2'),
    ('> #Feature', '<h1'),
    ('> > #Feature', '<h1'),
    ('- #### Detail', '<h4'),
    ('1. #### Detail', '<h4'),
    ('  - ###Feature', '<h3'),
    ('- ---', '<hr'),
    ('> <em>Feature</em>\n> ---', '<h2'),
    ('<h1>Feature</h1>', '<h1'),
    ('<h6>Detail</h6>', '<h6'),
    ('<H2 class="x">Feature</H2>', '<h2'),
    ('<h3 id="anchor">Feature</h3>', '<h3'),
    ('> <h1>Feature</h1>', '<h1'),
    ('- <h4>Detail</h4>', '<h4'),
    ('- Bump \\`<h2>Feature</h2>`', '<h2'),
    ('- Use `<!--` here.\n\n# Feature\n\n-->', '<h1'),
    ('- Bump <!-- x\n\n# Feature\n\n-->', '<h1'),
    ('> <!-- note\n> ### Feature\n> - New --foo option.\n-->', '<h3'),
    ('> > <!-- x\n> > # Big\n-->', '<h1'),
    ('- a\n  > <!-- x\n  > # Big\n-->', '<h1'),
    ('\\<!-- x\n## v0.9.9 (2020-01-01)\n-->', '<h2'),
    ('\\<!-- x\n# Big\n-->', '<h1'),
    ('\\<!-- x\n***\n-->', '<hr'),
    ('\\\\<!-- x\n# Big\n-->', '<h1'),
    ('    <!-- x\n## v0.9.9 (2020-01-01)\n-->', '<h2'),
    ('    <!-- x\n***\n-->', '<hr'),
    ('\t<!-- x\n# Big\n-->', '<h1'),
    ('> <!-- x\n> ## v2.0.0\n-->', '<h2'),
    ('- <!-- x\n# Big\n-->', '<h1'),
    ('1. <!-- x\n# Big\n-->', '<h1'),
    ('p <!-- x\n# Big\n-->', '<h1'),
    ('<!-- a --!>\n# Big\n-->', '<h1'),
    ('x <a title="\n<!-- y\n# Big\n-->\n">', '<h1'),
    ('x <a\n<!-- y\n# Big\n-->', '<h1'),
    ('    ```\n\n# Feature\n\n    ```', '<h1'),
    ('- Bump.\n\n    ```\n\n# Feature\n\n    ```', '<h1'),
    ('- item\n\n    #720)', '<h1'),
    ('````\nx\n`````\n````\n#### Hidden\n````', '<h4'),
]


COMMENT_OPENER_SHAPES = [
    '<!-- x',
    ' <!-- x',
    '   <!-- x',
    '- a\n  <!-- x',
    '1. a\n   <!-- x',
    '> a\n<!-- x',
    '    <!-- x',
    '\t<!-- x',
    '  \t<!-- x',
    '\\<!-- x',
    '\\\\<!-- x',
    '> <!-- x',
    '> > <!-- x',
    '>> <!-- x',
    '- <!-- x',
    '1. <!-- x',
    '- a\n  > <!-- x',
    'p <!-- x',
    '`a` <!-- x',
    '<!-- a --!>',
    '<!-- a\n--!> b',
]
TAIL_COMMENT_OPENER = '<!-- a --> t <!-- b'
SENTINEL = 'k1k'
SECTION_SWITCH_SHAPES = {
    'column 0': '### Fix',
    'one space': ' ### Fix',
    'two spaces': '  ### Fix',
    'three spaces': '   ### Fix',
    'tab': '\t### Fix',
    'tab after the hashes': '###\tFix',
    'closing hashes': '### Fix ###',
    'under a list item': '- k0k (no docs: r)\n### Fix',
    'indented under a list item': '- k0k (no docs: r)\n  ### Fix',
    'after a blank line under a list item': '- k0k (no docs: r)\n\n  ### Fix',
    'after text': 'Some prose.\n### Fix',
    'indented after text': 'Some prose.\n  ### Fix',
}


def _sentinel_changelog(shape: str) -> str:
    """Return an entry with ``shape`` under ``### Feature`` and an ungated-looking sentinel bullet after it."""
    return f'## v1.0.0\n\n### Feature\n\n{shape}\n\n- {SENTINEL} (#1)\n'


def _gate_section_of_sentinel(changelog: str) -> str:
    problems = '\n'.join(_load_checker().find_problems(changelog, '1.0.0', SITE))
    match = re.search(rf'bullet under "### ([^"]+)" at line \d+ \({SENTINEL}', problems)
    assert match is not None, problems
    return match.group(1)


def _mkdocs_markdown_extension_names() -> set[str]:
    """Return the extension names in ``mkdocs.yml``; composing the YAML never runs its ``!!python`` tags."""
    root = cast('yaml.MappingNode', yaml.compose(MKDOCS_CONFIG.read_text(encoding='utf-8'), Loader=yaml.SafeLoader))
    extensions = next(value for key, value in root.value if key.value == 'markdown_extensions')
    return {_extension_name(item) for item in extensions.value}


def _extension_name(item: yaml.Node) -> str:
    return cast('str', item.value if isinstance(item, yaml.ScalarNode) else item.value[0][0].value)


@pytest.mark.small
class DescribeShapesTheRendererShows:
    @pytest.mark.parametrize(('text', 'tag'), REJECTED_SHAPES_THE_RENDERER_SHOWS)
    def it_rejects_each_shape_the_renderer_turns_into_a_heading_or_break(self, text: str, tag: str) -> None:
        assert _problems_of(f'### Internal\n\n{text}\n') != '', tag


@pytest.mark.medium
class DescribeRendererOracle:
    """The real docs renderer is a one-way oracle for the strict format.

    It samples rejected shapes that do render a heading (or a break), to prove those rejections guard real bypasses.
    Shapes the strict format rejects without a renderer agreeing need no oracle. The oracle needs the ``markdown`` and
    ``pymdownx`` packages, which the uv and CI environments install from the docs group; the tox environments do not,
    so there these tests are skipped.
    """

    MARKDOWN_EXTENSIONS = (
        'abbr',
        'admonition',
        'attr_list',
        'def_list',
        'fenced_code',
        'footnotes',
        'md_in_html',
        'tables',
        'toc',
        'pymdownx.arithmatex',
        'pymdownx.betterem',
        'pymdownx.caret',
        'pymdownx.critic',
        'pymdownx.details',
        'pymdownx.emoji',
        'pymdownx.highlight',
        'pymdownx.inlinehilite',
        'pymdownx.keys',
        'pymdownx.magiclink',
        'pymdownx.mark',
        'pymdownx.progressbar',
        'pymdownx.smartsymbols',
        'pymdownx.snippets',
        'pymdownx.superfences',
        'pymdownx.tabbed',
        'pymdownx.tasklist',
        'pymdownx.tilde',
    )

    @classmethod
    def _render(cls, text: str) -> str:
        markdown = pytest.importorskip('markdown', reason='the docs group renders the oracle samples')
        pytest.importorskip('pymdownx', reason='the docs group provides the pymdownx extensions')
        return cast(
            'str',
            markdown.markdown(
                text, extensions=list(cls.MARKDOWN_EXTENSIONS), extension_configs={'toc': {'toc_depth': 3}}
            ),
        )

    def it_renders_with_the_extensions_mkdocs_uses(self) -> None:
        expected = _mkdocs_markdown_extension_names() | ORACLE_EXTENSIONS_NOT_IN_MKDOCS

        assert set(self.MARKDOWN_EXTENSIONS) == expected

    @pytest.mark.parametrize(('text', 'tag'), REJECTED_SHAPES_THE_RENDERER_SHOWS)
    def it_renders_a_heading_or_break_for_each_rejected_shape(self, text: str, tag: str) -> None:
        assert tag in self._render(f'{text}\n').lower()

    @pytest.mark.parametrize(
        'text',
        [
            '- **A.** (#598,\n  #716)\n',
            '- **A.** (#963,\n  #989-#994)\n',
            '- **A.** (#963,\n  #964) Thanks. (no docs: r)\n',
            '- **A.** (#963,\n  #964 for details)\n',
            '- **A.** (#963,\n  #964,#965\n',
            '- **A.** (#963,\n    #964)\n',
            '- **A.** (#963,\n  #Feature\n',
            '- **A.** (#963,\n  ####Detail\n',
            '- **A.** (#963,\n  ####### seven\n',
            'Plain prose.\n',
            'Use `<h1>` in prose.\n',
            '````markdown\n> ```\n````\n',
        ],
    )
    def it_renders_no_heading_for_accepted_plain_content(self, text: str) -> None:
        assert '<h' not in self._render(text)

    @pytest.mark.parametrize('text', ['- A.\n  <div>\n### Internal\n</div>\n', '<?php\n### Internal\n?>\n'])
    def it_hides_a_section_heading_inside_a_raw_html_block(self, text: str) -> None:
        assert '<h3' not in self._render(text)

    @pytest.mark.parametrize('text', ['- A. <span>\n### Internal\n</span>\n', 'Text <div>\n### Internal\n</div>\n'])
    def it_shows_a_section_heading_after_a_tag_that_is_not_at_the_start_of_a_line(self, text: str) -> None:
        assert '<h3' in self._render(text)

    @pytest.mark.parametrize('opener', COMMENT_OPENER_SHAPES)
    def it_hides_the_line_after_a_comment_opener_exactly_when_the_gate_hides_it(self, opener: str) -> None:
        sample = f'{opener}\n# Probe\n-->\n'
        rendered = '<h1' in self._render(sample)

        assert rendered == ('(# Probe)' in _problems_of(f'### Internal\n\n{sample}'))

    def it_hides_a_comment_after_a_comment_that_starts_the_line_which_the_gate_rejects(self) -> None:
        assert '<h1' not in self._render(f'{TAIL_COMMENT_OPENER}\n# Probe\n-->\n')

    @pytest.mark.parametrize('shape', SECTION_SWITCH_SHAPES.values(), ids=SECTION_SWITCH_SHAPES.keys())
    def it_gates_a_bullet_under_the_section_the_rendered_page_shows_it_under(self, shape: str) -> None:
        changelog = _sentinel_changelog(shape)
        rendered_before_sentinel = self._render(changelog).split(SENTINEL)[0]
        rendered_section = re.findall(r'<h3\b[^>]*>(.*?)</h3>', rendered_before_sentinel)[-1]

        assert _gate_section_of_sentinel(changelog) == rendered_section

    def it_renders_a_heading_inside_a_loose_list_item_from_a_line_indented_four_columns(self) -> None:
        assert '<h3 id="fix">Fix</h3>\n</li>' in self._render('- a\n\n    ### Fix\n')

    def it_rejects_a_heading_indented_four_columns_under_a_loose_list_item(self) -> None:
        changelog = _sentinel_changelog('- k0k (no docs: r)\n\n    ### Fix')

        problems = _load_checker().find_problems(changelog, '1.0.0', SITE)

        assert f'{INDENTED_HEADING_AT} 7 (### Fix); {INDENTED_HEADING_FIX}' in problems


def _gated_changelog(bullet: str) -> str:
    return f'## v9.9.9\n\n### Fix\n\n{bullet}\n'


@pytest.mark.small
class DescribeCodeSpanTiming:
    def it_checks_a_backtick_line_at_the_length_cap_in_linear_time(self) -> None:
        checker = _load_checker()
        bullet = '- x' + '`' * (checker.MAX_LINE_LENGTH - 3)
        started = time.perf_counter()

        checker.find_problems(_gated_changelog(bullet), '9.9.9', SITE)

        assert time.perf_counter() - started < LINEAR_TIME_BUDGET_SECONDS

    def it_checks_a_bullet_joined_from_fifty_backtick_lines_in_linear_time(self) -> None:
        checker = _load_checker()
        continuation = '\n'.join(['  ' + '`' * 988] * 49)
        bullet = '- x' + '`' * 987 + '\n' + continuation
        started = time.perf_counter()

        checker.find_problems(_gated_changelog(bullet), '9.9.9', SITE)

        assert time.perf_counter() - started < LINEAR_TIME_BUDGET_SECONDS

    @pytest.mark.parametrize(
        'pattern',
        [
            '````````a',
            '\\``a',
            '````````a```````a``````a`````a````a```a``a`a',
            '`a``a```a````a`````a``````a```````a````````a',
        ],
    )
    def it_checks_a_line_of_runs_at_the_cap_in_linear_time(self, pattern: str) -> None:
        checker = _load_checker()
        line = '- x ' + pattern * ((checker.MAX_LINE_LENGTH - 4) // len(pattern))
        started = time.perf_counter()

        checker.find_problems(_gated_changelog(line), '9.9.9', SITE)

        assert time.perf_counter() - started < LINEAR_TIME_BUDGET_SECONDS

    @pytest.mark.parametrize(
        'pattern',
        [
            '````````a',
            '\\``a',
            '````````a```````a``````a`````a````a```a``a`a',
            '`a``a```a````a`````a``````a```````a````````a',
        ],
    )
    def it_checks_a_bullet_joined_from_fifty_lines_of_runs_at_the_cap_in_linear_time(self, pattern: str) -> None:
        checker = _load_checker()
        line = pattern * ((checker.MAX_LINE_LENGTH - 4) // len(pattern))
        bullet = '- x ' + line + ''.join(['\n  ' + line] * 49)
        started = time.perf_counter()

        checker.find_problems(_gated_changelog(bullet), '9.9.9', SITE)

        assert time.perf_counter() - started < LINEAR_TIME_BUDGET_SECONDS

    def it_finds_the_spans_of_a_long_text_of_fallback_openers_in_linear_time(self) -> None:
        checker = _load_checker()
        text = '\\``a' * 50000
        started = time.perf_counter()

        checker.code_spans(text)

        assert time.perf_counter() - started < LINEAR_TIME_BUDGET_SECONDS


REGEX_CODE_SPAN = re.compile(r'(?<!\\)(`+).+?(?<!`)\1(?!`)', re.DOTALL)
WELL_FORMED_CODE_SPAN_TEXTS = [
    'no spans at all',
    '`a`',
    'x `a` y `b` z',
    '``a ` b``',
    '```a `` b```',
    '\\`a` b`',
    '`a\\`',
    '`<!--` x',
    '`<!-- x -->` y <!-- z -->',
    '``<h1>`` and <h2>',
    '`a\nb` y',
    'first `line\n  second` line',
    '` `',
    '`unclosed',
    'a `` b',
    '[docs](u) `[x](v)` (no docs: r)',
]


@pytest.mark.small
class DescribeCodeSpans:
    @pytest.mark.parametrize('text', WELL_FORMED_CODE_SPAN_TEXTS)
    def it_finds_the_spans_the_regex_found_on_well_formed_text(self, text: str) -> None:
        expected = [match.span() for match in REGEX_CODE_SPAN.finditer(text)]

        assert _load_checker().code_spans(text) == expected

    def it_opens_a_span_after_an_escaped_backslash(self) -> None:
        assert _load_checker().code_spans('\\\\`x`') == [(2, 5)]

    @pytest.mark.parametrize(
        ('text', 'expected'),
        [
            ('``a`', [(0, 4)]),
            ('``a`b`', [(0, 4)]),
            ('a``b`c', [(1, 5)]),
            ('a ` b `` c', [(2, 8)]),
            ('`a```b', [(0, 5)]),
            ('```a`b``c`', [(0, 8)]),
            ('\\``a` b', [(2, 5)]),
        ],
    )
    def it_closes_an_opener_at_another_length_as_the_docs_renderer_does(
        self, text: str, expected: list[tuple[int, int]]
    ) -> None:
        assert _load_checker().code_spans(text) == expected

    def it_finds_no_span_in_text_with_a_run_longer_than_the_cap(self) -> None:
        checker = _load_checker()
        run = '`' * (checker.MAX_BACKTICK_RUN + 1)

        assert checker.code_spans(f'`a` {run}') == []


def _sentinels(text: str) -> set[str]:
    return set(re.findall(r'k\d+k', text))


def _joined_like_a_bullet(text: str) -> str:
    return ' '.join(part.strip() for part in text.split('\n'))


RENDERER_PAIRING_TEXTS = [
    'k0k ``k1k[docs](p.md#a)`k2k',
    'k0k ``k1k(no docs: r)`k2k',
    'k0k ``k1k`<h2>k2k</h2>` k3k',
    'k0k ```k1k ``<h2>k2k</h2>`` k3k',
    'k0k `k1k``k2k',
    'k0k ``k1k`k2k`k3k',
    'k0k `k1k `` k2k ` k3k',
    'k0k ``k1k` k2k ``k3k',
    'k0k ```k1k`k2k``k3k`k4k',
    'k0k `k1k',
    'k0k k1k ```',
    'k0k \\`k1k`k2k`k3k',
    'k0k \\\\`k1k`k2k',
    'k0k \\\\\\`k1k`k2k`k3k',
    'k0k \\``k1k`k2k',
    'k0k `k1k\\`k2k`k3k',
    'k0k `k1k\n  k2k` k3k `k4k` k5k',
    'k0k ``k1k`\n  `` k2k `` k3k',
    'k0k `k1k\n  k2k `` k3k\n  k4k ` k5k',
    'k0k \\\n  `k1k` k2k',
]


@pytest.mark.medium
class DescribeCodeSpansMatchTheRenderer:
    """``code_spans`` pairs backticks as the docs renderer does, so the gate hides exactly what renders as code.

    Each sentinel (``k<n>k``) is visible to the gate when ``_without_code_spans`` keeps it, and visible to a reader
    when the rendered page shows it outside every ``<code>`` element. A sentinel the renderer drops is in neither.
    """

    @staticmethod
    def _rendered_outside_code(text: str) -> set[str]:
        html = DescribeRendererOracle._render(f'- {text}\n')
        return _sentinels(re.sub(r'<code\b[^>]*>.*?</code>', '', html, flags=re.DOTALL))

    @pytest.mark.parametrize('text', RENDERER_PAIRING_TEXTS)
    def it_hides_the_text_the_renderer_shows_as_code(self, text: str) -> None:
        gate_visible = _sentinels(_load_checker()._without_code_spans(_joined_like_a_bullet(text)))

        assert gate_visible == self._rendered_outside_code(text)

    def it_renders_a_docs_link_after_a_longer_opener_as_code(self) -> None:
        assert 'href="p.md#a"' not in DescribeRendererOracle._render('- x ``[docs](p.md#a)`\n')

    def it_renders_a_raw_heading_after_a_span_closed_by_a_shorter_run(self) -> None:
        assert '<h2>x</h2>' in DescribeRendererOracle._render('- x ``a`<h2>x</h2>` (no docs: r)\n')

    def it_renders_a_raw_heading_between_spans_that_cross_a_line(self) -> None:
        assert '<h2>c</h2>' in DescribeRendererOracle._render('- x `a\n  b` <h2>c</h2> `d` (no docs: r)\n')

    def it_renders_a_raw_heading_after_a_comment_that_a_code_span_ends(self) -> None:
        assert '<h2>y</h2>' in DescribeRendererOracle._render('x <!-- ` --> `<h2>y</h2>` `\n')


UNPAIRED_BACKTICKS_AT_LINE_5 = 'an unpaired backtick run at line 5'


@pytest.mark.small
class DescribeUnpairedBackticks:
    """A line whose backticks do not all pair exactly on that line is rejected.

    The docs renderer closes an opener at a run of another length, and pairs backticks across the lines of a
    paragraph. Requiring every run to close at a run of its own length on its own line makes the pairing of a line, of
    a joined bullet and of the rendered paragraph the same.
    """

    @pytest.mark.parametrize(
        'bullet',
        [
            '- x ``[docs](p.md#a)`',
            '- x ``(no docs: r)`',
            '- x ``a`<h2>x</h2>` (no docs: r)',
            '- x ```a ``<h2>x</h2>`` (no docs: r)',
            '- x `a\n  b` <h2>c</h2> `d` (no docs: r)',
            '- x ``a`\n  `` <h2>c</h2> `` (no docs: r)',
            '- x `unclosed (no docs: r)',
        ],
    )
    def it_rejects_a_bullet_whose_first_line_does_not_pair_its_backticks(self, bullet: str) -> None:
        problems = _load_checker().find_problems(_gated_changelog(bullet), '9.9.9', SITE)

        assert any(problem.startswith(UNPAIRED_BACKTICKS_AT_LINE_5) for problem in problems), problems

    def it_says_how_to_fix_an_unpaired_run(self) -> None:
        problems = _load_checker().find_problems(_gated_changelog('- x ``a` (no docs: r)'), '9.9.9', SITE)

        assert problems == [
            'an unpaired backtick run at line 5 (- x ``a` (no docs: r)); close every code span on the line it opens '
            'on with a run of the same length, or escape a literal backtick as "\\`"'
        ]

    def it_rejects_an_unpaired_run_in_an_exempt_section(self) -> None:
        assert 'an unpaired backtick run at line 7 (- x `a)' in _problems_of('### Internal\n\n- x `a\n  b`')

    @pytest.mark.parametrize(
        'bullet',
        [
            '- x `a` and ``b`c`` (no docs: r)',
            '- x \\`literal and `code` (no docs: r)',
            '- x \\\\`code` (no docs: r)',
            '- x ```````` eight ```````` (no docs: r)',
        ],
    )
    def it_accepts_a_bullet_whose_backticks_pair_exactly(self, bullet: str) -> None:
        assert _load_checker().find_problems(_gated_changelog(bullet), '9.9.9', SITE) == []


@pytest.mark.small
class DescribeBacktickRunCap:
    def it_rejects_a_run_longer_than_the_cap(self) -> None:
        checker = _load_checker()
        run = '`' * (checker.MAX_BACKTICK_RUN + 1)

        problems = checker.find_problems(_gated_changelog(f'- x {run} (no docs: r)'), '9.9.9', SITE)

        assert problems == [
            f'a run of more than {checker.MAX_BACKTICK_RUN} backticks at line 5 (- x {run} (no docs: r)); '
            f'write code spans with at most {checker.MAX_BACKTICK_RUN} backticks'
        ]

    def it_rejects_a_long_run_inside_an_html_comment(self) -> None:
        run = '`' * 9

        assert f'a run of more than 8 backticks at line 7 (<!-- {run} -->)' in _problems_of(
            f'### Internal\n\n<!-- {run} -->'
        )

    def it_reports_every_fence_line_of_a_nine_backtick_fence(self) -> None:
        run = '`' * 9

        problems = _problems_of(f'### Internal\n\n{run}\nx {run}\n{run}')

        assert problems.splitlines() == [
            f'a run of more than 8 backticks at line {number} ({text}); write code spans with at most 8 backticks'
            for number, text in ((7, run), (8, f'x {run}'), (9, run))
        ]

    def it_reports_a_long_run_inside_a_fence_the_format_does_not_support(self) -> None:
        run = '`' * 9

        assert f'a run of more than 8 backticks at line 8 (x {run})' in _problems_of(
            f'### Internal\n\n> ```\nx {run}\n> ```'
        )

    def it_accepts_a_five_backtick_fence_that_shows_a_four_backtick_fence(self) -> None:
        assert _problems_of('### Internal\n\n`````markdown\n````text\nx\n````\n`````') == ''


@pytest.mark.small
class DescribeBacktickInComment:
    def it_rejects_a_backtick_inside_an_html_comment(self) -> None:
        problems = _problems_of('### Internal\n\nx <!-- ` --> `<h2>y</h2>` `')

        assert (
            'a backtick on a line that also has an HTML comment at line 7 (x <!-- ` --> `<h2>y</h2>` `); the docs '
            'renderer pairs backticks before it reads comments, so move the comment to its own line'
        ) in problems

    def it_rejects_code_spans_that_meet_once_a_comment_between_them_is_removed(self) -> None:
        problems = _problems_of('### Internal\n\nx `a`<!---->``b`` <h2>y</h2> ```c```')

        assert 'a backtick on a line that also has an HTML comment at line 7' in problems

    def it_accepts_backticks_on_the_lines_of_a_comment_that_shows_no_text(self) -> None:
        assert _problems_of('### Internal\n\n<!--\n`a` and ```\n```\n-->') == ''

    @pytest.mark.parametrize('opener', ['x <!-- a', '  <!-- a'])
    def it_pairs_the_backticks_of_a_comment_that_does_not_start_a_line(self, opener: str) -> None:
        problems = _problems_of(f'### Internal\n\n{opener}\n` b\n-->')

        assert 'an unpaired backtick run at line 8 (` b)' in problems


@pytest.mark.medium
class DescribeReleaseNotesStep:
    @staticmethod
    def _notes_step() -> dict[str, Any]:
        steps = [
            step
            for job in _jobs('release.yml').values()
            for step in job.get('steps', [])
            if step.get('id') == 'changelog'
        ]
        assert len(steps) == 1
        return cast('dict[str, Any]', steps[0])

    def it_takes_the_release_notes_from_the_checker(self) -> None:
        run = self._notes_step()['run']

        assert GATE_COMMAND in run
        assert '--notes-out' in run

    def it_does_not_extract_the_notes_with_a_second_parser(self) -> None:
        run = self._notes_step()['run']

        assert 'awk' not in run
        assert 'sed' not in run

    def it_fails_the_step_when_the_notes_are_missing_or_empty(self) -> None:
        run = self._notes_step()['run']

        assert '[ ! -s release_notes.md ]' in run
        assert 'exit 1' in run
