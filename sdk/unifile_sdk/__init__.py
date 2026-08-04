"""Public, PyQt-free embedding API for UniFile's core engine."""
from __future__ import annotations

from collections.abc import Callable

from unifile import __version__
from unifile.classifier import tiered_classify
from unifile.learning import PatternLearner
from unifile.semantic import SemanticIndex
from unifile.tagging.library import TagLibrary


class Classifier:
    """Small object-oriented facade over UniFile's tiered classifier.

    The desktop application keeps the same function-based engine internally;
    this facade gives embedding hosts a stable object and optional logger.
    """

    def __init__(self, *, log_callback: Callable[[str], None] | None = None):
        self.log_callback = log_callback

    def classify(self, folder_name: str, folder_path: str | None = None) -> dict:
        """Classify a folder name and optional local folder contents."""
        return tiered_classify(folder_name, folder_path, self.log_callback)

    __call__ = classify


__all__ = [
    "Classifier",
    "PatternLearner",
    "SemanticIndex",
    "TagLibrary",
    "__version__",
]
