"""UniFile -- Semantic / Natural Language Search using embeddings."""
import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
from collections.abc import Callable, Mapping
from typing import Any, cast

_log = logging.getLogger(__name__)

from unifile.config import (  # noqa: E402
    _APP_DATA_DIR,
    load_json_safe,
    save_json_safe,
)
from unifile.embedding_backends import (  # noqa: E402
    OnnxBackendError,
    OnnxEmbeddingBackend,
    default_onnx_model_dir,
)
from unifile.sqlite_policy import connect_sqlite  # noqa: E402

_EMBED_DB = os.path.join(_APP_DATA_DIR, 'semantic_embeddings.db')
_SEMANTIC_SETTINGS_FILE = os.path.join(_APP_DATA_DIR, 'semantic_settings.json')
_EMBEDDING_BACKENDS = {'auto', 'onnx', 'ollama'}


def load_semantic_settings(path: str = _SEMANTIC_SETTINGS_FILE) -> dict[str, Any]:
    """Load embedding backend settings with safe defaults."""
    raw = load_json_safe(path, {}, expected_type=dict)
    backend = str(raw.get('backend', 'auto')).strip().lower()
    if backend not in _EMBEDDING_BACKENDS:
        backend = 'auto'
    try:
        threshold = float(raw.get('threshold', 0.3))
    except (TypeError, ValueError):
        threshold = 0.3
    return {
        'backend': backend,
        'model': str(raw.get('model', 'nomic-embed-text')).strip() or 'nomic-embed-text',
        'onnx_model_dir': str(raw.get(
            'onnx_model_dir', default_onnx_model_dir(_APP_DATA_DIR))).strip()
            or default_onnx_model_dir(_APP_DATA_DIR),
        'onnx_provider': str(raw.get('onnx_provider', 'auto')).strip().lower() or 'auto',
        'threshold': min(0.95, max(0.05, threshold)),
    }


def save_semantic_settings(
    settings: Mapping[str, Any], path: str = _SEMANTIC_SETTINGS_FILE
) -> bool:
    """Persist only known embedding settings atomically."""
    current = load_semantic_settings(path)
    merged = dict(current)
    merged.update({key: value for key, value in settings.items() if key in current})
    normalized = load_semantic_settings_from_dict(merged)
    return bool(save_json_safe(path, normalized))


