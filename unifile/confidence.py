"""Confidence tiers used by review and automated scan workflows."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_AUTO_APPLY_THRESHOLD = 90
DEFAULT_SUGGEST_THRESHOLD = 70
MIN_CONFIDENCE = 0
MAX_CONFIDENCE = 100

AUTO_APPLY = "auto_apply"
SUGGEST = "suggest"
SKIP = "skip"

TIER_LABELS = {
    AUTO_APPLY: "Auto-apply",
    SUGGEST: "Suggest",
    SKIP: "Skip",
}


def _clamp(value: object, default: int) -> int:
    try:
        return max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, int(value)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ConfidenceTiers:
    """Thresholds for automated, review, and skipped classification results."""

    auto_apply: int = DEFAULT_AUTO_APPLY_THRESHOLD
    suggest: int = DEFAULT_SUGGEST_THRESHOLD

    def __post_init__(self) -> None:
        suggest = _clamp(self.suggest, DEFAULT_SUGGEST_THRESHOLD)
        auto_apply = _clamp(self.auto_apply, DEFAULT_AUTO_APPLY_THRESHOLD)
        if auto_apply < suggest:
            auto_apply = suggest
        object.__setattr__(self, "suggest", suggest)
        object.__setattr__(self, "auto_apply", auto_apply)

    def classify(self, confidence: object) -> str:
        """Return the stable machine-readable tier for a 0–100 score."""
        score = _clamp(confidence, MIN_CONFIDENCE)
        if score >= self.auto_apply:
            return AUTO_APPLY
        if score >= self.suggest:
            return SUGGEST
        return SKIP

    def as_dict(self) -> dict[str, int]:
        return {"auto_apply": self.auto_apply, "suggest": self.suggest}

    def describe(self) -> str:
        return (
            f"Auto-apply ≥ {self.auto_apply}%, "
            f"suggest {self.suggest}–{self.auto_apply - 1}%, "
            f"skip < {self.suggest}%"
        )


def normalize_confidence_tiers(value: object = None) -> ConfidenceTiers:
    """Normalize persisted profile data without allowing unsafe ordering."""
    if not isinstance(value, dict):
        return ConfidenceTiers()
    return ConfidenceTiers(
        auto_apply=value.get("auto_apply", DEFAULT_AUTO_APPLY_THRESHOLD),
        suggest=value.get("suggest", DEFAULT_SUGGEST_THRESHOLD),
    )


def confidence_tier_label(tier: str) -> str:
    """Return a human-readable label for a tier value."""
    return TIER_LABELS.get(tier, TIER_LABELS[SKIP])


def confidence_tier_text(confidence: object, tiers: ConfidenceTiers | None = None) -> str:
    """Return the compact label used in table cells and exported reports."""
    active = tiers or ConfidenceTiers()
    tier = active.classify(confidence)
    try:
        score = int(float(confidence))
    except (TypeError, ValueError):
        score = 0
    return f"{score}% ({confidence_tier_label(tier)})"
