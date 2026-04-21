"""Category mismatch audit utility."""
import sys
sys.path.insert(0, '.')
from unifile.categories import get_all_category_names
from unifile.classifier import EXTENSION_CATEGORY_MAP, FILENAME_ASSET_MAP
from unifile.archive_inference import _RAW_RULES

cats = set(get_all_category_names())

print(f"Total categories: {len(cats)}\n")

# --- Check specific suspects ---
suspects = [
    'Calendar', 'Calendars & Planners',
    'Mockups - Devices', 'Mockups - Apparel', 'Mockups - Packaging',
    'Mockups - Branding', 'Mockups - Print', 'Mockups - Signage',
    'Photoshop - Mockups', 'Infographic', 'Infographics',
    'Backgrounds & Textures', 'Overlays & Effects', 'Banners', 'Posters',
    'AI Art & Generative', 'Vectors & SVG', 'Forms & Documents',
    '3D Printing - STL Files', 'Canva - Templates', 'Final Cut Pro - Templates',
    'Color Grading & LUTs',
]
print("=== Suspect list ===")
for s in suspects:
    status = "OK" if s in cats else "MISSING"
    print(f"  {status}: {s!r}")

# --- EXTENSION_CATEGORY_MAP ---
print("\n=== EXTENSION_CATEGORY_MAP mismatches ===")
for ext_set, cat, conf in EXTENSION_CATEGORY_MAP:
    if cat not in cats:
        print(f"  MISSING: {cat!r}")

# --- FILENAME_ASSET_MAP ---
print("\n=== FILENAME_ASSET_MAP mismatches ===")
for kws, cat, pri in FILENAME_ASSET_MAP:
    if cat not in cats:
        print(f"  MISSING: {cat!r}  (keywords: {kws[0]!r}...)")

# --- archive_inference rules ---
print("\n=== archive_inference._RAW_RULES mismatches ===")
for pat, cat, conf in _RAW_RULES:
    if cat not in cats:
        print(f"  MISSING: {cat!r}  (pattern: {pat!r})")
