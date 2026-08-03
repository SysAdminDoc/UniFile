"""UniFile -- Semantic / Natural Language Search using embeddings."""
import hashlib
import json
import logging
import math
import os
import sqlite3

_log = logging.getLogger(__name__)

from unifile.config import _APP_DATA_DIR, register_sqlite_connection  # noqa: E402

_EMBED_DB = os.path.join(_APP_DATA_DIR, 'semantic_embeddings.db')


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticIndex:
    """Vector similarity search for file descriptions and tags.

    Uses Ollama's embedding endpoint to generate vectors for file descriptions,
    then stores them in SQLite for fast cosine-similarity search.
    """

    def __init__(self, ollama_url: str = "http://localhost:11434",
                 model: str = "nomic-embed-text"):
        self._url = ollama_url.rstrip('/')
        self._model = model
        self._conn = None
        self._available = None

    def _ensure_db(self):
        """Create/open the embedding database. Uses check_same_thread=False
        so the connection can be shared between the UI thread and workers —
        callers are responsible for serializing writes."""
        if self._conn is not None:
            return
        os.makedirs(os.path.dirname(_EMBED_DB), exist_ok=True)
        self._conn = sqlite3.connect(_EMBED_DB, check_same_thread=False, timeout=10)
        register_sqlite_connection(self._conn)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA busy_timeout=5000')
        self._conn.execute('''CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            filepath TEXT,
            description TEXT,
            embedding BLOB,
            dim INTEGER,
            source_type TEXT NOT NULL DEFAULT 'file',
            archive_path TEXT,
            inner_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        # Older installations predate archive-member embeddings.  Keep their
        # rows intact and add the nullable metadata in place.
        columns = {row[1] for row in self._conn.execute(
            'PRAGMA table_info(embeddings)').fetchall()}
        for name, definition in (
                ('source_type', "TEXT NOT NULL DEFAULT 'file'"),
                ('archive_path', 'TEXT'),
                ('inner_path', 'TEXT')):
            if name not in columns:
                self._conn.execute(
                    f'ALTER TABLE embeddings ADD COLUMN {name} {definition}')
        self._conn.commit()

    def _get_embedding(self, text: str) -> list[float] | None:
        """Get an embedding vector from Ollama."""
        from unifile.ai_providers import AIRequestError, ai_request
        try:
            body = json.dumps({
                'model': self._model,
                'input': text,
            }).encode()
            data = ai_request(f"{self._url}/api/embed", data=body, timeout=15,
                              retries=1)
            embeddings = data.get('embeddings', [])
            if embeddings:
                return embeddings[0]
        except (AIRequestError, Exception) as e:
            _log.debug("Embedding request failed for model %s: %s", self._model, e)
        return None

    def is_available(self) -> bool:
        """Check if the embedding model is available."""
        if self._available is not None:
            return self._available
        try:
            vec = self._get_embedding("test")
            self._available = vec is not None and len(vec) > 0
        except Exception as e:
            _log.debug("Semantic search availability check failed: %s", e)
            self._available = False
        return self._available

    def _pack_vector(self, vec: list[float]) -> bytes:
        """Pack a float vector into bytes for SQLite storage."""
        import struct
        return struct.pack(f'{len(vec)}f', *vec)

    def _unpack_vector(self, data: bytes, dim: int) -> list[float]:
        """Unpack bytes into a float vector."""
        import struct
        return list(struct.unpack(f'{dim}f', data))

    def index_file(self, filepath: str, description: str,
                   tags: list[str] | None = None) -> bool:
        """Generate and store an embedding for a file's description.

        Args:
            filepath: Absolute path to the file.
            description: Text description (AI-generated, category, etc.)
            tags: Optional tag list to include in the text.
        """
        self._ensure_db()

        # Build searchable text from all metadata
        parts = [description]
        if tags:
            parts.append(' '.join(tags))
        parts.append(os.path.basename(filepath))
        text = ' '.join(parts).strip()
        if not text:
            return False

        file_id = hashlib.md5(filepath.encode()).hexdigest()

        vec = self._get_embedding(text)
        if not vec:
            return False

        blob = self._pack_vector(vec)
        self._conn.execute(
            'INSERT OR REPLACE INTO embeddings '
            '(id, filepath, description, embedding, dim, source_type, archive_path, inner_path) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (file_id, filepath, text, blob, len(vec), 'file', None, None)
        )
        self._conn.commit()
        return True

    def index_archive_entry(self, archive_path: str, inner_path: str,
                            description: str = "", *, name: str | None = None,
                            size: int = 0, force: bool = False) -> bool:
        """Index one read-only member of an archive.

        Archive members share the container's real path but receive a stable
        compound key, so they cannot overwrite the container's normal file
        embedding or appear as mutable Tag Library entries.
        """
        self._ensure_db()
        archive_path = os.path.abspath(str(archive_path))
        inner_path = str(inner_path).replace('\\', '/').strip('/')
        if not archive_path or not inner_path:
            return False
        member_name = name or os.path.basename(inner_path)
        archive_name = os.path.basename(archive_path)
        parts = [member_name, inner_path, f"inside {archive_name}"]
        if description:
            parts.insert(0, description)
        text = ' '.join(str(part) for part in parts if part).strip()
        if not text:
            return False
        member_id = hashlib.md5(
            f"archive\\0{archive_path}\\0{inner_path}".encode()).hexdigest()
        if not force and self._conn.execute(
                'SELECT 1 FROM embeddings WHERE id = ?', (member_id,)).fetchone():
            return True
        vec = self._get_embedding(text)
        if not vec:
            return False
        self._conn.execute(
            'INSERT OR REPLACE INTO embeddings '
            '(id, filepath, description, embedding, dim, source_type, archive_path, inner_path) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (member_id, archive_path, text, self._pack_vector(vec), len(vec),
             'archive', archive_path, inner_path)
        )
        self._conn.commit()
        return True

    def index_archive_entries(self, entries, callback=None, *, force: bool = False) -> int:
        """Index archive-entry objects or dictionaries with stable metadata."""
        entries = list(entries or [])
        count = 0
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                archive_path = entry.get('archive_path', '')
                inner_path = entry.get('inner_path', '')
                name = entry.get('name')
                description = entry.get('description', '')
            else:
                archive_path = getattr(entry, 'archive_path', '')
                inner_path = getattr(entry, 'inner_path', '')
                name = getattr(entry, 'name', None)
                description = getattr(entry, 'description', '')
            if self.index_archive_entry(
                    archive_path, inner_path, description,
                    name=name, size=getattr(entry, 'size', 0), force=force):
                count += 1
            if callback:
                callback(index + 1, len(entries))
        return count

    def index_batch(self, items: list[dict], callback=None) -> int:
        """Index multiple files.

        Each item: {'filepath': str, 'description': str, 'tags': list[str]}
        callback: optional function(count, total) for progress.

        Returns: number of files indexed.
        """
        count = 0
        total = len(items)
        for i, item in enumerate(items):
            ok = self.index_file(
                item['filepath'],
                item.get('description', ''),
                item.get('tags'),
            )
            if ok:
                count += 1
            if callback:
                callback(i + 1, total)
        return count

    def search(self, query: str, limit: int = 20,
               threshold: float = 0.3, *, top_k: int | None = None) -> list[dict]:
        """Natural language search across indexed files.

        Args:
            query: Natural language search query.
            limit: Max results.
            threshold: Minimum cosine similarity (0-1).

        Returns:
            List of dicts: {'filepath', 'description', 'score'}
        """
        if top_k is not None:
            limit = top_k
        self._ensure_db()
        query_vec = self._get_embedding(query)
        if not query_vec:
            return []

        rows = self._conn.execute(
            'SELECT filepath, description, embedding, dim, source_type, '
            'archive_path, inner_path FROM embeddings'
        ).fetchall()

        results = []
        for filepath, desc, blob, dim, source_type, archive_path, inner_path in rows:
            stored_vec = self._unpack_vector(blob, dim)
            if len(stored_vec) != len(query_vec):
                continue
            score = _cosine_similarity(query_vec, stored_vec)
            if score >= threshold:
                result = {
                    'filepath': filepath,
                    'path': filepath,
                    'description': desc,
                    'score': score,
                    'source_type': source_type or 'file',
                }
                if result['source_type'] == 'archive':
                    result.update({
                        'archive_path': archive_path or filepath,
                        'inner_path': inner_path or '',
                        'name': os.path.basename(inner_path or ''),
                    })
                results.append(result)

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    def get_indexed_count(self) -> int:
        """Return number of indexed files."""
        self._ensure_db()
        row = self._conn.execute('SELECT COUNT(*) FROM embeddings').fetchone()
        return row[0] if row else 0

    def remove_file(self, filepath: str):
        """Remove a file's embedding from the index."""
        self._ensure_db()
        file_id = hashlib.md5(filepath.encode()).hexdigest()
        self._conn.execute('DELETE FROM embeddings WHERE id = ?', (file_id,))
        self._conn.commit()

    def clear(self):
        """Clear all embeddings."""
        self._ensure_db()
        self._conn.execute('DELETE FROM embeddings')
        self._conn.commit()

    def close(self):
        """Close the database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
