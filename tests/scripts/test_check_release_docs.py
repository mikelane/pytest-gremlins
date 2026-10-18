"""Tests for scripts/check_release_docs.py -- the gate that blocks a release with undocumented changes."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_release_docs.py'
WORKFLOWS = Path(__file__).resolve().parents[2] / '.github' / 'workflows'
GATE_COMMAND = 'check_release_docs.py'
DOCS_URL = 'https://pytest-gremlins.readthedocs.io/en/latest'
SITE_PAGES = {'guide/configuration': frozenset({'batch-size', 'caching'}), '': frozenset()}


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
            '#### Detail',
            '```shell\npytest --gremlins\n```',
            '~~~\n- a bullet-shaped line\n~~~',
            '<!--\nmulti-line\ncomment\n-->',
            '- Wrote a `<!-- x -->` example. (#1)',
        ],
    )
    def it_allows_prose_fences_and_comments_that_are_closed(self, section: str, content: str) -> None:
        assert _problems_of(f'### {section}\n\n{content}\n') == ''

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
    def it_reports_a_comment_opened_in_a_code_span_that_a_later_code_span_closes(self) -> None:
        body = (
            '**The HTML report no longer drops text after a `<!--` in a docstring.**\n\n'
            '### Fix\n\n- **Fixed a crash on Windows.** (#5)\n\n'
            '### Internal\n\n- Renamed the `opener --> closer` helper. (#6)\n'
        )

        problems = _problems_of(body)

        assert 'HTML comment opened at line 5 hides the "###" heading at line 7' in problems

    def it_reports_a_comment_opened_in_an_exempt_section_that_hides_a_gated_section(self) -> None:
        body = (
            '### Internal\n\n- Wrote `<!--` in a docstring.\n\n'
            '### Fix\n\n- **Fixed a crash on Windows.** (#5)\n\n'
            '### Documentation\n\n- Wrote `-->` in a docstring.\n'
        )

        problems = _problems_of(body)

        assert 'HTML comment opened at line 7 hides the "###" heading at line 9' in problems

    def it_reports_a_fence_that_hides_a_gated_section(self) -> None:
        body = '### Internal\n\n- A step.\n  ```\n### Fix\n\n- **Fixed a crash on Windows.** (#5)\n\n  ```\n'

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
    @pytest.mark.parametrize(
        'heading', [' ### Fix', '  ### Feature', '   ### Upgrade notes', '###\tFix', '### Fix ###']
    )
    def it_gates_the_bullets_under_an_indented_or_closed_gated_heading_after_internal(self, heading: str) -> None:
        body = f'### Internal\n\n- Bumped a dev dependency. (#1)\n\n{heading}\n\n- **Fixed a crash.** (#2)\n'

        problems = _problems_of(body)

        assert 'Fixed a crash' in problems

    @pytest.mark.parametrize('heading', ['### Internal ###', '### Internal #', ' ### Internal', '###\tInternal'])
    def it_accepts_an_internal_heading_written_with_extra_syntax(self, heading: str) -> None:
        assert _problems_of(f'{heading}\n\n- Bumped a dev dependency. (#1)\n') == ''

    @pytest.mark.parametrize('heading', [' ### Fixes', '### Fixes ###', '###', '### ###'])
    def it_names_an_unknown_heading_written_with_extra_syntax(self, heading: str) -> None:
        assert 'unknown section heading' in _problems_of(f'{heading}\n\n- x\n')

    def it_does_not_read_a_hash_without_a_space_as_a_heading(self) -> None:
        assert 'unknown section heading' not in _problems_of('### Fix\n\n- **Fixed #12.** (no docs: x)\n#hashtag\n')


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

    return checker.find_problems(changelog, '2.0.0', SITE)


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
        check=False,
        env=env,
    )


@pytest.mark.medium
class DescribeNotesOut:
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
        return steps[0]

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
