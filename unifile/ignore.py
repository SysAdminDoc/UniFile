"""UniFile -- .unifile_ignore file support (gitignore-style pattern matching)."""
import os
import re
import fnmatch
from pathlib import Path
from typing import Optional


class IgnoreFilter:
    """Reads .unifile_ignore files and filters paths against them.

    Supports gitignore-style patterns:
        *.tmp           - match by extension
        build/          - match directories
        !important.log  - negate (un-ignore) a pattern
        # comment       - comments
        **/node_modules - match anywhere in tree
    """

    def __init__(self):
        self._rules: list[tuple[bool, re.Pattern]] = []  # (is_negation, compiled_regex)
        self._raw_patterns: list[str] = []

    @classmethod
    def from_directory(cls, directory: str) -> "IgnoreFilter":
        """Load .unifile_ignore from a directory, walking up to find it."""
        filt = cls()
        # Check the directory itself, then parents
        d = Path(directory).resolve()
        for _ in range(20):  # max depth
            ignore_file = d / ".unifile_ignore"
            if ignore_file.is_file():
                filt.load(str(ignore_file))
                break
            parent = d.parent
            if parent == d:
                break
            d = parent
        return filt

    def load(self, filepath: str):
        """Load patterns from a .unifile_ignore file."""
        try:
            with open(filepath, encoding='utf-8') as f:
                for line in f:
                    line = line.rstrip('\n\r')
                    self._add_pattern(line)
        except (OSError, UnicodeDecodeError):
            pass

    def add_pattern(self, pattern: str):
        """Add a single pattern."""
        self._add_pattern(pattern)

    def _add_pattern(self, line: str):
        """Parse and compile a single gitignore-style pattern."""
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            return

        negation = False
        if stripped.startswith('!'):
            negation = True
            stripped = stripped[1:]

        self._raw_patterns.append(line)
        regex = self._pattern_to_regex(stripped)
        self._rules.append((negation, re.compile(regex, re.IGNORECASE)))

    @staticmethod
    def _pattern_to_regex(pattern: str) -> str:
        """Convert a gitignore glob pattern to a regex string."""
        # Handle **/ prefix (match in any directory)
        if pattern.startswith('**/'):
            pattern = pattern[3:]
            prefix = r'(?:.*[\\/])?'
        else:
            prefix = r'^(?:.*[\\/])?'

        # Handle trailing / (directory-only match)
        dir_only = pattern.endswith('/')
        if dir_only:
            pattern = pattern.rstrip('/')

        # Convert glob to regex
        parts = []
        i = 0
        while i < len(pattern):
            c = pattern[i]
            if c == '*':
                if i + 1 < len(pattern) and pattern[i + 1] == '*':
                    parts.append('.*')
                    i += 2
                    if i < len(pattern) and pattern[i] == '/':
                        i += 1
                    continue
                else:
                    parts.append(r'[^\\/]*')
            elif c == '?':
                parts.append(r'[^\\/]')
            elif c == '[':
                j = i + 1
                while j < len(pattern) and pattern[j] != ']':
                    j += 1
                parts.append(pattern[i:j + 1])
                i = j
            elif c in r'\.+^${}()|':
                parts.append('\\' + c)
            else:
                parts.append(c)
            i += 1

        result = prefix + ''.join(parts)
        if dir_only:
            result += r'[\\/]?'
        result += '$'
        return result

    def is_ignored(self, path: str, is_dir: bool = False) -> bool:
        """Check if a path should be ignored.

        Args:
            path: Relative or absolute path to check.
            is_dir: True if the path is a directory. Directory-only patterns
                    (trailing `/`) are then honored correctly.

        Returns:
            True if the path matches an ignore pattern.
        """
        if not self._rules:
            return False

        # Normalize separators and strip leading "./"
        check = path.replace('\\', '/').lstrip('./')
        # For directories, also test with a trailing slash so patterns
        # like "build/" match "build".
        check_dir = check + '/' if is_dir else check
        name = os.path.basename(check)

        ignored = False
        for negation, regex in self._rules:
            # Try matching against full path (including trailing slash for dirs)
            # and just the basename.
            if regex.search(check) or regex.search(check_dir) or regex.search(name):
                ignored = not negation
        return ignored

    def filter_paths(self, paths: list[str], base_dir: str = "") -> list[str]:
        """Return only paths that are NOT ignored."""
        if not self._rules:
            return paths
        result = []
        for p in paths:
            rel = os.path.relpath(p, base_dir) if base_dir else p
            is_dir = os.path.isdir(p)
            if not self.is_ignored(rel, is_dir):
                result.append(p)
        return result

    @property
    def patterns(self) -> list[str]:
        return list(self._raw_patterns)

    @property
    def has_rules(self) -> bool:
        return len(self._rules) > 0
