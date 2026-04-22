"""UniFile -- Adaptive Learning engine for classification improvements."""
import os
import re
import json
import threading
from collections import Counter, defaultdict
from datetime import datetime

from unifile.config import _APP_DATA_DIR

_LEARNING_DB = os.path.join(_APP_DATA_DIR, 'learning_patterns.json')


class PatternLearner:
    """Learns classification patterns from user corrections.

    Tracks:
    - Extension-to-category frequency (e.g., .psd files are usually "Design Assets")
    - Name token-to-category frequency (e.g., "invoice" -> "Finance")
    - Folder structure patterns (e.g., files under "src/" -> "Code")
    - Size range patterns (e.g., >100MB -> "Video")

    Each correction strengthens the pattern. After N confirmations,
    the pattern is used as a classification tier (between fuzzy and LLM).
    """

    MIN_CONFIDENCE_THRESHOLD = 3  # need at least N corrections before trusting a pattern
    LEARNED_CONFIDENCE = 75       # confidence score for learned classifications
    _lock = threading.Lock()

    def __init__(self):
        self._ext_patterns: dict[str, Counter] = defaultdict(Counter)
        self._token_patterns: dict[str, Counter] = defaultdict(Counter)
        self._folder_patterns: dict[str, Counter] = defaultdict(Counter)
        self._size_patterns: dict[str, Counter] = defaultdict(Counter)
        self._total_corrections = 0
        self._load()

    def _load(self):
        """Load learned patterns from disk."""
        if not os.path.isfile(_LEARNING_DB):
            return
        try:
            with open(_LEARNING_DB, encoding='utf-8') as f:
                data = json.load(f)
            self._ext_patterns = defaultdict(Counter, {
                k: Counter(v) for k, v in data.get('ext', {}).items()
            })
            self._token_patterns = defaultdict(Counter, {
                k: Counter(v) for k, v in data.get('tokens', {}).items()
            })
            self._folder_patterns = defaultdict(Counter, {
                k: Counter(v) for k, v in data.get('folders', {}).items()
            })
            self._size_patterns = defaultdict(Counter, {
                k: Counter(v) for k, v in data.get('sizes', {}).items()
            })
            self._total_corrections = data.get('total', 0)
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self):
        """Persist learned patterns to disk."""
        data = {
            'ext': {k: dict(v) for k, v in self._ext_patterns.items()},
            'tokens': {k: dict(v) for k, v in self._token_patterns.items()},
            'folders': {k: dict(v) for k, v in self._folder_patterns.items()},
            'sizes': {k: dict(v) for k, v in self._size_patterns.items()},
            'total': self._total_corrections,
            'updated': datetime.now().isoformat(),
        }
        try:
            with open(_LEARNING_DB, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def record_correction(self, filename: str, filepath: str, category: str,
                          old_category: str = ""):
        """Record a user correction to strengthen patterns."""
        with self._lock:
            self._total_corrections += 1

            # Extension pattern
            ext = os.path.splitext(filename)[1].lower()
            if ext:
                self._ext_patterns[ext][category] += 1

            # Token patterns (words from filename)
            tokens = re.findall(r'[a-zA-Z]{3,}', os.path.splitext(filename)[0].lower())
            for tok in tokens:
                self._token_patterns[tok][category] += 1

            # Folder structure pattern (parent folder name)
            parent = os.path.basename(os.path.dirname(filepath)).lower()
            if parent and parent not in ('.', ''):
                self._folder_patterns[parent][category] += 1

            # Size range pattern
            try:
                size = os.path.getsize(filepath)
                size_bucket = self._size_bucket(size)
                self._size_patterns[size_bucket][category] += 1
            except OSError:
                pass

            self._save()

    def record_batch_corrections(self, corrections: list[dict]):
        """Record multiple corrections at once.

        Each dict: {'filename': str, 'filepath': str, 'category': str}
        """
        for c in corrections:
            self.record_correction(
                c['filename'], c['filepath'], c['category'],
                c.get('old_category', ''))

    @staticmethod
    def _size_bucket(size: int) -> str:
        """Map file size to a bucket string."""
        if size < 1024:
            return "tiny"
        elif size < 100 * 1024:
            return "small"
        elif size < 1024 * 1024:
            return "medium"
        elif size < 10 * 1024 * 1024:
            return "large"
        elif size < 100 * 1024 * 1024:
            return "xlarge"
        else:
            return "huge"

    def predict(self, filename: str, filepath: str) -> dict | None:
        """Predict category based on learned patterns.

        Returns:
            dict with 'category', 'confidence', 'method', 'detail' or None
        """
        votes: Counter = Counter()
        evidence = []

        ext = os.path.splitext(filename)[1].lower()
        if ext and ext in self._ext_patterns:
            top = self._ext_patterns[ext].most_common(1)
            if top and top[0][1] >= self.MIN_CONFIDENCE_THRESHOLD:
                votes[top[0][0]] += top[0][1] * 2  # extensions get double weight
                evidence.append(f"ext:{ext}->{top[0][0]}(x{top[0][1]})")

        # Token matches
        tokens = re.findall(r'[a-zA-Z]{3,}', os.path.splitext(filename)[0].lower())
        for tok in tokens:
            if tok in self._token_patterns:
                top = self._token_patterns[tok].most_common(1)
                if top and top[0][1] >= self.MIN_CONFIDENCE_THRESHOLD:
                    votes[top[0][0]] += top[0][1]
                    evidence.append(f"token:{tok}->{top[0][0]}(x{top[0][1]})")

        # Folder structure
        parent = os.path.basename(os.path.dirname(filepath)).lower()
        if parent and parent in self._folder_patterns:
            top = self._folder_patterns[parent].most_common(1)
            if top and top[0][1] >= self.MIN_CONFIDENCE_THRESHOLD:
                votes[top[0][0]] += top[0][1] * 1.5
                evidence.append(f"folder:{parent}->{top[0][0]}(x{top[0][1]})")

        # Size pattern
        try:
            size = os.path.getsize(filepath)
            bucket = self._size_bucket(size)
            if bucket in self._size_patterns:
                top = self._size_patterns[bucket].most_common(1)
                if top and top[0][1] >= self.MIN_CONFIDENCE_THRESHOLD:
                    votes[top[0][0]] += top[0][1] * 0.5
                    evidence.append(f"size:{bucket}->{top[0][0]}(x{top[0][1]})")
        except OSError:
            pass

        if not votes:
            return None

        winner, score = votes.most_common(1)[0]
        total_evidence = sum(votes.values())
        # Calculate confidence: higher score relative to total = more confident
        raw_conf = min(95, self.LEARNED_CONFIDENCE + (score / max(1, total_evidence)) * 20)

        return {
            'category': winner,
            'confidence': raw_conf,
            'method': 'learned',
            'detail': f"Adaptive: {', '.join(evidence[:3])}",
        }

    def get_stats(self) -> dict:
        """Return learning statistics."""
        return {
            'total_corrections': self._total_corrections,
            'extension_patterns': sum(len(v) for v in self._ext_patterns.values()),
            'token_patterns': sum(len(v) for v in self._token_patterns.values()),
            'folder_patterns': sum(len(v) for v in self._folder_patterns.values()),
            'size_patterns': sum(len(v) for v in self._size_patterns.values()),
        }

    def clear(self):
        """Reset all learned patterns."""
        with self._lock:
            self._ext_patterns.clear()
            self._token_patterns.clear()
            self._folder_patterns.clear()
            self._size_patterns.clear()
            self._total_corrections = 0
            self._save()


# Module-level singleton
_learner: PatternLearner | None = None
_learner_lock = threading.Lock()


def get_learner() -> PatternLearner:
    """Get the singleton PatternLearner instance (thread-safe)."""
    global _learner
    if _learner is None:
        with _learner_lock:
            if _learner is None:
                _learner = PatternLearner()
    return _learner
