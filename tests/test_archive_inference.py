"""Archive-inference parameterized regression tests.

Consolidates the legacy `tests/smoke_v86.py` … `tests/smoke_v89.py` manual
scripts (v8.6–v8.9 feature drops) into a single pytest-native file so the
coverage stays part of the default suite instead of languishing as exit-code
smoke scripts that nobody runs.

Each block below corresponds to a smoke-script section; parametrize IDs use
the historical labels so failures remain greppable against CHANGELOG entries.
"""

import pytest

from unifile.archive_inference import (
    aggregate_archive_names,
    classify_archive_name,
)
from unifile.classifier import EXTENSION_CATEGORY_MAP


def _infer(stem):
    return classify_archive_name(stem)


def _ext_lookup(ext):
    """Look up an extension directly in EXTENSION_CATEGORY_MAP."""
    for exts, cat, conf in EXTENSION_CATEGORY_MAP:
        if ext in exts:
            return (cat, conf)
    return (None, 0)


# ── v8.6: marketplace & design tool archive rules ──────────────────────────────
V86_CASES = [
    # Fixed infographic rule — non-motion packs should now land on 'Infographic'
    ("infographic-bundle", "Infographic"),
    ("business-infographic-template", "Infographic"),
    # Motion infographic still routes to AE
    ("animated-infographic-pack", "After Effects - Infographics & Data"),
    ("infographic-motion-template", "After Effects - Infographics & Data"),
    # Marketplace rules
    ("creative-market-font-pack", "Fonts & Typography"),
    ("creative-fabrica-svg-bundle", "Cutting Machine - SVG & DXF"),
    ("design-bundles-cricut-files", "Cutting Machine - SVG & DXF"),
    ("font-bundles-display-pack", "Fonts & Typography"),
    ("freepik-vector-pack", "Clipart & Illustrations"),
    ("freepik-photo-bundle", "Stock Photos - General"),
    ("artlist-music-pack", "Stock Music & Audio"),
    ("artgrid-drone-footage", "Stock Footage - General"),
    ("placeit-mockup-bundle", "Photoshop - Mockups"),
    # Design tool rules
    ("sketch-ui-kit-template", "Sketch - UI Resources"),
    ("adobe-xd-dashboard-kit", "Adobe XD - Templates"),
    ("affinity-designer-vector-pack", "Affinity - Designer Files"),
    ("affinity-photo-retouch", "Affinity - Photo Edits"),
    ("affinity-publisher-magazine", "Affinity - Publisher Layouts"),
]


@pytest.mark.parametrize("stem,expected", V86_CASES, ids=[c[0] for c in V86_CASES])
def test_v86_archive_rules(stem, expected):
    cat, conf = _infer(stem)
    assert cat == expected, f"{stem!r} -> {cat!r} (expected {expected!r})"


def test_v86_ae_collapse():
    """5 AE subcategories should collapse to 'After Effects - Templates'."""
    stems = [
        "intro-pack", "slideshow-bundle", "transitions-pack",
        "lower-thirds-kit", "particles-fx",
    ]
    cat, conf, _detail = aggregate_archive_names(stems)
    assert cat == "After Effects - Templates"


