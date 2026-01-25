"""Content hashing for incremental analysis.

Content hashing enables cache invalidation based on file content rather than
timestamps. Files with identical content produce identical hashes, enabling
instant cache lookups for unchanged code.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


class ContentHasher:
    """Produces content hashes for files and strings.

    Uses SHA-256 to produce deterministic hashes that uniquely identify
    content. These hashes form the cache keys for incremental analysis.

    Example:
        >>> hasher = ContentHasher()
        >>> result = hasher.hash_string('def foo(): return 42')
        >>> len(result) == 64  # SHA-256 produces 64 hex characters
        True
    """

    def hash_string(self, content: str) -> str:
        """Hash a string and return its hex digest.

        Args:
            content: The string content to hash.

        Returns:
            A 64-character hexadecimal string (SHA-256 digest).
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def hash_file(self, path: Path) -> str:
        """Hash a file's content and return its hex digest.

        Args:
            path: Path to the file to hash.

        Returns:
            A 64-character hexadecimal string (SHA-256 digest).

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        content = path.read_text(encoding='utf-8')
        return self.hash_string(content)

    def hash_files(self, paths: list[Path]) -> dict[str, str]:
        """Hash multiple files and return a mapping of path to hash.

        Args:
            paths: List of file paths to hash.

        Returns:
            Dictionary mapping string path to hex digest.
        """
        return {str(path): self.hash_file(path) for path in paths}

    def hash_combined(self, hashes: list[str]) -> str:
        """Combine multiple hashes into a single hash.

        Useful for creating composite cache keys from multiple source
        files or a combination of source and test file hashes.

        Args:
            hashes: List of hex digest strings to combine.

        Returns:
            A single 64-character hexadecimal string.
        """
        combined = ''.join(hashes)
        return self.hash_string(combined)
