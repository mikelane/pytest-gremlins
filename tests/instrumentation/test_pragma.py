"""Tests for inline suppression pragma parsing."""

from __future__ import annotations

import logging

import pytest

from pytest_gremlins.instrumentation.pragma import parse_pardoned_lines


@pytest.mark.small
class DescribeParsePardonedLines:
    """Tests for parse_pardoned_lines function."""

    def it_returns_empty_dict_for_source_with_no_pragmas(self):
        source = 'x = 1\ny = 2\n'
        assert parse_pardoned_lines(source) == {}

    def it_parses_equivalent_pragma(self):
        source = 'x = a // 2  # gremlin: pardon[equivalent] floor division is integer arithmetic\n'
        result = parse_pardoned_lines(source)
        assert result == {1: ('equivalent', 'floor division is integer arithmetic')}

    def it_parses_untestable_pragma(self):
        source = 'x = a + b  # gremlin: pardon[untestable] cannot observe without changing contract\n'
        result = parse_pardoned_lines(source)
        assert result == {1: ('untestable', 'cannot observe without changing contract')}

    def it_parses_out_of_scope_pragma(self):
        source = 'x = foo()  # gremlin: pardon[out_of_scope] scaffolding not business logic\n'
        result = parse_pardoned_lines(source)
        assert result == {1: ('out_of_scope', 'scaffolding not business logic')}

    def it_returns_correct_line_numbers(self):
        source = 'x = 1\ny = a // 2  # gremlin: pardon[equivalent] integer division\nz = 3\n'
        result = parse_pardoned_lines(source)
        assert 2 in result
        assert result[2] == ('equivalent', 'integer division')

    def it_parses_multiple_pragmas_in_one_source(self):
        source = (
            'x = a // 2  # gremlin: pardon[equivalent] floor division\n'
            'y = b + c\n'
            'z = d or e  # gremlin: pardon[untestable] cannot observe\n'
        )
        result = parse_pardoned_lines(source)
        assert len(result) == 2
        assert result[1] == ('equivalent', 'floor division')
        assert result[3] == ('untestable', 'cannot observe')

    def it_ignores_lines_without_pragma(self):
        source = 'x = 1  # regular comment\ny = 2\n'
        assert parse_pardoned_lines(source) == {}

    def it_ignores_pragma_with_invalid_reason_code(self):
        source = 'x = a // 2  # gremlin: pardon[invalid_reason] some text\n'
        result = parse_pardoned_lines(source)
        assert result == {}

    def it_ignores_pragma_without_justification(self, caplog):
        source = 'x = a // 2  # gremlin: pardon[equivalent]\n'
        with caplog.at_level(logging.WARNING):
            result = parse_pardoned_lines(source)
        assert result == {}
        assert any('justification' in msg.lower() for msg in caplog.messages)

    def it_ignores_pragma_with_empty_justification(self, caplog):
        source = 'x = a // 2  # gremlin: pardon[equivalent] \n'
        with caplog.at_level(logging.WARNING):
            result = parse_pardoned_lines(source)
        assert result == {}
        assert any('justification' in msg.lower() for msg in caplog.messages)

    def it_trims_whitespace_from_justification(self):
        source = 'x = a // 2  # gremlin: pardon[equivalent]   trimmed text   \n'
        result = parse_pardoned_lines(source)
        assert result == {1: ('equivalent', 'trimmed text')}

    def it_handles_pragma_with_leading_whitespace_in_comment(self):
        source = 'x = a // 2  #  gremlin: pardon[equivalent] with leading space\n'
        result = parse_pardoned_lines(source)
        assert result == {1: ('equivalent', 'with leading space')}

    def it_ignores_malformed_pragma_missing_bracket(self):
        source = 'x = a // 2  # gremlin: survivor equivalent justification\n'
        assert parse_pardoned_lines(source) == {}

    def it_ignores_malformed_pragma_missing_closing_bracket(self):
        source = 'x = a // 2  # gremlin: pardon[equivalent justification\n'
        assert parse_pardoned_lines(source) == {}

    def it_uses_one_indexed_line_numbers(self):
        source = 'a = 1\nb = 2  # gremlin: pardon[equivalent] second line\n'
        result = parse_pardoned_lines(source)
        assert 2 in result
        assert 0 not in result

    def it_includes_filename_in_unknown_reason_code_warning(self, caplog):
        source = 'x = a // 2  # gremlin: pardon[bad_reason] some text\n'
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma'):
            parse_pardoned_lines(source, file_path='mymodule.py')
        assert 'mymodule.py' in caplog.text
        assert 'bad_reason' in caplog.text

    def it_includes_filename_in_missing_justification_warning(self, caplog):
        source = 'x = a // 2  # gremlin: pardon[equivalent]\n'
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma'):
            parse_pardoned_lines(source, file_path='other.py')
        assert 'other.py' in caplog.text

    def it_defaults_file_path_to_unknown(self, caplog):
        source = 'x = a // 2  # gremlin: pardon[bad_reason] some text\n'
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma'):
            parse_pardoned_lines(source)
        assert '<unknown>' in caplog.text
