"""Confidence tier policy and unattended-apply safeguards."""

from unifile import profiles
from unifile.confidence import (
    AUTO_APPLY,
    SKIP,
    SUGGEST,
    ConfidenceTiers,
    confidence_tier_text,
    normalize_confidence_tiers,
)
from unifile.models import FileItem


def test_confidence_tiers_have_safe_defaults_and_boundaries():
    tiers = ConfidenceTiers()

    assert tiers.auto_apply == 90
    assert tiers.suggest == 70
    assert tiers.classify(90) == AUTO_APPLY
    assert tiers.classify(89) == SUGGEST
    assert tiers.classify(70) == SUGGEST
    assert tiers.classify(69) == SKIP
    assert confidence_tier_text(90, tiers) == "90% (Auto-apply)"


def test_confidence_tiers_normalize_invalid_values_without_reversing_order():
    tiers = normalize_confidence_tiers({"auto_apply": "20", "suggest": 80})

    assert tiers.auto_apply == 80
    assert tiers.suggest == 80
    assert normalize_confidence_tiers(None).as_dict() == {
        "auto_apply": 90,
        "suggest": 70,
    }


def test_profile_confidence_override_round_trip(tmp_path, monkeypatch):
    profile_file = tmp_path / "active-profile.json"
    monkeypatch.setattr(profiles, "_PROFILES_FILE", str(profile_file))

    assert profiles.set_confidence_tiers(
        {"auto_apply": 95, "suggest": 75}, "General Files"
    )
    assert profiles.get_confidence_tiers("General Files").as_dict() == {
        "auto_apply": 95,
        "suggest": 75,
    }
    assert profiles.get_confidence_tiers("Photo Library").as_dict() == {
        "auto_apply": 90,
        "suggest": 70,
    }


def test_prepare_auto_apply_only_selects_high_confidence_items():
    from unifile.scan_mixin import ScanMixin

    class _Combo:
        def currentIndex(self):
            return 3

    class _Host:
        OP_CAT = 1
        OP_SMART = 2
        OP_FILES = 3

        def __init__(self):
            self.cmb_op = _Combo()
            self.file_items = []
            self.cat_items = []
            self.aep_items = []
            self._confidence_tiers = ConfidenceTiers()
            self.messages = []

        def _log(self, message):
            self.messages.append(message)

    host = _Host()
    for confidence in (95, 80, 60):
        item = FileItem()
        item.category = "Documents"
        item.confidence = confidence
        item.confidence_tier = host._confidence_tiers.classify(confidence)
        host.file_items.append(item)

    selected = ScanMixin._prepare_auto_apply(host)

    assert selected == 1
    assert [item.selected for item in host.file_items] == [True, False, False]
    assert "high-confidence tier" in host.messages[0]
