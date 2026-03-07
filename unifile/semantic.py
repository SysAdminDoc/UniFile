"""UniFile -- Semantic / Natural Language Search using embeddings."""
import os
import json
import math
import hashlib
import sqlite3
from pathlib import Path

from unifile.config import _APP_DATA_DIR

_EMBED_DB = os.path.join(_APP_DATA_DIR, 'semantic_embeddings.db')


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
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
        """Create/open the embedding database."""
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(_EMBED_DB)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('''CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            filepath TEXT,
            description TEXT,
            embedding BLOB,
            dim INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        self._conn.commit()

    def _get_embedding(self, text: str) -> list[float] | None:
        """Get an embedding vector from Ollama."""
        import urllib.request
        try:
            body = json.dumps({
                'model': self._model,
                'input': text,
            }).encode()
            req = urllib.request.Request(
                f"{self._url}/api/embed",
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            embeddings = data.get('embeddings', [])
            if embeddings:
                return embeddings[0]
        except Exception:
            pass
        return None

    def is_available(self) -> bool:
        """Check if the embedding model is available."""
        if self._available is not None:
            return self._available
        try:
            vec = self._get_embedding("test")
            self._available = vec is not None and len(vec) > 0
        except Exception:
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
            'INSERT OR REPLACE INTO embeddings (id, filepath, description, embedding, dim) '
            'VALUES (?, ?, ?, ?, ?)',
            (file_id, filepath, text, blob, len(vec))
        )
        self._conn.commit()
        return True

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
               threshold: float = 0.3) -> list[dict]:
        """Natural language search across indexed files.

        Args:
            query: Natural language search query.
            limit: Max results.
            threshold: Minimum cosine similarity (0-1).

        Returns:
            List of dicts: {'filepath', 'description', 'score'}
        """
        self._ensure_db()
        query_vec = self._get_embedding(query)
        if not query_vec:
            return []

        rows = self._conn.execute(
            'SELECT filepath, description, embedding, dim FROM embeddings'
        ).fetchall()

        results = []
        for filepath, desc, blob, dim in rows:
            stored_vec = self._unpack_vector(blob, dim)
            if len(stored_vec) != len(query_vec):
                continue
            score = _cosine_similarity(query_vec, stored_vec)
            if score >= threshold:
                results.append({
                    'filepath': filepath,
                    'description': desc,
                    'score': score,
                })

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
            self._conn.close()
            self._conn = None
