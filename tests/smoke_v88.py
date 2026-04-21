"""UniFile v8.8.0 smoke tests — archive inference, extension maps, composition heuristics."""
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__file__), '..'))
from unifile.archive_inference import aggregate_archive_names, classify_archive_name
from unifile.classifier import EXTENSION_CATEGORY_MAP

PASS = 0
FAIL = 0

def check(label, result, expected_cat, min_conf=60):
    global PASS, FAIL
    cat = result[0] if isinstance(result, tuple) else result
    conf = result[1] if isinstance(result, tuple) else 100
    ok = (cat == expected_cat and conf >= min_conf)
    status = 'OK  ' if ok else 'FAIL'
    if ok:
        PASS += 1
    else:
        FAIL += 1
        print(f"  {status} [{conf}] {label!r} -> {cat!r}  (expected {expected_cat!r})")

def infer(stem):
    return classify_archive_name(stem)

def ext_check(ext):
    """Look up an extension directly in EXTENSION_CATEGORY_MAP."""
    for exts, cat, conf in EXTENSION_CATEGORY_MAP:
        if ext in exts:
            return (cat, conf)
    return (None, 0)

print("=== Motion Array sub-typed rules ===")
check("motionarray-titles", infer("motionarray-500titles-pack"), "After Effects - Titles & Typography")
check("motionarray-transitions", infer("motionarray-handy-transitions"), "After Effects - Transitions")
check("motionarray-logo", infer("motionarray-logo-reveals-bundle"), "After Effects - Logo Reveals")
check("motionarray-slideshow", infer("motionarray-photo-slideshow"), "After Effects - Slideshows")
check("motionarray-lower-third", infer("motionarray-lower-thirds-pack"), "After Effects - Lower Thirds")
check("motionarray-mogrt", infer("motionarray-mogrt-pack"), "Premiere Pro - Templates")
check("motionarray-lut", infer("motionarray-cinematic-lut-pack"), "Color Grading & LUTs")
check("motionarray-generic", infer("motionarray-awesome-template"), "After Effects - Templates")

print("\n=== Envato Elements rules ===")
check("envato-mogrt", infer("envato-elements-mogrt-collection"), "Premiere Pro - Templates")
check("envato-transitions", infer("elements-envato-transition-pack"), "After Effects - Transitions")
check("envato-fonts", infer("envato-elements-font-family"), "Fonts & Typography")
check("envato-mockups", infer("envato-elements-mockup-bundle"), "Photoshop - Mockups")
check("envato-stock-photo", infer("envato-elements-stock-photos"), "Stock Photos - General")
check("envato-generic", infer("envato-elements-design-pack"), "After Effects - Templates")

print("\n=== Shutterstock / Getty / iStock rules ===")
check("shutterstock-footage", infer("shutterstock-aerial-footage-4k"), "Stock Footage - General")
check("shutterstock-music", infer("shutterstock-background-music"), "Stock Music & Audio")
check("shutterstock-generic", infer("shutterstock-business-photos"), "Stock Photos - General")
check("getty-generic", infer("gettyimages-corporate-photos"), "Stock Photos - General")
check("istock-generic", infer("istockphoto-nature-collection"), "Stock Photos - General")

print("\n=== UI8 / Gumroad / ArtStation / Iconscout rules ===")
check("ui8-kit", infer("ui8-component-kit"), "UI & UX Design")
check("ui8-template", infer("ui8-dashboard-template"), "UI & UX Design")
check("gumroad-font", infer("gumroad-hand-drawn-font"), "Fonts & Typography")
check("gumroad-brush", infer("gumroad-procreate-brush-set"), "Photoshop - Brushes")
check("gumroad-svg", infer("gumroad-svg-icon-pack"), "Cutting Machine - SVG & DXF")
check("gumroad-generic", infer("gumroad-design-resource-bundle"), "Clipart & Illustrations")
check("iconscout-icons", infer("iconscout-flat-icon-set"), "Icons & Symbols")
check("artstation-texture", infer("artstation-pbr-texture-pack"), "3D - Materials & Textures")
check("artstation-model", infer("artstation-3d-model-collection"), "3D - Models & Objects")
check("artstation-brush", infer("artstation-photoshop-brush-set"), "Photoshop - Brushes")

print("\n=== Premiere Pro sub-typed archive rules ===")
check("pr-transition", infer("premiere-pro-smooth-transitions"), "Premiere Pro - Transitions")
check("handy-seamless", infer("handy-seamless-transitions-v5"), "Premiere Pro - Transitions")
check("pr-title", infer("premiere-pro-title-pack"), "Premiere Pro - Titles & Text")
check("pr-lower-third", infer("premiere-lower-third-pack"), "Premiere Pro - Titles & Text")
check("pr-lut", infer("premiere-pro-lut-color-pack"), "Premiere Pro - LUTs & Color")
check("pr-preset", infer("premiere-pro-effect-presets"), "Premiere Pro - Presets & Effects")
check("pr-sound", infer("premiere-sfx-sound-pack"), "Premiere Pro - Sound Design")

print("\n=== Premiere Pro collapse ===")
pr_stems = [
    "premiere-smooth-transitions",
    "premiere-pro-title-text",
    "premiere-lower-third-animated",
]
pr_result = aggregate_archive_names(pr_stems)
print(f"  PR collapse result: {pr_result[0]!r} ({pr_result[1]})")
check("pr-collapse", pr_result, "Premiere Pro - Templates", min_conf=80)

print("\n=== New extension mappings ===")
check("glb", ext_check('.glb'), "3D - Models & Objects")
check("gltf", ext_check('.gltf'), "3D - Models & Objects")
check("lottie", ext_check('.lottie'), "Animated Icons")
check("bmpr", ext_check('.bmpr'), "UI & UX Design")
check("rp", ext_check('.rp'), "UI & UX Design")
check("vsdx", ext_check('.vsdx'), "Forms & Documents")
check("sla", ext_check('.sla'), "Flyers & Print")
check("pxm", ext_check('.pxm'), "Clipart & Illustrations")
check("splinecode", ext_check('.splinecode'), "UI & UX Design")
check("otc", ext_check('.otc'), "Fonts & Typography")
check("ttc", ext_check('.ttc'), "Fonts & Typography")

print(f"\n{PASS + FAIL} tests | {PASS} passed | {FAIL} failed")
if FAIL:
    sys.exit(1)

