"""UniFile -- Non-destructive Library Mode (overlay organization).

Creates a .unifile/ database in the source directory and organizes files
virtually without moving them. Files can be viewed in a virtual folder
structure and exported to a real structure on demand.
"""
import os
import json
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

from unifile.config import _APP_DATA_DIR


class VirtualLibrary:
    """Overlay organization -- classifies and tags files without moving them.

    Creates .unifile/library.sqlite in the source directory with:
    - Virtual folder assignments (category -> files)
    - Tags and metadata
    - Broken-link detection for moved/deleted files
    """

    def __init__(self):
        self._conn = None
        self._root = ""

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @property
    def root_dir(self) -> str:
        return self._root

    def open(self, directory: str) -> bool:
        """Open or create a virtual library in the given directory."""
        self._root = os.path.abspath(directory)
        db_dir = os.path.join(self._root, '.unifile')
        os.makedirs(db_dir, exist_ok=True)

        db_path = os.path.join(db_dir, 'library.sqlite')
        self._conn = sqlite3.connect(db_path)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._create_tables()
        return True

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
        self._root = ""

    def _create_tables(self):
        self._conn.executescript('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rel_path TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                extension TEXT,
                size INTEGER DEFAULT 0,
                modified_at TEXT,
                category TEXT DEFAULT '',
                virtual_folder TEXT DEFAULT '',
                confidence REAL DEFAULT 0,
                method TEXT DEFAULT '',
                description TEXT DEFAULT '',
                is_broken INTEGER DEFAULT 0,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS virtual_tags (
                file_id INTEGER,
                tag TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files(id),
                UNIQUE(file_id, tag)
            );

            CREATE TABLE IF NOT EXISTS virtual_folders (
                name TEXT PRIMARY KEY,
                parent TEXT DEFAULT '',
                color TEXT DEFAULT '#4ade80',
                file_count INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
            CREATE INDEX IF NOT EXISTS idx_files_virtual ON files(virtual_folder);
            CREATE INDEX IF NOT EXISTS idx_tags_file ON virtual_tags(file_id);
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON virtual_tags(tag);
        ''')
        self._conn.commit()

    def scan_directory(self, callback=None) -> int:
        """Scan the root directory and add new files to the library.

        Returns the number of newly added files.
        """
        count = 0
        all_files = []
        for root, dirs, files in os.walk(self._root):
            # Skip .unifile directory
            dirs[:] = [d for d in dirs if d != '.unifile']
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, self._root)
                all_files.append((full, rel, name))

        for i, (full, rel, name) in enumerate(all_files):
            existing = self._conn.execute(
                'SELECT id FROM files WHERE rel_path = ?', (rel,)
            ).fetchone()
            if existing:
                continue

            try:
                stat = os.stat(full)
                ext = os.path.splitext(name)[1].lower()
                self._conn.execute(
                    'INSERT INTO files (rel_path, filename, extension, size, modified_at) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (rel, name, ext, stat.st_size,
                     datetime.fromtimestamp(stat.st_mtime).isoformat())
                )
                count += 1
            except OSError:
                pass

            if callback and (i + 1) % 50 == 0:
                callback(i + 1, len(all_files))

        self._conn.commit()
        return count

    def assign_category(self, rel_path: str, category: str,
                        confidence: float = 0, method: str = ""):
        """Assign a category to a file (virtual folder assignment)."""
        self._conn.execute(
            'UPDATE files SET category = ?, virtual_folder = ?, '
            'confidence = ?, method = ? WHERE rel_path = ?',
            (category, category, confidence, method, rel_path)
        )
        self._conn.commit()
        self._update_folder_counts()

    def assign_batch(self, assignments: list[dict]):
        """Assign categories to multiple files.

        Each dict: {'rel_path': str, 'category': str, 'confidence': float, 'method': str}
        """
        for a in assignments:
            self._conn.execute(
                'UPDATE files SET category = ?, virtual_folder = ?, '
                'confidence = ?, method = ? WHERE rel_path = ?',
                (a['category'], a['category'],
                 a.get('confidence', 0), a.get('method', ''),
                 a['rel_path'])
            )
        self._conn.commit()
        self._update_folder_counts()

    def add_tag(self, rel_path: str, tag: str):
        """Add a tag to a file."""
        row = self._conn.execute(
            'SELECT id FROM files WHERE rel_path = ?', (rel_path,)
        ).fetchone()
        if row:
            self._conn.execute(
                'INSERT OR IGNORE INTO virtual_tags (file_id, tag) VALUES (?, ?)',
                (row[0], tag)
            )
            self._conn.commit()

    def remove_tag(self, rel_path: str, tag: str):
        """Remove a tag from a file."""
        row = self._conn.execute(
            'SELECT id FROM files WHERE rel_path = ?', (rel_path,)
        ).fetchone()
        if row:
            self._conn.execute(
                'DELETE FROM virtual_tags WHERE file_id = ? AND tag = ?',
                (row[0], tag)
            )
            self._conn.commit()

    def get_tags(self, rel_path: str) -> list[str]:
        """Get all tags for a file."""
        row = self._conn.execute(
            'SELECT id FROM files WHERE rel_path = ?', (rel_path,)
        ).fetchone()
        if not row:
            return []
        rows = self._conn.execute(
            'SELECT tag FROM virtual_tags WHERE file_id = ?', (row[0],)
        ).fetchall()
        return [r[0] for r in rows]

    def get_virtual_tree(self) -> dict:
        """Get the virtual folder structure.

        Returns: {category_name: [{'rel_path', 'filename', 'size', ...}, ...]}
        """
        tree = {}
        rows = self._conn.execute(
            'SELECT rel_path, filename, extension, size, category, confidence, method '
            'FROM files WHERE category != "" ORDER BY category, filename'
        ).fetchall()
        for rel, fname, ext, size, cat, conf, method in rows:
            if cat not in tree:
                tree[cat] = []
            tree[cat].append({
                'rel_path': rel,
                'filename': fname,
                'extension': ext,
                'size': size,
                'confidence': conf,
                'method': method,
                'full_path': os.path.join(self._root, rel),
            })
        return tree

    def get_uncategorized(self) -> list[dict]:
        """Get files that haven't been categorized yet."""
        rows = self._conn.execute(
            'SELECT rel_path, filename, extension, size FROM files '
            'WHERE category = "" OR category IS NULL ORDER BY filename'
        ).fetchall()
        return [{'rel_path': r[0], 'filename': r[1], 'extension': r[2],
                 'size': r[3]} for r in rows]

    def check_broken_links(self) -> list[dict]:
        """Find files in the library that no longer exist on disk."""
        broken = []
        rows = self._conn.execute(
            'SELECT id, rel_path, filename FROM files'
        ).fetchall()
        for fid, rel, fname in rows:
            full = os.path.join(self._root, rel)
            if not os.path.exists(full):
                broken.append({'id': fid, 'rel_path': rel, 'filename': fname})
                self._conn.execute(
                    'UPDATE files SET is_broken = 1 WHERE id = ?', (fid,))
        self._conn.commit()
        return broken

    def relink_file(self, old_rel_path: str, new_rel_path: str) -> bool:
        """Update the path for a file that was moved externally."""
        full = os.path.join(self._root, new_rel_path)
        if not os.path.exists(full):
            return False
        self._conn.execute(
            'UPDATE files SET rel_path = ?, filename = ?, is_broken = 0 '
            'WHERE rel_path = ?',
            (new_rel_path, os.path.basename(new_rel_path), old_rel_path)
        )
        self._conn.commit()
        return True

    def export_to_real_folders(self, dest_dir: str, callback=None) -> dict:
        """Export the virtual folder structure as real directories.

        Copies files into dest_dir/category_name/filename.

        Returns: {'copied': int, 'failed': int, 'skipped': int}
        """
        stats = {'copied': 0, 'failed': 0, 'skipped': 0}
        tree = self.get_virtual_tree()
        total = sum(len(files) for files in tree.values())
        done = 0

        for category, files in tree.items():
            cat_dir = os.path.join(dest_dir, category)
            os.makedirs(cat_dir, exist_ok=True)
            for f in files:
                src = f['full_path']
                dst = os.path.join(cat_dir, f['filename'])
                if not os.path.exists(src):
                    stats['skipped'] += 1
                    done += 1
                    continue
                try:
                    if os.path.exists(dst):
                        # Deduplicate name
                        base, ext = os.path.splitext(f['filename'])
                        n = 1
                        while os.path.exists(dst):
                            dst = os.path.join(cat_dir, f"{base} ({n}){ext}")
                            n += 1
                    shutil.copy2(src, dst)
                    stats['copied'] += 1
                except OSError:
                    stats['failed'] += 1
                done += 1
                if callback:
                    callback(done, total)

        return stats

    def get_stats(self) -> dict:
        """Get library statistics."""
        total = self._conn.execute('SELECT COUNT(*) FROM files').fetchone()[0]
        categorized = self._conn.execute(
            'SELECT COUNT(*) FROM files WHERE category != ""'
        ).fetchone()[0]
        broken = self._conn.execute(
            'SELECT COUNT(*) FROM files WHERE is_broken = 1'
        ).fetchone()[0]
        categories = self._conn.execute(
            'SELECT COUNT(DISTINCT category) FROM files WHERE category != ""'
        ).fetchone()[0]
        return {
            'total_files': total,
            'categorized': categorized,
            'uncategorized': total - categorized,
            'broken_links': broken,
            'categories': categories,
        }

    def search(self, query: str, limit: int = 100) -> list[dict]:
        """Search files by name, category, or tag."""
        q = f"%{query}%"
        # Search filename and category
        rows = self._conn.execute(
            'SELECT rel_path, filename, extension, size, category, confidence '
            'FROM files WHERE filename LIKE ? OR category LIKE ? '
            'ORDER BY filename LIMIT ?', (q, q, limit)
        ).fetchall()
        results = [{'rel_path': r[0], 'filename': r[1], 'extension': r[2],
                     'size': r[3], 'category': r[4], 'confidence': r[5]}
                    for r in rows]

        # Also search tags
        if len(results) < limit:
            tag_rows = self._conn.execute(
                'SELECT DISTINCT f.rel_path, f.filename, f.extension, f.size, '
                'f.category, f.confidence '
                'FROM files f JOIN virtual_tags t ON f.id = t.file_id '
                'WHERE t.tag LIKE ? LIMIT ?',
                (q, limit - len(results))
            ).fetchall()
            seen = {r['rel_path'] for r in results}
            for r in tag_rows:
                if r[0] not in seen:
                    results.append({'rel_path': r[0], 'filename': r[1],
                                    'extension': r[2], 'size': r[3],
                                    'category': r[4], 'confidence': r[5]})
        return results

    def _update_folder_counts(self):
        """Refresh virtual folder file counts."""
        self._conn.execute('DELETE FROM virtual_folders')
        rows = self._conn.execute(
            'SELECT category, COUNT(*) FROM files WHERE category != "" '
            'GROUP BY category'
        ).fetchall()
        for cat, count in rows:
            self._conn.execute(
                'INSERT OR REPLACE INTO virtual_folders (name, file_count) VALUES (?, ?)',
                (cat, count)
            )
        self._conn.commit()
