"""Category reference consistency.

Guards against drift between the canonical category list (`categories.py`)
and the various rule tables that assign into it. Replaces the manual
`tests/check_cats.py` utility.

If a rule ever references a category that no longer exists in
`get_all_category_names()`, the classifier silently emits an orphan label
that no downstream UI knows how to render. This test catches that at CI time.
"""

from unifile.archive_inference import _RAW_RULES
from unifile.categories import get_all_category_names
from unifile.classifier import EXTENSION_CATEGORY_MAP, FILENAME_ASSET_MAP


def test_extension_category_map_targets_exist():
    cats = set(get_all_category_names())
    missing = [cat for _exts, cat, _conf in EXTENSION_CATEGORY_MAP if cat not in cats]
    assert not missing, f"EXTENSION_CATEGORY_MAP references missing categories: {sorted(set(missing))}"


def test_filename_asset_map_targets_exist():
    cats = set(get_all_category_names())
    missing = [
        (cat, kws[0] if kws else "?")
        for kws, cat, _pri in FILENAME_ASSET_MAP
        if cat not in cats
    ]
    assert not missing, f"FILENAME_ASSET_MAP references missing categories: {missing}"


def test_archive_inference_raw_rules_targets_exist():
    cats = set(get_all_category_names())
    missing = [(cat, pat) for pat, cat, _conf in _RAW_RULES if cat not in cats]
    assert not missing, f"archive_inference._RAW_RULES references missing categories: {missing}"