# ── v8.7: FCP, Canva, Filmora, Pond5, Storyblocks, audio/AEJuice ──────────────
V87_CASES = [
    # Final Cut Pro
    ("final-cut-pro-title-pack", "Final Cut Pro - Templates", 70),
    ("fcpx-transition-bundle", "Final Cut Pro - Templates", 70),
    ("final-cut-effects-vol2", "Final Cut Pro - Templates", 70),
    ("fcpx-plugin-collection", "Final Cut Pro - Templates", 70),
    # Canva
    ("canva-social-media-templates", "Canva - Templates", 70),
    ("canva-flyer-design-bundle", "Canva - Templates", 70),
    ("canva-presentation-pack", "Canva - Templates", 70),
    ("canva-logo-kit", "Canva - Templates", 70),
    # Filmora — rerouted to AE templates (the Filmora categories aren't first-class)
    ("filmora-title-templates", "After Effects - Templates", 70),
    ("wondershare-filmora-effects", "After Effects - Templates", 70),
    # Pond5
    ("pond5-sfx-pack", "Sound Effects & SFX", 70),
    ("pond5-drone-footage", "Stock Footage - General", 70),
    ("pond5-motion-template", "After Effects - Templates", 70),
    ("pond5-ambient-music", "Stock Music & Audio", 70),
    # Storyblocks / Videoblocks
    ("storyblocks-footage-bundle", "Stock Footage - General", 70),
    ("videoblocks-music-pack", "Stock Music & Audio", 70),
    ("storyblocks-motion-graphics", "After Effects - Templates", 70),
    # Audio sources
    ("epidemic-sound-collection", "Stock Music & Audio", 70),
    ("looperman-drum-loops", "Stock Music & Audio", 70),
    ("splice-sample-pack-vol3", "Stock Music & Audio", 70),
    ("zapsplat-sfx-library", "Sound Effects & SFX", 70),
    ("soundsnap-effects-bundle", "Sound Effects & SFX", 70),
    # AEJuice / MotionBro / Mixkit
    ("aejuice-starter-pack", "After Effects - Templates", 70),
    ("motionbro-extension-pack", "After Effects - Templates", 70),
    ("mixkit-music-pack", "Stock Music & Audio", 70),
    ("mixkit-video-clips", "Stock Footage - General", 70),
    ("mixkit-ae-template", "After Effects - Templates", 70),
    # Numeric Envato ID extended subcategories
    ("12345678-particle-fx-pack", "After Effects - Particles & FX", 70),
    ("23456789-character-animation-rig", "After Effects - Character Animation", 70),
    ("34567890-lyric-video-template", "After Effects - Lyric Video", 70),
    ("45678901-hud-elements-pack", "After Effects - HUD & UI", 70),
    ("56789012-countdown-timer", "After Effects - Countdown & Timer", 70),
    ("67890123-logo-mockup-pack", "Photoshop - Mockups", 70),
    ("78901234-business-card-template", "Business Cards", 70),
    ("89012345-resume-cv-pack", "Resume & CV", 70),
    ("90123456-logo-design-kit", "Logo & Identity", 70),
    ("12309876-presentation-template", "Presentations & PowerPoint", 70),
]


@pytest.mark.parametrize("stem,expected,min_conf", V87_CASES, ids=[c[0] for c in V87_CASES])
def test_v87_archive_rules(stem, expected, min_conf):
    cat, conf = _infer(stem)
    assert cat == expected and conf >= min_conf, (
        f"{stem!r} -> {cat!r} [{conf}] (expected {expected!r} >= {min_conf})"
    )


def test_v87_photoshop_collapse():
    """Multiple Photoshop subcategories should collapse to 'Photoshop - Templates & Composites'."""
    stems = [
        "photoshop-actions-collection-vol1",
        "photoshop-brushes-mega-pack",
        "photoshop-styles-and-effects",
        "photoshop-actions-pro-bundle",
        "photoshop-brushes-watercolor",
    ]
    cat, conf, _detail = aggregate_archive_names(stems)
    assert cat == "Photoshop - Templates & Composites" and conf >= 70


# ── v8.8: Motion Array, Envato Elements, Shutterstock, UI8, PR sub-typed ─────
V88_CASES = [
    # Motion Array sub-typed
    ("motionarray-500titles-pack", "After Effects - Titles & Typography", 60),
    ("motionarray-handy-transitions", "After Effects - Transitions", 60),
    ("motionarray-logo-reveals-bundle", "After Effects - Logo Reveals", 60),
    ("motionarray-photo-slideshow", "After Effects - Slideshows", 60),
    ("motionarray-lower-thirds-pack", "After Effects - Lower Thirds", 60),
    ("motionarray-mogrt-pack", "Premiere Pro - Templates", 60),
    ("motionarray-cinematic-lut-pack", "Color Grading & LUTs", 60),
    ("motionarray-awesome-template", "After Effects - Templates", 60),
    # Envato Elements
    ("envato-elements-mogrt-collection", "Premiere Pro - Templates", 60),
    ("elements-envato-transition-pack", "After Effects - Transitions", 60),
    ("envato-elements-font-family", "Fonts & Typography", 60),
    ("envato-elements-mockup-bundle", "Photoshop - Mockups", 60),
    ("envato-elements-stock-photos", "Stock Photos - General", 60),
    ("envato-elements-design-pack", "After Effects - Templates", 60),
    # Shutterstock / Getty / iStock
    ("shutterstock-aerial-footage-4k", "Stock Footage - General", 60),
    ("shutterstock-background-music", "Stock Music & Audio", 60),
    ("shutterstock-business-photos", "Stock Photos - General", 60),
    ("gettyimages-corporate-photos", "Stock Photos - General", 60),
    ("istockphoto-nature-collection", "Stock Photos - General", 60),
    # UI8 / Gumroad / ArtStation / Iconscout
    ("ui8-component-kit", "UI & UX Design", 60),
    ("ui8-dashboard-template", "UI & UX Design", 60),
    ("gumroad-hand-drawn-font", "Fonts & Typography", 60),
    ("gumroad-procreate-brush-set", "Photoshop - Brushes", 60),
    ("gumroad-svg-icon-pack", "Cutting Machine - SVG & DXF", 60),
    ("gumroad-design-resource-bundle", "Clipart & Illustrations", 60),
    ("iconscout-flat-icon-set", "Icons & Symbols", 60),
    ("artstation-pbr-texture-pack", "3D - Materials & Textures", 60),
    ("artstation-3d-model-collection", "3D - Models & Objects", 60),
    ("artstation-photoshop-brush-set", "Photoshop - Brushes", 60),
    # Premiere Pro sub-typed
    ("premiere-pro-smooth-transitions", "Premiere Pro - Transitions", 60),
    ("handy-seamless-transitions-v5", "Premiere Pro - Transitions", 60),
    ("premiere-pro-title-pack", "Premiere Pro - Titles & Text", 60),
    ("premiere-lower-third-pack", "Premiere Pro - Titles & Text", 60),
    ("premiere-pro-lut-color-pack", "Premiere Pro - LUTs & Color", 60),
    ("premiere-pro-effect-presets", "Premiere Pro - Presets & Effects", 60),
    ("premiere-sfx-sound-pack", "Premiere Pro - Sound Design", 60),
]


