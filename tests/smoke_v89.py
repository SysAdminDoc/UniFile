"""UniFile v8.9.0 smoke tests — AI art platforms, 3D marketplaces, game marketplaces,
music production marketplaces, new extensions, LUT fix, composition heuristics."""
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


print("=== LUT extension fix (.cube/.3dl/.lut -> Color Grading & LUTs) ===")
check(".cube -> Color Grading & LUTs", ext_check('.cube'), "Color Grading & LUTs")
check(".3dl  -> Color Grading & LUTs", ext_check('.3dl'),  "Color Grading & LUTs")
check(".lut  -> Color Grading & LUTs", ext_check('.lut'),  "Color Grading & LUTs")

print("\n=== AI art platform archive rules ===")
check("civitai lora",       infer("civitai-sdxl-lora-pack-v3"),           "AI Art & Generative")
check("civitai checkpoint", infer("civitai-realistic-vision-checkpoint"),  "AI Art & Generative")
check("civitai generic",    infer("civitai-awesome-model"),                "AI Art & Generative")
check("hugging face lora",  infer("hugging-face-sdxl-lora-collection"),    "AI Art & Generative")
check("hugging face model", infer("huggingface-stable-diffusion-model"),   "AI Art & Generative")

print("\n=== 3D marketplace archive rules ===")
check("turbosquid character", infer("turbosquid-character-rigged-3d"),     "3D - Models & Objects")
check("turbosquid vehicle",   infer("turbosquid-sports-car-vehicle"),       "3D - Models & Objects")
check("turbosquid generic",   infer("turbosquid-bundle-collection"),        "3D - Models & Objects")
check("cgtrader model",       infer("cgtrader-lowpoly-character-model"),    "3D - Models & Objects")
check("cgtrader scene",       infer("cgtrader-interior-scene-pack"),        "3D - Models & Objects")
check("cgtrader generic",     infer("cgtrader-3d-assets-vol2"),             "3D - Models & Objects")
check("sketchfab model",      infer("sketchfab-animated-model-pack"),       "3D - Models & Objects")
check("sketchfab generic",    infer("sketchfab-scenes-collection"),         "3D - Models & Objects")
check("kitbash3d kit",        infer("kitbash3d-neo-city-kit"),              "3D - Models & Objects")
check("kitbash bundle",       infer("kit-bash-fantasy-bundle"),             "3D - Models & Objects")
check("daz3d character",      infer("daz3d-genesis-character-pack"),        "3D")
check("renderosity prop",     infer("renderosity-scene-prop-set"),          "3D")
check("poser generic",        infer("poser-figure-pack-v1"),                "3D")
check("poly haven",           infer("poly-haven-hdri-environments"),        "3D - Materials & Textures")
check("hdri haven",           infer("hdri-haven-outdoor-pack"),             "3D - Materials & Textures")
check("ambientcg",            infer("ambientcg-pbr-materials-pack"),        "3D - Materials & Textures")
check("substance painter",    infer("substance-painter-material-pack"),     "3D - Materials & Textures")
check("substance designer",   infer("substance-designer-texture-bundle"),   "3D - Materials & Textures")
check("sbsar material",       infer("sbsar-stone-material-pack"),           "3D - Materials & Textures")
check("hdri pack",            infer("studio-hdri-environment-pack-vol3"),   "3D - Materials & Textures")
check("fab unreal asset",     infer("fab-marketplace-asset-unreal"),        "Unreal Engine - Assets")
check("fab ue5 material",     infer("fab-material-pack-ue5"),               "Unreal Engine - Assets")

print("\n=== Game asset marketplace archive rules ===")
check("itch.io tileset",  infer("itch-io-pixel-tileset-pack"),    "Game Assets & Sprites")
check("itch.io asset",    infer("itchio-game-asset-bundle"),      "Game Assets & Sprites")
check("opengameart",      infer("opengameart-sprites-collection"), "Game Assets & Sprites")
check("kenney pack",      infer("kenney-ui-sprite-pack"),         "Game Assets & Sprites")
check("rpg maker tileset",infer("rpg-maker-tileset-forest"),      "Game Assets & Sprites")

print("\n=== Music production marketplace archive rules ===")
check("loopmasters sample", infer("loopmasters-deep-house-sample-pack"), "Stock Music & Audio")
check("loopmasters generic",infer("loopmasters-collection-vol5"),        "Stock Music & Audio")
check("native instruments", infer("native-instruments-komplete-library"),"Music Production - Presets")
check("ni komplete preset", infer("ni-komplete-expansion-pack"),         "Music Production - Presets")
check("spitfire audio",     infer("spitfire-audio-strings-expansion"),   "Music Production - Presets")
check("spitfire library",   infer("spitfire-symphonic-instrument-pack"), "Music Production - Presets")
check("adsr sample pack",   infer("adsr-sounds-sample-pack"),            "Stock Music & Audio")
check("samples from mars",  infer("samples-from-mars-drumbox-pack"),     "Stock Music & Audio")

print("\n=== New extension mappings ===")
check(".cr3  -> Photography - RAW Files",      ext_check('.cr3'),   "Photography - RAW Files")
check(".exr  -> 3D - Materials & Textures",    ext_check('.exr'),   "3D - Materials & Textures")
check(".sbs  -> 3D - Materials & Textures",    ext_check('.sbs'),   "3D - Materials & Textures")
check(".sbsar-> 3D - Materials & Textures",    ext_check('.sbsar'), "3D - Materials & Textures")
check(".ztl  -> 3D",                           ext_check('.ztl'),   "3D")
check(".usd  -> 3D - Models & Objects",        ext_check('.usd'),   "3D - Models & Objects")
check(".usdz -> 3D - Models & Objects",        ext_check('.usdz'),  "3D - Models & Objects")
check(".sf2  -> Music Production - Presets",   ext_check('.sf2'),   "Music Production - Presets")
check(".sfz  -> Music Production - Presets",   ext_check('.sfz'),   "Music Production - Presets")
check(".nki  -> Music Production - Presets",   ext_check('.nki'),   "Music Production - Presets")
check(".nkx  -> Music Production - Presets",   ext_check('.nkx'),   "Music Production - Presets")
check(".ptx  -> Music Production - DAW Projects", ext_check('.ptx'),"Music Production - DAW Projects")
check(".cpr  -> Music Production - DAW Projects", ext_check('.cpr'),"Music Production - DAW Projects")
check(".xcf  -> Clipart & Illustrations",      ext_check('.xcf'),   "Clipart & Illustrations")

print(f"\n{PASS + FAIL} tests | {PASS} passed | {FAIL} failed")
if FAIL:
    sys.exit(1)
