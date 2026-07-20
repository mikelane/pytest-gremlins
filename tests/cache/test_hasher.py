"""Tests for content hashing functionality.

Content hashing is the foundation of incremental analysis. Files with
identical content produce identical hashes, enabling cache lookups.
"""

import hashlib

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

    def it_matches_hash_file_output_to_hash_string_for_lf_source(self, tmp_path):
        """hash_file matches hash_string for LF-encoded content.

        This equivalence is scoped to LF-encoded UTF-8 source: it does not
        claim anything about CRLF or non-UTF-8 files. See #469.
        """
        hasher = ContentHasher()
        content = 'class MyClass:\n    pass\n'
        file_path = tmp_path / 'test.py'
        file_path.write_bytes(content.encode('utf-8'))

        file_hash = hasher.hash_file(file_path)
        string_hash = hasher.hash_string(content)

        assert file_hash == string_hash

    def it_hashes_file_content_as_raw_bytes(self, tmp_path):
        """hash_file equals the SHA-256 digest of the file's raw bytes."""
        hasher = ContentHasher()
        file_path = tmp_path / 'test.py'
        file_path.write_bytes(b'class MyClass:\r\n    pass\r\n')

        result = hasher.hash_file(file_path)

        assert result == hashlib.sha256(file_path.read_bytes()).hexdigest()

    def it_hashes_crlf_and_lf_files_differently_for_same_logical_content(self, tmp_path):
        """A CRLF file and an LF file with the same logical content hash differently."""
        hasher = ContentHasher()
        logical_content = 'class MyClass:\n    pass\n'
        lf_path = tmp_path / 'lf.py'
        crlf_path = tmp_path / 'crlf.py'
        lf_path.write_bytes(logical_content.encode('utf-8'))
        crlf_path.write_bytes(logical_content.replace('\n', '\r\n').encode('utf-8'))

        assert hasher.hash_file(lf_path) != hasher.hash_file(crlf_path)

    def it_hashes_non_utf8_source_bytes(self, tmp_path):
        """hash_file hashes valid PEP 263 source without decoding it."""
        hasher = ContentHasher()
        content = b"# -*- coding: latin-1 -*-\nname = 'caf\xe9'\n"
        file_path = tmp_path / 'latin1.py'
        file_path.write_bytes(content)

        assert hasher.hash_file(file_path) == hashlib.sha256(content).hexdigest()

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


@pytest.mark.medium
class DescribeContentHasherFileErrors:
    """File I/O edge cases for ContentHasher — require real filesystem access."""

    def it_raises_is_a_directory_error_for_directories(self, tmp_path):
        """hash_file raises IsADirectoryError when given a directory."""
        hasher = ContentHasher()

        with pytest.raises(IsADirectoryError):
            hasher.hash_file(tmp_path)

    def it_hashes_empty_files(self, tmp_path):
        """hash_file returns the SHA-256 of empty bytes for an empty file."""
        hasher = ContentHasher()
        file_path = tmp_path / 'empty.py'
        file_path.write_bytes(b'')

        assert hasher.hash_file(file_path) == hashlib.sha256(b'').hexdigest()

    def it_follows_symlinks_to_target_content(self, tmp_path):
        """hash_file hashes the symlink target's content, not the link itself."""
        hasher = ContentHasher()
        target = tmp_path / 'target.py'
        target.write_bytes(b'def foo(): pass\n')
        link = tmp_path / 'link.py'
        link.symlink_to(target)

        assert hasher.hash_file(link) == hasher.hash_file(target)

    def it_hashes_utf8_bom_files_by_raw_bytes(self, tmp_path):
        """hash_file includes the UTF-8 BOM in the digest."""
        hasher = ContentHasher()
        content = b'\xef\xbb\xbfdef foo(): pass\n'
        file_path = tmp_path / 'bom.py'
        file_path.write_bytes(content)

        assert hasher.hash_file(file_path) == hashlib.sha256(content).hexdigest()


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