@pytest.mark.parametrize("stem,expected,min_conf", V88_CASES, ids=[c[0] for c in V88_CASES])
def test_v88_archive_rules(stem, expected, min_conf):
    cat, conf = _infer(stem)
    assert cat == expected and conf >= min_conf, (
        f"{stem!r} -> {cat!r} [{conf}] (expected {expected!r} >= {min_conf})"
    )


def test_v88_premiere_collapse():
    """Mixed Premiere subcategories should collapse to 'Premiere Pro - Templates'."""
    stems = [
        "premiere-smooth-transitions",
        "premiere-pro-title-text",
        "premiere-lower-third-animated",
    ]
    cat, conf, _detail = aggregate_archive_names(stems)
    assert cat == "Premiere Pro - Templates" and conf >= 80


V88_EXTENSIONS = [
    (".glb", "3D - Models & Objects"),
    (".gltf", "3D - Models & Objects"),
    (".lottie", "Animated Icons"),
    (".bmpr", "UI & UX Design"),
    (".rp", "UI & UX Design"),
    (".vsdx", "Forms & Documents"),
    (".sla", "Flyers & Print"),
    (".pxm", "Clipart & Illustrations"),
    (".splinecode", "UI & UX Design"),
    (".otc", "Fonts & Typography"),
    (".ttc", "Fonts & Typography"),
]


@pytest.mark.parametrize("ext,expected", V88_EXTENSIONS, ids=[c[0] for c in V88_EXTENSIONS])
def test_v88_extension_mappings(ext, expected):
    cat, _conf = _ext_lookup(ext)
    assert cat == expected, f"{ext!r} -> {cat!r} (expected {expected!r})"


# ── v8.9: AI art, 3D marketplaces, game/music marketplaces, LUT fix ──────────
V89_LUT_FIX = [
    (".cube", "Color Grading & LUTs"),
    (".3dl", "Color Grading & LUTs"),
    (".lut", "Color Grading & LUTs"),
]


@pytest.mark.parametrize("ext,expected", V89_LUT_FIX, ids=[c[0] for c in V89_LUT_FIX])
def test_v89_lut_extensions(ext, expected):
    cat, _conf = _ext_lookup(ext)
    assert cat == expected


V89_AI_ART = [
    ("civitai-sdxl-lora-pack-v3", "AI Art & Generative"),
    ("civitai-realistic-vision-checkpoint", "AI Art & Generative"),
    ("civitai-awesome-model", "AI Art & Generative"),
    ("hugging-face-sdxl-lora-collection", "AI Art & Generative"),
    ("huggingface-stable-diffusion-model", "AI Art & Generative"),
]


@pytest.mark.parametrize("stem,expected", V89_AI_ART, ids=[c[0] for c in V89_AI_ART])
def test_v89_ai_art_rules(stem, expected):
    cat, conf = _infer(stem)
    assert cat == expected and conf >= 60


