"""Tests for content hashing functionality.

Content hashing is the foundation of incremental analysis. Files with
identical content produce identical hashes, enabling cache lookups.
"""

import pytest

from pytest_gremlins.cache.hasher import ContentHasher


@pytest.mark.small
class DescribeContentHasher:
    """Tests for ContentHasher class."""

    def it_returns_hex_digest_from_hash_string(self):
        """hash_string returns a hexadecimal string."""
        hasher = ContentHasher()

        result = hasher.hash_string('hello world')

        assert isinstance(result, str)
        assert all(c in '0123456789abcdef' for c in result)

    def it_produces_deterministic_hash_strings(self):
        """Same content produces same hash."""
        hasher = ContentHasher()
        content = 'def foo(): return 42'

        hash1 = hasher.hash_string(content)
        hash2 = hasher.hash_string(content)

        assert hash1 == hash2

    def it_produces_different_hash_strings_for_different_content(self):
        """Different content produces different hashes."""
        hasher = ContentHasher()

        hash1 = hasher.hash_string('def foo(): return 42')
        hash2 = hasher.hash_string('def foo(): return 43')

        assert hash1 != hash2

    def it_produces_different_hashes_for_whitespace_differences(self):
        """Whitespace changes produce different hashes."""
        hasher = ContentHasher()

        hash1 = hasher.hash_string('def foo():\n    return 42')
        hash2 = hasher.hash_string('def foo():\n  return 42')

        assert hash1 != hash2

    def it_produces_single_hash_from_combined_inputs(self):
        """hash_combined combines multiple hashes into one."""
        hasher = ContentHasher()
        hashes = ['abc123', 'def456', 'ghi789']

        result = hasher.hash_combined(hashes)

        assert isinstance(result, str)
        assert len(result) == 64

    def it_produces_different_combined_hashes_for_different_orderings(self):
        """Order of hashes affects combined hash."""
        hasher = ContentHasher()
        hashes1 = ['abc123', 'def456']
        hashes2 = ['def456', 'abc123']

        result1 = hasher.hash_combined(hashes1)
        result2 = hasher.hash_combined(hashes2)

        assert result1 != result2


@pytest.mark.medium
class DescribeContentHasherFileIO:
    """File I/O tests for ContentHasher — require real filesystem access."""

    def it_reads_and_hashes_file_content(self, tmp_path):
        """hash_file reads file content and returns hash."""
        hasher = ContentHasher()
        file_path = tmp_path / 'test.py'
        file_path.write_text('def bar(): pass')

        result = hasher.hash_file(file_path)

        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 produces 64 hex characters

    def it_matches_hash_file_output_to_hash_string(self, tmp_path):
        """hash_file produces same result as hash_string for same content."""
        hasher = ContentHasher()
        content = 'class MyClass:\n    pass\n'
        file_path = tmp_path / 'test.py'
        file_path.write_text(content)

        file_hash = hasher.hash_file(file_path)
        string_hash = hasher.hash_string(content)

        assert file_hash == string_hash

    def it_raises_for_missing_file(self, tmp_path):
        """hash_file raises FileNotFoundError for missing files."""
        hasher = ContentHasher()
        missing_path = tmp_path / 'nonexistent.py'

        with pytest.raises(FileNotFoundError):
            hasher.hash_file(missing_path)

    def it_hashes_multiple_files(self, tmp_path):
        """hash_files returns a dict of path to hash."""
        hasher = ContentHasher()
        file1 = tmp_path / 'a.py'
        file2 = tmp_path / 'b.py'
        file1.write_text('def a(): pass')
        file2.write_text('def b(): pass')

        result = hasher.hash_files([file1, file2])

        assert len(result) == 2
        assert str(file1) in result
        assert str(file2) in result
        assert result[str(file1)] != result[str(file2)]


@pytest.mark.small
class DescribeContentHasherEdgeCases:
    """Tests for edge cases in ContentHasher."""

    def it_hash_string_returns_64_character_hex_digest(self):
        """hash_string returns a 64-character hex digest (SHA-256)."""
        hasher = ContentHasher()

        result = hasher.hash_string('hello world')

        assert len(result) == 64
        assert all(c in '0123456789abcdef' for c in result)

    def it_hash_string_of_empty_string_returns_valid_hash(self):
        """hash_string('') returns a valid 64-char hex digest."""
        hasher = ContentHasher()

        result = hasher.hash_string('')

        assert len(result) == 64
        assert all(c in '0123456789abcdef' for c in result)

    def it_hash_files_with_empty_list_returns_empty_dict(self):
        """hash_files([]) returns {}."""
        hasher = ContentHasher()

        result = hasher.hash_files([])

        assert result == {}

    def it_hash_combined_with_single_element_equals_hash_string(self):
        """hash_combined([h]) equals hash_string(h)."""
        hasher = ContentHasher()
        input_hash = 'abc123def456'  # pragma: allowlist secret

        assert hasher.hash_combined([input_hash]) == hasher.hash_string(input_hash)
