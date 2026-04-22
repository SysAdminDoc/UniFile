"""UniFile -- User-defined sort rules (CSV regex patterns).

Drop a rules CSV at %APPDATA%/UniFile/sort_rules.csv to classify folders
without AI.  Each row: category, regex_pattern

Lines starting with # are comments.  Patterns are matched case-insensitively
against the folder name.  First matching rule wins.

Set the UNIFILE_RULES_CSV environment variable to a semicolon-separated list
of additional CSV paths to layer on top of the primary rules file.
"""
import os
import re
import csv
from typing import Optional

from unifile.config import _APP_DATA_DIR


_RULES_FILE = os.path.join(_APP_DATA_DIR, 'sort_rules.csv')
_rules_cache: list | None = None  # [(compiled_regex, category, raw_pattern), ...]


def get_rules_file() -> str:
    """Return the path to the primary sort rules CSV file."""
    return _RULES_FILE


def load_rules(extra_paths: list | None = None) -> list:
    """Load all CSV rule files.  Returns [(compiled_regex, category, raw_pattern), ...]."""
    paths: list[str] = [_RULES_FILE]
    if extra_paths:
        paths.extend(extra_paths)
    env = os.environ.get('UNIFILE_RULES_CSV', '')
    if env:
        paths.extend(p.strip() for p in env.split(';') if p.strip())

    rules: list = []
    seen: set = set()
    for path in paths:
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        try:
            with open(path, encoding='utf-8', newline='') as f:
                for row in csv.reader(f):
                    if not row:
                        continue
                    cell = row[0].strip()
                    if not cell or cell.startswith('#'):
                        continue
                    if len(row) < 2:
                        continue
                    category = cell
                    pattern = row[1].strip()
                    if not pattern:
                        continue
                    try:
                        compiled = re.compile(pattern, re.IGNORECASE)
                        rules.append((compiled, category, pattern))
                    except re.error:
                        pass
        except (OSError, UnicodeDecodeError):
            pass
    return rules


def preload_csv_rules() -> None:
    """Pre-load rules into memory.  Call once at scan start for performance."""
    global _rules_cache
    _rules_cache = load_rules()


def invalidate_csv_rules_cache() -> None:
    """Invalidate the in-memory cache after edits."""
    global _rules_cache
    _rules_cache = None


def check_csv_rules(folder_name: str) -> str | None:
    """Check folder name against loaded CSV rules.  Returns first matching category or None."""
    rules = _rules_cache if _rules_cache is not None else load_rules()
    for compiled, category, _ in rules:
        if compiled.search(folder_name):
            return category
    return None


def test_rules(folder_name: str, rules: list | None = None) -> tuple | None:
    """Test folder name against rules.
    If rules is provided (list of (category, pattern) tuples), uses those;
    otherwise loads from disk.
    Returns (category, pattern) for the first match, or None.
    """
    if rules is not None:
        compiled_rules = []
        for cat, pat in rules:
            try:
                compiled_rules.append((re.compile(pat, re.IGNORECASE), cat, pat))
            except re.error:
                pass
    else:
        compiled_rules = load_rules()
    for compiled, category, raw in compiled_rules:
        if compiled.search(folder_name):
            return (category, raw)
    return None


def get_rules_for_editor() -> list:
    """Return current rules as [(category, pattern), ...] for the editor UI."""
    return [(cat, pat) for _, cat, pat in load_rules()]


def save_rules(rules_list: list) -> None:
    """Save list of (category, pattern) tuples to the primary rules CSV.

    rules_list: list of (category, pattern) tuples — comment rows are ignored.
    """
    os.makedirs(os.path.dirname(_RULES_FILE), exist_ok=True)
    with open(_RULES_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['# category', '# regex_pattern'])
        writer.writerow(['# Example: Fonts & Typography', r'\bfont(s)?\b'])
        writer.writerow(['# Example: Stock Music & Audio', r'(?:music|audio|sound|sfx)\b'])
        for category, pattern in rules_list:
            cat_str = str(category).strip()
            if not cat_str or cat_str.startswith('#'):
                continue
            writer.writerow([cat_str, str(pattern).strip()])
    invalidate_csv_rules_cache()


def rules_file_exists() -> bool:
    """Return True if the primary rules CSV file exists."""
    return os.path.exists(_RULES_FILE)