V89_3D_MARKETS = [
    ("turbosquid-character-rigged-3d", "3D - Models & Objects"),
    ("turbosquid-sports-car-vehicle", "3D - Models & Objects"),
    ("turbosquid-bundle-collection", "3D - Models & Objects"),
    ("cgtrader-lowpoly-character-model", "3D - Models & Objects"),
    ("cgtrader-interior-scene-pack", "3D - Models & Objects"),
    ("cgtrader-3d-assets-vol2", "3D - Models & Objects"),
    ("sketchfab-animated-model-pack", "3D - Models & Objects"),
    ("sketchfab-scenes-collection", "3D - Models & Objects"),
    ("kitbash3d-neo-city-kit", "3D - Models & Objects"),
    ("kit-bash-fantasy-bundle", "3D - Models & Objects"),
    ("daz3d-genesis-character-pack", "3D"),
    ("renderosity-scene-prop-set", "3D"),
    ("poser-figure-pack-v1", "3D"),
    ("poly-haven-hdri-environments", "3D - Materials & Textures"),
    ("hdri-haven-outdoor-pack", "3D - Materials & Textures"),
    ("ambientcg-pbr-materials-pack", "3D - Materials & Textures"),
    ("substance-painter-material-pack", "3D - Materials & Textures"),
    ("substance-designer-texture-bundle", "3D - Materials & Textures"),
    ("sbsar-stone-material-pack", "3D - Materials & Textures"),
    ("studio-hdri-environment-pack-vol3", "3D - Materials & Textures"),
    ("fab-marketplace-asset-unreal", "Unreal Engine - Assets"),
    ("fab-material-pack-ue5", "Unreal Engine - Assets"),
]


@pytest.mark.parametrize("stem,expected", V89_3D_MARKETS, ids=[c[0] for c in V89_3D_MARKETS])
def test_v89_3d_marketplace_rules(stem, expected):
    cat, conf = _infer(stem)
    assert cat == expected and conf >= 60


V89_GAME_ASSETS = [
    ("itch-io-pixel-tileset-pack", "Game Assets & Sprites"),
    ("itchio-game-asset-bundle", "Game Assets & Sprites"),
    ("opengameart-sprites-collection", "Game Assets & Sprites"),
    ("kenney-ui-sprite-pack", "Game Assets & Sprites"),
    ("rpg-maker-tileset-forest", "Game Assets & Sprites"),
]


@pytest.mark.parametrize("stem,expected", V89_GAME_ASSETS, ids=[c[0] for c in V89_GAME_ASSETS])
def test_v89_game_asset_rules(stem, expected):
    cat, conf = _infer(stem)
    assert cat == expected and conf >= 60


V89_MUSIC_PROD = [
    ("loopmasters-deep-house-sample-pack", "Stock Music & Audio"),
    ("loopmasters-collection-vol5", "Stock Music & Audio"),
    ("native-instruments-komplete-library", "Music Production - Presets"),
    ("ni-komplete-expansion-pack", "Music Production - Presets"),
    ("spitfire-audio-strings-expansion", "Music Production - Presets"),
    ("spitfire-symphonic-instrument-pack", "Music Production - Presets"),
    ("adsr-sounds-sample-pack", "Stock Music & Audio"),
    ("samples-from-mars-drumbox-pack", "Stock Music & Audio"),
]


@pytest.mark.parametrize("stem,expected", V89_MUSIC_PROD, ids=[c[0] for c in V89_MUSIC_PROD])
def test_v89_music_production_rules(stem, expected):
    cat, conf = _infer(stem)
    assert cat == expected and conf >= 60


V89_EXTENSIONS = [
    (".cr3", "Photography - RAW Files"),
    (".exr", "3D - Materials & Textures"),
    (".sbs", "3D - Materials & Textures"),
    (".sbsar", "3D - Materials & Textures"),
    (".ztl", "3D"),
    (".usd", "3D - Models & Objects"),
    (".usdz", "3D - Models & Objects"),
    (".sf2", "Music Production - Presets"),
    (".sfz", "Music Production - Presets"),
    (".nki", "Music Production - Presets"),
    (".nkx", "Music Production - Presets"),
    (".ptx", "Music Production - DAW Projects"),
    (".cpr", "Music Production - DAW Projects"),
    (".xcf", "Clipart & Illustrations"),
]


@pytest.mark.parametrize("ext,expected", V89_EXTENSIONS, ids=[c[0] for c in V89_EXTENSIONS])
def test_v89_extension_mappings(ext, expected):
    cat, _conf = _ext_lookup(ext)
    assert cat == expected
