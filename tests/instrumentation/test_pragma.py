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


@pytest.mark.small
class DescribeLineAbovePragma:
    """Tests for standalone comment pragma placement (line-above)."""

    # --- AC1: inline pragma still maps to same line (regression guard) ---

    def it_keeps_inline_pragma_on_same_line(self):
        source = 'x = a // 2  # gremlin: pardon[equivalent] floor division\n'
        result = parse_pardoned_lines(source)
        assert result == {1: ('equivalent', 'floor division')}

    # --- AC2: standalone comment pragma maps to next line ---

    def it_maps_standalone_pragma_to_next_line(self):
        source = '# gremlin: pardon[equivalent] integer division rounds same as subtraction\nreturn a // b\n'
        result = parse_pardoned_lines(source)
        assert result == {2: ('equivalent', 'integer division rounds same as subtraction')}

    def it_maps_indented_standalone_pragma_to_next_line(self):
        source = '    # gremlin: pardon[untestable] cannot observe side effect\n    x = do_something()\n'
        result = parse_pardoned_lines(source)
        assert result == {2: ('untestable', 'cannot observe side effect')}

    def it_handles_standalone_pragma_mid_file(self):
        source = 'a = 1\nb = 2\n# gremlin: pardon[out_of_scope] scaffolding\nc = foo()\nd = 4\n'
        result = parse_pardoned_lines(source)
        assert result == {4: ('out_of_scope', 'scaffolding')}

    # --- AC3: standalone pragma followed by blank line warns and is ignored ---

    def it_warns_when_standalone_pragma_followed_by_blank_line(self, caplog):
        source = '# gremlin: pardon[equivalent] integer division\n\nreturn a // b\n'
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma'):
            result = parse_pardoned_lines(source, file_path='module.py')
        assert result == {}
        assert any('not adjacent' in msg.lower() for msg in caplog.messages)

    # --- AC4: standalone pragma on last line of file warns and is ignored ---

    def it_warns_when_standalone_pragma_is_last_line(self, caplog):
        source = 'x = 1\n# gremlin: pardon[equivalent] integer division\n'
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma'):
            result = parse_pardoned_lines(source, file_path='tail.py')
        assert result == {}
        assert any('no code line below' in msg.lower() for msg in caplog.messages)

    # --- AC5: same-line pragma wins over line-above pragma for same target ---

    def it_prefers_same_line_pragma_over_line_above(self, caplog):
        source = '# gremlin: pardon[untestable] above reason\nx = a // 2  # gremlin: pardon[equivalent] inline reason\n'
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma'):
            result = parse_pardoned_lines(source)
        assert result == {2: ('equivalent', 'inline reason')}
        assert any('duplicate' in msg.lower() for msg in caplog.messages)

    # --- AC6: existing validation still applies to standalone pragmas ---

    def it_ignores_standalone_pragma_with_invalid_reason(self, caplog):
        source = '# gremlin: pardon[bad_code] some justification\nx = a // 2\n'
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma'):
            result = parse_pardoned_lines(source)
        assert result == {}
        assert any('bad_code' in msg for msg in caplog.messages)

    def it_ignores_standalone_pragma_with_missing_justification(self, caplog):
        source = '# gremlin: pardon[equivalent]\nx = a // 2\n'
        with caplog.at_level(logging.WARNING, logger='pytest_gremlins.instrumentation.pragma'):
            result = parse_pardoned_lines(source)
        assert result == {}
        assert any('justification' in msg.lower() for msg in caplog.messages)

    # --- Edge cases from the issue ---

    def it_pardons_decorator_line_when_pragma_above_decorator(self):
        source = '# gremlin: pardon[out_of_scope] framework boilerplate\n@app.route("/api")\ndef handler():\n    pass\n'
        result = parse_pardoned_lines(source)
        assert result == {2: ('out_of_scope', 'framework boilerplate')}

    def it_maps_two_consecutive_standalone_pragmas_each_to_their_next_line(self):
        source = '# gremlin: pardon[equivalent] first reason\n# gremlin: pardon[untestable] second reason\nx = a + b\n'
        result = parse_pardoned_lines(source)
        # First pragma (line 1) targets line 2 (another comment -- effectively wasted)
        # Second pragma (line 2) targets line 3 (actual code)
        assert result[2] == ('equivalent', 'first reason')
        assert result[3] == ('untestable', 'second reason')
        assert len(result) == 2

    def it_handles_mixed_inline_and_standalone_pragmas(self):
        source = (
            'a = 1  # gremlin: pardon[equivalent] inline first\n'
            '# gremlin: pardon[untestable] standalone second\n'
            'b = 2\n'
            'c = 3\n'
        )
        result = parse_pardoned_lines(source)
        assert result[1] == ('equivalent', 'inline first')
        assert result[3] == ('untestable', 'standalone second')