def load_semantic_settings_from_dict(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a settings mapping without reading from disk."""
    backend = str(raw.get('backend', 'auto')).strip().lower()
    if backend not in _EMBEDDING_BACKENDS:
        backend = 'auto'
    try:
        threshold = float(raw.get('threshold', 0.3))
    except (TypeError, ValueError):
        threshold = 0.3
    provider = str(raw.get('onnx_provider', 'auto')).strip().lower()
    if provider not in {'auto', 'cpu', 'cuda'}:
        provider = 'auto'
    return {
        'backend': backend,
        'model': str(raw.get('model', 'nomic-embed-text')).strip() or 'nomic-embed-text',
        'onnx_model_dir': str(raw.get(
            'onnx_model_dir', default_onnx_model_dir(_APP_DATA_DIR))).strip()
            or default_onnx_model_dir(_APP_DATA_DIR),
        'onnx_provider': provider,
        'threshold': min(0.95, max(0.05, threshold)),
    }


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

    Uses a local ONNX model when configured and available, with Ollama as the
    automatic fallback, then stores vectors in SQLite for fast cosine search.
    """

    def __init__(self, ollama_url: str = "http://localhost:11434",
                 model: str | None = None, backend: str | None = None,
                 onnx_model_dir: str | None = None,
                 onnx_provider: str | None = None) -> None:
        settings = load_semantic_settings()
        self._url = ollama_url.rstrip('/')
        self._model = model or settings['model']
        self._backend_name = (backend or settings['backend']).strip().lower()
        if self._backend_name not in _EMBEDDING_BACKENDS:
            self._backend_name = 'auto'
        self._onnx_model_dir = onnx_model_dir or settings['onnx_model_dir']
        self._onnx_provider = onnx_provider or settings['onnx_provider']
        self._conn: sqlite3.Connection | None = None
        self._available: bool | None = None
        self._onnx_backend: OnnxEmbeddingBackend | None = None
        self._onnx_checked = False
        self._backend_error = ''
        self._db_lock = threading.RLock()

    @property
    def backend_name(self) -> str:
        """Return the configured backend preference."""
        return self._backend_name

    def backend_status(self) -> dict[str, Any]:
        """Return local backend capability without probing Ollama."""
        if self._backend_name in {'auto', 'onnx'}:
            onnx = self._get_onnx_backend()
            if onnx is not None:
                return {
                    'configured': self._backend_name,
                    'active': 'onnx',
                    **onnx.status(),
                }
            if self._backend_name == 'onnx':
                return {
                    'configured': 'onnx', 'active': 'onnx', 'available': False,
                    'model_dir': self._onnx_model_dir,
                    'provider': self._onnx_provider, 'error': self._backend_error,
                }
        return {
            'configured': self._backend_name,
            'active': 'ollama',
            'available': None,
            'model': self._model,
            'error': self._backend_error,
        }

    def _connection(self) -> sqlite3.Connection:
        with self._db_lock:
            self._ensure_db()
            assert self._conn is not None
            return self._conn

    def _ensure_db(self) -> None:
        """Create/open the embedding database. Uses check_same_thread=False
        so the connection can be shared between the UI thread and workers —
        callers are responsible for serializing writes."""
        if self._conn is not None:
            return
        os.makedirs(os.path.dirname(_EMBED_DB), exist_ok=True)
        conn = connect_sqlite(_EMBED_DB, check_same_thread=False)
        self._conn = conn
        conn.execute('''CREATE TABLE IF NOT EXISTS embeddings (
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
        columns = {row[1] for row in conn.execute(
            'PRAGMA table_info(embeddings)').fetchall()}
        for name, definition in (
                ('source_type', "TEXT NOT NULL DEFAULT 'file'"),
                ('archive_path', 'TEXT'),
                ('inner_path', 'TEXT')):
            if name not in columns:
                conn.execute(
                    f'ALTER TABLE embeddings ADD COLUMN {name} {definition}')
        conn.commit()

    def _get_onnx_backend(self) -> OnnxEmbeddingBackend | None:
        if self._onnx_checked:
            return self._onnx_backend
        self._onnx_checked = True
        try:
            backend = OnnxEmbeddingBackend(
                self._onnx_model_dir,
                provider=self._onnx_provider,
            )
            if backend.is_available():
                self._onnx_backend = backend
            else:
                self._backend_error = backend.error
        except (OnnxBackendError, ValueError) as exc:
            self._backend_error = str(exc)
        return self._onnx_backend

    def _get_ollama_embedding(self, text: str) -> list[float] | None:
        """Get one embedding vector from Ollama's local HTTP endpoint."""
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
                return cast(list[float], embeddings[0])
        except (AIRequestError, Exception) as e:
            _log.debug("Embedding request failed for model %s: %s", self._model, e)
        return None

    def _get_embeddings(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a batch through ONNX or fall back to one Ollama call per text."""
        if self._backend_name in {'auto', 'onnx'}:
            onnx = self._get_onnx_backend()
            if onnx is not None:
                try:
                    return list(onnx.embed(texts))
                except Exception as exc:
                    self._backend_error = str(exc)
                    if self._backend_name == 'onnx':
                        return [None] * len(texts)
            elif self._backend_name == 'onnx':
                return [None] * len(texts)
        return [self._get_ollama_embedding(text) for text in texts]

    def _get_embedding(self, text: str) -> list[float] | None:
        """Get one vector through the configured backend chain."""
        vectors = self._get_embeddings([text])
        return vectors[0] if vectors else None

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

    @staticmethod
    def _build_search_text(filepath: str, description: str,
                           tags: list[str] | None = None) -> str:
        parts = [description]
        if tags:
            parts.append(' '.join(tags))
        parts.append(os.path.basename(filepath))
        return ' '.join(parts).strip()

    def index_file(self, filepath: str, description: str,
                   tags: list[str] | None = None) -> bool:
        """Generate and store an embedding for a file's description.

        Args:
            filepath: Absolute path to the file.
            description: Text description (AI-generated, category, etc.)
            tags: Optional tag list to include in the text.
        """
        conn = self._connection()

        # Build searchable text from all metadata
        text = self._build_search_text(filepath, description, tags)
        if not text:
            return False

        file_id = hashlib.md5(filepath.encode()).hexdigest()

        vec = self._get_embedding(text)
        if not vec:
            return False

        blob = self._pack_vector(vec)
        with self._db_lock:
            conn.execute(
                'INSERT OR REPLACE INTO embeddings '
                '(id, filepath, description, embedding, dim, source_type, archive_path, inner_path) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (file_id, filepath, text, blob, len(vec), 'file', None, None)
            )
            conn.commit()
        return True

    def index_archive_entry(self, archive_path: str, inner_path: str,
                            description: str = "", *, name: str | None = None,
                            size: int = 0, force: bool = False) -> bool:
        """Index one read-only member of an archive.

        Archive members share the container's real path but receive a stable
        compound key, so they cannot overwrite the container's normal file
        embedding or appear as mutable Tag Library entries.
        """
        conn = self._connection()
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
        with self._db_lock:
            if not force and conn.execute(
                    'SELECT 1 FROM embeddings WHERE id = ?', (member_id,)).fetchone():
                return True
        vec = self._get_embedding(text)
        if not vec:
            return False
        with self._db_lock:
            conn.execute(
                'INSERT OR REPLACE INTO embeddings '
                '(id, filepath, description, embedding, dim, source_type, archive_path, inner_path) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (member_id, archive_path, text, self._pack_vector(vec), len(vec),
                 'archive', archive_path, inner_path)
            )
            conn.commit()
        return True

    def index_archive_entries(
        self,
        entries: Any,
        callback: Callable[[int, int], None] | None = None,
        *,
        force: bool = False,
    ) -> int:
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

    def index_batch(
        self,
        items: list[dict[str, Any]],
        callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Index multiple files.

        Each item: {'filepath': str, 'description': str, 'tags': list[str]}
        callback: optional function(count, total) for progress.

        Returns: number of files indexed.
        """
        conn = self._connection()
        count = 0
        total = len(items)
        texts = [self._build_search_text(
            item['filepath'], item.get('description', ''), item.get('tags'))
            for item in items]
        vectors = self._get_embeddings(texts)
        for i, (item, text) in enumerate(zip(items, texts, strict=True)):
            vec = vectors[i] if i < len(vectors) else None
            if text and vec:
                file_id = hashlib.md5(item['filepath'].encode()).hexdigest()
                with self._db_lock:
                    conn.execute(
                        'INSERT OR REPLACE INTO embeddings '
                        '(id, filepath, description, embedding, dim, source_type, archive_path, inner_path) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (file_id, item['filepath'], text, self._pack_vector(vec), len(vec),
                         'file', None, None)
                    )
                    conn.commit()
                count += 1
            if callback:
                callback(i + 1, total)
        return count

    def search(self, query: str, limit: int = 20,
               threshold: float = 0.3, *, top_k: int | None = None) -> list[dict[str, Any]]:
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
        conn = self._connection()
        query_vec = self._get_embedding(query)
        if not query_vec:
            return []

        with self._db_lock:
            rows = conn.execute(
                'SELECT filepath, description, embedding, dim, source_type, '
                'archive_path, inner_path FROM embeddings'
            ).fetchall()

        results: list[dict[str, Any]] = []
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
        conn = self._connection()
        with self._db_lock:
            row = conn.execute('SELECT COUNT(*) FROM embeddings').fetchone()
        return row[0] if row else 0

    def remove_file(self, filepath: str) -> None:
        """Remove a file's embedding from the index."""
        conn = self._connection()
        file_id = hashlib.md5(filepath.encode()).hexdigest()
        with self._db_lock:
            conn.execute('DELETE FROM embeddings WHERE id = ?', (file_id,))
            conn.commit()

    def clear(self) -> None:
        """Clear all embeddings."""
        conn = self._connection()
        with self._db_lock:
            conn.execute('DELETE FROM embeddings')
            conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        with self._db_lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
