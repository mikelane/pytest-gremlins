"""Unit tests for the message matcher behind drift check 1d."""

from __future__ import annotations

import pytest

from .emitted_messages import (
    line_is_emittable,
    message_templates,
)


@pytest.mark.small
class DescribeMessageTemplates:
    """Templates come from the message strings in the source, with placeholders as wildcards."""

    def it_turns_f_string_fields_into_wildcards(self):
        source = "msg = f'pytest-gremlins: skipped {path}: could not instrument ({reason})'"

        assert message_templates(source) == ['pytest-gremlins: skipped \x00: could not instrument (\x00)']

    def it_turns_percent_format_fields_into_wildcards(self):
        source = "logger.warning('pytest-gremlins: could not install the finder (%s)', error)"

        assert message_templates(source) == ['pytest-gremlins: could not install the finder (\x00)']

    def it_turns_brace_format_fields_into_wildcards(self):
        source = "msg = 'pytest-gremlins: {count} gremlins from cache'"

        assert message_templates(source) == ['pytest-gremlins: \x00 gremlins from cache']

    def it_reads_each_line_of_a_multi_line_message(self):
        source = "msg = 'first\\npytest-gremlins: second line\\nthird'"

        assert message_templates(source) == ['pytest-gremlins: second line']

    def it_reads_a_message_after_a_carriage_return(self):
        source = "print(f'\\rpytest-gremlins: Progress {done}/{total}')"

        assert message_templates(source) == ['pytest-gremlins: Progress \x00/\x00']

    def it_reads_a_message_inside_a_script_embedded_in_a_string(self):
        source = 'SCRIPT = """\nprint(f\'pytest-gremlins: cannot read the file ({error})\', file=sys.stderr)\n"""'

        assert message_templates(source) == ['pytest-gremlins: cannot read the file (\x00)']

    def it_ignores_docstrings(self):
        source = 'def f():\n    """pytest-gremlins: only documented, never printed."""\n'

        assert message_templates(source) == []

    def it_ignores_a_message_that_is_only_the_prefix_and_a_placeholder(self):
        source = "raise pytest.UsageError(f'pytest-gremlins: {invalid}')"

        assert message_templates(source) == []


@pytest.mark.small
class DescribeLineIsEmittable:
    """A quoted docs line must match a template; wrapped or elided lines only need to start one."""

    TEMPLATES = ('pytest-gremlins: skipped \x00: could not instrument (\x00)', 'pytest-gremlins: cache cleared')

    @pytest.mark.parametrize(
        'line',
        [
            'pytest-gremlins: cache cleared',
            'pytest-gremlins: skipped src/demo/chain.py: could not instrument (RecursionError: too deep)',
            'pytest-gremlins: skipped <file>: could not instrument (<reason>)',
        ],
    )
    def it_accepts_a_line_that_fills_a_template(self, line):
        assert line_is_emittable(line, list(self.TEMPLATES), continues=False)

    @pytest.mark.parametrize(
        'line',
        [
            'pytest-gremlins: this message does not exist',
            'pytest-gremlins: cache',
            'pytest-gremlins: (zapped + timeout) / (total - pardoned)',
        ],
    )
    def it_rejects_a_line_no_template_produces(self, line):
        assert not line_is_emittable(line, list(self.TEMPLATES), continues=False)

    def it_accepts_the_start_of_a_message_when_the_line_is_wrapped(self):
        assert line_is_emittable('pytest-gremlins: skipped src/a.py: could not', list(self.TEMPLATES), continues=True)

    def it_accepts_the_start_of_a_message_when_the_line_is_elided(self):
        assert line_is_emittable('pytest-gremlins: cache ...', list(self.TEMPLATES), continues=False)

    def it_rejects_the_start_of_an_invented_message_when_the_line_is_wrapped(self):
        assert not line_is_emittable('pytest-gremlins: this message', list(self.TEMPLATES), continues=True)

    def it_rejects_a_truncated_line_that_is_not_marked_as_wrapped(self):
        assert not line_is_emittable(
            'pytest-gremlins: skipped src/a.py: could not', list(self.TEMPLATES), continues=False
        )
