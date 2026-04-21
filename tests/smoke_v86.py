"""Smoke test for v8.6.0 — run from repo root."""
import sys
sys.path.insert(0, '.')

from unifile.archive_inference import classify_archive_name, aggregate_archive_names

tests = [
    # Fixed infographic rule — non-motion packs should now land on 'Infographic'
    ("infographic-bundle",                  "Infographic"),
    ("business-infographic-template",       "Infographic"),
    # Motion infographic still routes to AE
    ("animated-infographic-pack",           "After Effects - Infographics & Data"),
    ("infographic-motion-template",         "After Effects - Infographics & Data"),
    # Marketplace rules
    ("creative-market-font-pack",           "Fonts & Typography"),
    ("creative-fabrica-svg-bundle",         "Cutting Machine - SVG & DXF"),
    ("design-bundles-cricut-files",         "Cutting Machine - SVG & DXF"),
    ("font-bundles-display-pack",           "Fonts & Typography"),
    ("freepik-vector-pack",                 "Clipart & Illustrations"),
    ("freepik-photo-bundle",                "Stock Photos - General"),
    ("artlist-music-pack",                  "Stock Music & Audio"),
    ("artgrid-drone-footage",               "Stock Footage - General"),
    ("placeit-mockup-bundle",               "Photoshop - Mockups"),
    # Design tool rules
    ("sketch-ui-kit-template",              "Sketch - UI Resources"),
    ("adobe-xd-dashboard-kit",              "Adobe XD - Templates"),
    ("affinity-designer-vector-pack",       "Affinity - Designer Files"),
    ("affinity-photo-retouch",              "Affinity - Photo Edits"),
    ("affinity-publisher-magazine",         "Affinity - Publisher Layouts"),
]

passed = 0
failed = []
for stem, expected in tests:
    got, conf = classify_archive_name(stem)
    ok = (got == expected)
    status = "OK  " if ok else "FAIL"
    print(f"  {status} [{conf:2d}] {stem!r} -> {got!r}" + ("" if ok else f"  (expected: {expected!r})"))
    if ok:
        passed += 1
    else:
        failed.append(stem)

print(f"\n{passed}/{len(tests)} passed")

# AE collapse
print("\nAE collapse test:")
stems = ["intro-pack", "slideshow-bundle", "transitions-pack", "lower-thirds-kit", "particles-fx"]
cat, conf, detail = aggregate_archive_names(stems)
print(f"  Result: {cat!r} ({conf})")
print(f"  Detail: {detail[:100]}")
if cat == "After Effects - Templates":
    print("  AE collapse: OK")
    passed += 1
else:
    print(f"  AE collapse: FAIL (expected 'After Effects - Templates', got {cat!r})")
    failed.append("ae-collapse")

total = len(tests) + 1
print(f"\nTotal: {passed}/{total}")
sys.exit(0 if not failed else 1)
