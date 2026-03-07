"""UniFile — Category definitions, keyword index, and AEP scoring."""
import os, re, math
from pathlib import Path
from functools import lru_cache

from unifile.config import _APP_DATA_DIR, _CUSTOM_CATS_FILE

# Late import to avoid circular dependency
def _get_normalize():
    from unifile.naming import _normalize
    return _normalize

# ── Generic AEP names to exclude ──────────────────────────────────────────────
GENERIC_AEP_NAMES = {
    'cs6', 'project', '1', 'cc', 'ver_1', '(cs6)',
    'cs5', 'cs5.5', 'cs4', 'cc2014', 'cc2015', 'cc2017', 'cc2018', 'cc2019', 'cc2020',
    'cc2021', 'cc2022', 'cc2023', 'cc2024', 'cc2025',
    'main', 'comp', 'comp 1', 'comp1', 'composition', 'final', 'final project',
    'output', 'render', 'preview', 'thumbnail', 'template', 'source', 'original',
    'backup', 'copy', 'test', 'temp', 'draft', 'wip', 'new project', 'untitled',
    'element', 'precomp', 'pre-comp', 'pre comp', 'assets',
    # Discovered from 23K-folder scan (v5.4)
    '001', '002', '003', '16', '01',  # Bare numbers used as project names
}

def is_generic_aep(name: str) -> bool:
    return name.strip().lower() in GENERIC_AEP_NAMES


def _score_aep(aep_path, folder_path, folder_name):
    """Score an AEP file for how likely it is to be the main project file.
    Higher score = better candidate for naming.

    Scoring signals:
      +50  base score
      +30  descriptive name (>8 alpha chars, not generic)
      +20  name resembles folder name (shared significant words)
      +15  located at top level of folder (depth 0)
      +10  not inside an asset subfolder (Footage, Audio, etc.)
      +5   larger files get a small bonus (tiebreaker, not dominant)
      -40  generic/version name (project.aep, cs6.aep, comp.aep)
      -25  inside asset folder like (Footage), Elements, etc.
      -10  per depth level beyond top
      -15  very short name (1-3 chars, likely abbreviations)
    """
    stem = aep_path.stem  # filename without .aep
    stem_lower = stem.strip().lower()
    stem_norm = _normalize(stem)
    folder_norm = _normalize(folder_name)
    size = 0
    try:
        size = aep_path.stat().st_size
    except (PermissionError, OSError):
        pass

    score = 50  # Base score

    # ── Depth: prefer top-level AEPs ──
    try:
        rel = aep_path.relative_to(folder_path)
        depth = len(rel.parts) - 1  # 0 = directly in folder
    except (ValueError, TypeError):
        depth = 0
    score += max(0, 15 - depth * 10)  # +15 at depth 0, +5 at depth 1, -5 at depth 2, etc.

    # ── Asset folder penalty: AEPs inside (Footage), Assets, etc. ──
    if depth > 0:
        parent_parts = rel.parts[:-1]  # All parent dirs relative to folder root
        for part in parent_parts:
            part_lower = part.lower().strip()
            part_stripped = re.sub(r'^[\(\[\{]|[\)\]\}]$', '', part_lower).strip()
            if part_lower in _ASSET_FOLDER_NAMES or part_stripped in _ASSET_FOLDER_NAMES:
                score -= 25
                break

    # ── Generic name penalty ──
    if stem_lower in GENERIC_AEP_NAMES:
        score -= 40
    # Also penalize pure version patterns: "v1", "v2", "ver2", number-only
    elif re.match(r'^(v\d+|ver[_\s]?\d+|\d{1,3})$', stem_lower):
        score -= 35
    # Penalize names that are just the AE version: "CC 2020", "After Effects"
    elif re.match(r'^(cc\s*\d{4}|after\s*effects?)$', stem_lower):
        score -= 35

    # ── Pre-render / auto-save / copy penalties (from 23K scan) ──
    # Pre-rendered versions are secondary to the editable project
    if re.search(r'pre[_\-\s]?render', stem_lower):
        score -= 20
    # Auto-save files are never the main project
    if 'auto-save' in stem_lower or 'auto_save' in stem_lower:
        score -= 50
    # "copy" suffix indicates a duplicate
    if re.search(r'\bcopy\b', stem_lower):
        score -= 15
    # "(converted)" suffix from AE version conversion
    if '(converted)' in stem_lower:
        score -= 10

    # ── CC version preference (from 23K scan: CS/CC version pairs are most common multi-AEP pattern) ──
    cc_match = re.search(r'cc[_\s]?(\d{4})', stem_lower)
    if cc_match:
        cc_year = int(cc_match.group(1))
        if cc_year >= 2020:
            score += 8
        elif cc_year >= 2018:
            score += 5
    elif re.search(r'\bcc\b', stem_lower) and not re.match(r'^cc$', stem_lower):
        score += 3
    # CS versions are less preferred than CC
    if re.search(r'\b(cs[456]|cs5\.5)\b', stem_lower):
        score -= 8
    # ── Short name penalty ──
    alpha_count = sum(1 for c in stem if c.isalpha())
    if alpha_count <= 3:
        score -= 15
    elif alpha_count <= 5:
        score -= 5

    # ── Descriptive name bonus ──
    if alpha_count > 8 and stem_lower not in GENERIC_AEP_NAMES:
        score += 30
    elif alpha_count > 5 and stem_lower not in GENERIC_AEP_NAMES:
        score += 15

    # ── Folder name similarity bonus ──
    if stem_norm and folder_norm:
        stem_tokens = set(stem_norm.split())
        folder_tokens = set(folder_norm.split())
        # Remove noise tokens (numbers, short words)
        sig_stem = {t for t in stem_tokens if len(t) > 2 and not t.isdigit()}
        sig_folder = {t for t in folder_tokens if len(t) > 2 and not t.isdigit()}
        if sig_stem and sig_folder:
            overlap = sig_stem & sig_folder
            if overlap:
                score += min(20, len(overlap) * 10)

    # ── Size bonus (minor tiebreaker: log-scaled, max +8 points) ──
    if size > 0:
        # 1MB = +2, 10MB = +4, 100MB = +6, 1GB = +8
        score += min(8, max(0, int(math.log10(max(size, 1)) - 4)))

    return score, size


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def is_generic_aep(name: str) -> bool:
    return name.strip().lower() in GENERIC_AEP_NAMES


def _score_aep(aep_path, folder_path, folder_name):
    """Score an AEP file for how likely it is to be the main project file.
    Higher score = better candidate for naming.

    Scoring signals:
      +50  base score
      +30  descriptive name (>8 alpha chars, not generic)
      +20  name resembles folder name (shared significant words)
      +15  located at top level of folder (depth 0)
      +10  not inside an asset subfolder (Footage, Audio, etc.)
      +5   larger files get a small bonus (tiebreaker, not dominant)
      -40  generic/version name (project.aep, cs6.aep, comp.aep)
      -25  inside asset folder like (Footage), Elements, etc.
      -10  per depth level beyond top
      -15  very short name (1-3 chars, likely abbreviations)
    """
    stem = aep_path.stem  # filename without .aep
    stem_lower = stem.strip().lower()
    stem_norm = _normalize(stem)
    folder_norm = _normalize(folder_name)
    size = 0
    try:
        size = aep_path.stat().st_size
    except (PermissionError, OSError):
        pass

    score = 50  # Base score

    # ── Depth: prefer top-level AEPs ──
    try:
        rel = aep_path.relative_to(folder_path)
        depth = len(rel.parts) - 1  # 0 = directly in folder
    except (ValueError, TypeError):
        depth = 0
    score += max(0, 15 - depth * 10)  # +15 at depth 0, +5 at depth 1, -5 at depth 2, etc.

    # ── Asset folder penalty: AEPs inside (Footage), Assets, etc. ──
    if depth > 0:
        parent_parts = rel.parts[:-1]  # All parent dirs relative to folder root
        for part in parent_parts:
            part_lower = part.lower().strip()
            part_stripped = re.sub(r'^[\(\[\{]|[\)\]\}]$', '', part_lower).strip()
            if part_lower in _ASSET_FOLDER_NAMES or part_stripped in _ASSET_FOLDER_NAMES:
                score -= 25
                break

    # ── Generic name penalty ──
    if stem_lower in GENERIC_AEP_NAMES:
        score -= 40
    # Also penalize pure version patterns: "v1", "v2", "ver2", number-only
    elif re.match(r'^(v\d+|ver[_\s]?\d+|\d{1,3})$', stem_lower):
        score -= 35
    # Penalize names that are just the AE version: "CC 2020", "After Effects"
    elif re.match(r'^(cc\s*\d{4}|after\s*effects?)$', stem_lower):
        score -= 35

    # ── Pre-render / auto-save / copy penalties (from 23K scan) ──
    # Pre-rendered versions are secondary to the editable project
    if re.search(r'pre[_\-\s]?render', stem_lower):
        score -= 20
    # Auto-save files are never the main project
    if 'auto-save' in stem_lower or 'auto_save' in stem_lower:
        score -= 50
    # "copy" suffix indicates a duplicate
    if re.search(r'\bcopy\b', stem_lower):
        score -= 15
    # "(converted)" suffix from AE version conversion
    if '(converted)' in stem_lower:
        score -= 10

    # ── CC version preference (from 23K scan: CS/CC version pairs are most common multi-AEP pattern) ──
    cc_match = re.search(r'cc[_\s]?(\d{4})', stem_lower)
    if cc_match:
        cc_year = int(cc_match.group(1))
        if cc_year >= 2020:
            score += 8
        elif cc_year >= 2018:
            score += 5
    elif re.search(r'\bcc\b', stem_lower) and not re.match(r'^cc$', stem_lower):
        score += 3
    # CS versions are less preferred than CC
    if re.search(r'\b(cs[456]|cs5\.5)\b', stem_lower):
        score -= 8
    # ── Short name penalty ──
    alpha_count = sum(1 for c in stem if c.isalpha())
    if alpha_count <= 3:
        score -= 15
    elif alpha_count <= 5:
        score -= 5

    # ── Descriptive name bonus ──
    if alpha_count > 8 and stem_lower not in GENERIC_AEP_NAMES:
        score += 30
    elif alpha_count > 5 and stem_lower not in GENERIC_AEP_NAMES:
        score += 15

    # ── Folder name similarity bonus ──
    if stem_norm and folder_norm:
        stem_tokens = set(stem_norm.split())
        folder_tokens = set(folder_norm.split())
        # Remove noise tokens (numbers, short words)
        sig_stem = {t for t in stem_tokens if len(t) > 2 and not t.isdigit()}
        sig_folder = {t for t in folder_tokens if len(t) > 2 and not t.isdigit()}
        if sig_stem and sig_folder:
            overlap = sig_stem & sig_folder
            if overlap:
                score += min(20, len(overlap) * 10)

    # ── Size bonus (minor tiebreaker: log-scaled, max +8 points) ──
    if size > 0:
        # 1MB = +2, 10MB = +4, 100MB = +6, 1GB = +8
        score += min(8, max(0, int(math.log10(max(size, 1)) - 4)))

    return score, size


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

CATEGORIES = [
    # ══════════════════════════════════════════════════════════════════════════
    # ADOBE & DIGITAL DESIGN TOOLS
    # ══════════════════════════════════════════════════════════════════════════
    ("After Effects - Templates", ["after effects template", "ae template", "aep template", "ae project", "after effects project"]),
    ("After Effects - Intros & Openers", ["intro", "opener", "opening", "ae intro", "logo intro", "logo reveal", "logo sting", "logo animation", "intro sequence", "channel intro", "broadcast intro"]),
    ("After Effects - Slideshows", ["slideshow", "slide show", "photo slideshow", "video slideshow", "gallery slideshow", "memory slideshow", "image slideshow"]),
    ("After Effects - Titles & Typography", ["title sequence", "title animation", "kinetic typography", "kinetic type", "text animation", "animated title", "title reveal", "movie title", "film title", "cinematic title", "title pack", "animated text"]),
    ("After Effects - Lower Thirds", ["lower third", "lower thirds", "name tag", "l3rd", "lower 3rd", "call out", "callout", "callout title"]),
    ("After Effects - Transitions", ["transition", "transitions", "transition pack", "seamless transition", "glitch transition", "zoom transition", "ink transition", "liquid transition", "light transition", "smooth transition"]),
    ("After Effects - Logo Reveals", ["logo reveal", "logo animation", "logo sting", "logo intro", "logo opener", "3d logo", "logo template", "logo motion"]),
    ("After Effects - Infographics & Data", ["infographic", "infographics", "data visualization", "chart animation", "graph animation", "pie chart", "bar chart", "statistics", "animated chart", "data driven"]),
    ("After Effects - HUD & UI", ["hud", "heads up display", "sci-fi ui", "futuristic ui", "hud element", "hud pack", "interface animation", "screen ui", "hologram", "holographic", "tech ui"]),
    ("After Effects - Particles & FX", ["particle", "particles", "particle effect", "particular", "trapcode", "plexus", "stardust", "magic particles", "dust particles", "spark", "sparks"]),
    ("After Effects - Explainer & Promo", ["explainer", "explainer video", "product promo", "app promo", "website promo", "service promo", "corporate promo", "promotional video"]),
    ("After Effects - Character Animation", ["character animation", "character rig", "character", "animated character", "cartoon character", "rigged character", "duik", "rubberhose", "puppet", "limber"]),
    ("After Effects - Social Media Templates", ["social media template", "instagram template", "facebook template", "youtube template", "tiktok template", "social media pack", "stories template", "post template"]),
    ("After Effects - Broadcast Package", ["broadcast package", "broadcast design", "broadcast graphics", "channel branding", "tv package", "news package", "sports broadcast", "broadcast bundle"]),
    ("After Effects - Wedding & Events", ["wedding template", "wedding slideshow", "wedding intro", "wedding invitation video", "save the date video", "event promo", "event opener"]),
    ("After Effects - Photo & Gallery", ["photo gallery", "photo album", "photo animation", "photo template", "gallery template", "photo collage", "photo mosaic", "photo wall"]),
    ("After Effects - Countdown & Timer", ["countdown", "countdown timer", "timer", "clock animation", "new year countdown", "event countdown"]),
    ("After Effects - Presets & Scripts", ["ae preset", "ae presets", "after effects preset", "ae script", "after effects script", "expression", "expressions", "ae plugin", "aescript", "aescripts"]),
    ("After Effects - Map & Location", ["map animation", "map", "travel map", "world map", "animated map", "location pin", "route animation", "country map", "infographic map"]),
    ("After Effects - Lyric Video", ["lyric video", "lyrics", "lyric template", "lyrics video", "karaoke template"]),
    ("After Effects - Mockup & Device", ["device mockup", "phone mockup", "laptop mockup", "screen mockup", "app mockup", "website mockup", "mockup animation", "device animation"]),
    ("After Effects - Emoji & Stickers", ["emoji", "sticker", "stickers", "animated emoji", "animated sticker", "reaction", "emoticon"]),

    ("Premiere Pro - Templates", ["premiere pro template", "premiere template", "mogrt", "prproj", "premiere project"]),
    ("Premiere Pro - Transitions", ["premiere transition", "premiere transitions", "video transition", "film transition", "cinematic transition", "handy seamless"]),
    ("Premiere Pro - Titles & Text", ["premiere title", "mogrt title", "premiere text", "premiere lower third", "premiere caption"]),
    ("Premiere Pro - LUTs & Color", ["lut", "luts", "color grading", "color correction", "color grade", "color lookup", "cinematic lut", "film lut", "3dl", "cube lut"]),
    ("Premiere Pro - Presets & Effects", ["premiere preset", "premiere effect", "video effect", "film effect", "cinematic effect", "speed ramp", "premiere plugin"]),
    ("Premiere Pro - Sound Design", ["sound design", "audio design", "whoosh", "swoosh", "riser", "impact sound", "cinematic sound", "boom", "hit sound"]),

    ("Photoshop - Actions", ["photoshop action", "ps action", "photo action", "atn", "action set", "photo manipulation action", "retouching action", "color action", "hdr action"]),
    ("Photoshop - Brushes", ["photoshop brush", "ps brush", "abr", "brush set", "paint brush", "watercolor brush", "grunge brush", "smoke brush", "hair brush", "foliage brush", "cloud brush"]),
    ("Photoshop - Styles & Effects", ["photoshop style", "layer style", "asl", "text style", "photoshop effect", "photo effect", "double exposure", "dispersion", "shatter effect", "glitch effect"]),
    ("Photoshop - Overlays", ["photoshop overlay", "photo overlay", "light overlay", "rain overlay", "snow overlay", "fire overlay", "smoke overlay", "bokeh overlay", "lens flare overlay", "dust overlay", "scratch overlay"]),
    ("Photoshop - Mockups", ["mockup", "mock-up", "mockup psd", "product mockup", "packaging mockup", "branding mockup", "stationery mockup", "apparel mockup", "scene creator", "hero image"]),
    ("Photoshop - Templates & Composites", ["psd template", "photoshop template", "photo template", "composite", "photo composite", "manipulation", "photo manipulation", "matte painting"]),
    ("Photoshop - Retouching & Skin", ["retouch", "retouching", "skin retouch", "beauty retouch", "portrait retouch", "frequency separation", "dodge and burn", "skin smoothing"]),
    ("Photoshop - Patterns", ["photoshop pattern", "ps pattern", "pat file", "seamless pattern", "tileable pattern", "repeat pattern"]),
    ("Photoshop - Gradients & Swatches", ["gradient", "gradients", "swatch", "swatches", "color palette", "color scheme", "aco", "grd"]),
    ("Photoshop - Smart Objects & PSDs", ["smart object", "smart psd", "layered psd", "editable psd", "organized psd"]),
    ("Photoshop - Shapes & Custom Shapes", ["custom shape", "photoshop shape", "csh", "vector shape", "ps shape"]),

    ("Illustrator - Vectors & Assets", ["illustrator", "vector art", "vector illustration", "ai file", "eps file", "vector graphic", "vector pack", "vector set", "vector bundle"]),
    ("Illustrator - Brushes & Swatches", ["illustrator brush", "ai brush", "vector brush", "scatter brush", "pattern brush", "art brush", "illustrator swatch"]),
    ("Illustrator - Patterns & Styles", ["illustrator pattern", "vector pattern", "illustrator style", "graphic style"]),
    ("Illustrator - Icons & UI Kits", ["icon set", "icon pack", "icon bundle", "ui kit", "ui pack", "wireframe", "wireframe kit"]),

    ("InDesign - Templates & Layouts", ["indesign", "indd", "indesign template", "indesign layout", "indt", "idml"]),
    ("InDesign - Magazine & Editorial", ["magazine template", "magazine layout", "editorial", "editorial layout", "editorial design", "lookbook", "catalog layout"]),
    ("InDesign - Print Templates", ["print template", "print ready", "print design", "press ready", "cmyk", "bleed", "crop marks"]),

    ("Lightroom - Presets & Profiles", ["lightroom preset", "lr preset", "lightroom profile", "lrtemplate", "xmp preset", "dng preset", "lightroom mobile", "lightroom filter"]),

    # ══════════════════════════════════════════════════════════════════════════
    # MOTION GRAPHICS & VIDEO PRODUCTION
    # ══════════════════════════════════════════════════════════════════════════
    ("Motion Graphics", ["motion graphics", "motion design", "mograph", "animated graphic", "motion pack"]),
    ("Animated Backgrounds", ["animated background", "motion background", "video background", "loop background", "loopable background", "vj loop", "vj loops"]),
    ("Animated Icons", ["animated icon", "animated icons", "icon animation", "lottie", "bodymovin", "motion icon"]),
    ("Animated Elements", ["animated element", "animated shape", "shape animation", "geometric animation", "element pack", "motion element"]),
    ("Kinetic Typography", ["kinetic type", "kinetic typography", "type animation", "word animation", "lyric animation"]),
    ("Reveal & Unveil Animations", ["reveal", "unveil", "unfold", "uncover", "curtain reveal", "paper reveal"]),
    ("Glitch & Distortion FX", ["glitch", "glitch effect", "distortion", "digital distortion", "data glitch", "tv glitch", "rgb split", "chromatic aberration", "signal error", "bad tv", "vhs effect", "analog"]),
    ("Smoke & Fluid FX", ["smoke effect", "fluid", "fluid effect", "ink bleed", "ink drop", "watercolor animation", "liquid animation", "fluid dynamics", "flowing", "ink flow"]),
    ("Cinematic Effects", ["cinematic", "cinematic effect", "film grain", "film burn", "light leak", "anamorphic", "letterbox", "widescreen", "film strip", "film reel", "old film"]),
    ("Speed & Action FX", ["speed lines", "action lines", "comic effect", "anime effect", "manga effect", "energy", "power", "impact frame", "speed ramp"]),
    ("Nature & Weather FX", ["rain effect", "snow effect", "fog", "mist", "lightning", "thunder", "storm", "wind effect", "leaves falling", "falling snow", "weather"]),
    ("Fire & Explosion FX", ["fire effect", "explosion", "blast", "detonation", "shockwave", "fire burst", "fireball", "pyrotechnic", "flame effect"]),
    ("Light & Lens FX", ["lens flare", "light effect", "light ray", "light beam", "light streak", "optical flare", "sun ray", "god ray", "volumetric light", "prism"]),
    ("Parallax & Ken Burns", ["parallax", "parallax effect", "ken burns", "2.5d", "photo animation", "depth effect", "camera projection"]),
    ("Split Screen", ["split screen", "multiscreen", "multi screen", "screen split", "collage video"]),
    ("Frame & Border", ["frame", "border", "photo frame", "video frame", "decorative frame", "ornamental frame", "vintage frame"]),
    ("Countdown & Numbers", ["countdown", "number animation", "counter", "numeric", "timer animation", "number reveal"]),
    ("Call-Outs & Pointers", ["call out", "callout", "pointer", "annotation", "line callout", "info box", "tooltip animation"]),
    ("Ribbon & Banner Animations", ["ribbon animation", "banner animation", "flag animation", "waving", "cloth simulation"]),

    # ══════════════════════════════════════════════════════════════════════════
    # STOCK FOOTAGE & MEDIA
    # ══════════════════════════════════════════════════════════════════════════
    ("Stock Footage - General", ["stock footage", "stock video", "video clip", "footage", "royalty free video", "b-roll", "b roll", "broll"]),
    ("Stock Footage - Aerial & Drone", ["aerial footage", "drone footage", "drone shot", "aerial view", "birds eye", "drone video", "flyover"]),
    ("Stock Footage - Nature & Landscape", ["nature footage", "landscape footage", "mountain footage", "ocean footage", "forest footage", "waterfall footage", "sunset footage", "timelapse nature"]),
    ("Stock Footage - City & Urban", ["city footage", "urban footage", "timelapse city", "traffic footage", "street footage", "downtown footage", "nightlife footage"]),
    ("Stock Footage - People & Lifestyle", ["people footage", "lifestyle footage", "business people", "diverse people", "crowd footage", "family footage"]),
    ("Stock Footage - Technology", ["technology footage", "computer footage", "screen footage", "data center", "server room", "coding footage", "tech footage"]),
    ("Stock Footage - Green Screen", ["green screen", "chroma key", "greenscreen", "blue screen", "keying"]),
    ("Stock Footage - Slow Motion", ["slow motion", "slow mo", "slowmo", "high speed", "high frame rate"]),
    ("Stock Footage - Timelapse", ["timelapse", "time lapse", "hyperlapse", "hyper lapse"]),
    ("Stock Footage - Abstract & VFX", ["abstract footage", "abstract video", "vfx footage", "visual effects footage", "cgi footage", "fractal", "kaleidoscope"]),
    ("Stock Footage - Countdown Leaders", ["countdown leader", "film leader", "academy leader", "film countdown", "reel leader"]),
    ("Stock Photos - General", ["stock photo", "stock image", "stock photography", "royalty free photo", "royalty free image"]),
    ("Stock Photos - People & Portraits", ["portrait photo", "headshot", "people photo", "model photo", "lifestyle photo"]),
    ("Stock Photos - Food & Drink", ["food photo", "food photography", "food stock", "drink photo", "beverage photo"]),
    ("Stock Photos - Business", ["business photo", "office photo", "corporate photo", "meeting photo", "teamwork photo"]),
    ("Stock Photos - Nature & Outdoors", ["nature photo", "landscape photo", "outdoor photo", "scenery photo"]),
    ("Stock Photos - Flat Lay & Styled", ["flat lay", "flatlay", "styled stock", "styled photo", "desktop photo", "workspace photo", "styled scene"]),
    ("Stock Music & Audio", ["stock music", "royalty free music", "background music", "production music", "music track", "audio track", "music loop", "audio loop"]),
    ("Sound Effects & SFX", ["sound effect", "sound effects", "sfx", "foley", "ambient sound", "ambiance", "audio sfx", "whoosh", "impact", "riser"]),

    # ══════════════════════════════════════════════════════════════════════════
    # DESIGN ELEMENTS & ASSETS
    # ══════════════════════════════════════════════════════════════════════════
    ("3D", ["3d", "three dimensional", "3d render", "3d model", "cinema4d", "c4d", "blender3d", "element 3d", "3d object", "3d scene", "3d asset", "3d text", "3d logo"]),
    ("3D - Models & Objects", ["3d model", "obj", "fbx", "3ds", "stl", "3d object", "3d prop", "3d asset pack"]),
    ("3D - Materials & Textures", ["3d material", "3d texture", "pbr material", "pbr texture", "substance", "material pack", "shader", "hdri", "hdr environment", "environment map"]),
    ("3D - Scenes & Environments", ["3d scene", "3d environment", "3d room", "3d stage", "3d studio", "virtual set", "virtual studio"]),
    ("Abstract", ["abstract", "generative", "procedural", "abstract art", "abstract design"]),
    ("Alpha Channels & Mattes", ["alpha channel", "alpha matte", "matte", "luma matte", "track matte"]),
    ("Animated GIFs & Cinemagraphs", ["gif", "animated gif", "cinemagraph", "living photo"]),
    ("Backgrounds & Textures", ["background", "backgrounds", "texture", "textures", "wallpaper", "pattern", "backdrop", "studio background"]),
    ("Badges & Emblems", ["badge", "badges", "emblem", "crest", "seal", "stamp", "vintage badge"]),
    ("Banners", ["banner", "banners", "web banner", "display banner", "ad banner", "leaderboard", "skyscraper"]),
    ("Borders & Dividers", ["border", "divider", "separator", "line divider", "decorative border", "ornamental border"]),
    ("Brushes & Presets", ["brush", "brushes", "preset", "presets", "procreate brush"]),
    ("Buttons & UI Elements", ["button", "buttons", "ui element", "web element", "ui component", "gui element"]),
    ("Clipart & Illustrations", ["clipart", "clip art", "illustration", "vector", "svg", "hand drawn", "doodle", "sketch"]),
    ("Color Palettes & Swatches", ["color palette", "color scheme", "swatch", "swatches", "color combination"]),
    ("Confetti & Celebration FX", ["confetti", "streamer", "party popper", "celebration effect", "balloon pop"]),
    ("Dust & Debris", ["dust", "debris", "dirt", "grime", "particle debris", "floating dust"]),
    ("Flares & Light Effects", ["flare", "flares", "lens flare", "light leak", "bokeh", "light effect", "glow", "neon", "anamorphic flare"]),
    ("Flat Design", ["flat design", "flat style", "material design", "flat icon", "flat illustration"]),
    ("Frames & Borders", ["frame", "frames", "photo frame", "picture frame", "border", "decorative frame", "ornate frame"]),
    ("Grunge & Distressed", ["grunge", "distressed", "grungy", "scratch", "scratches", "noise", "grain", "film grain"]),
    ("Icons & Symbols", ["icon", "icons", "symbol", "glyph", "icon set", "iconography", "line icon", "filled icon", "outline icon"]),
    ("Isometric Design", ["isometric", "isometric illustration", "isometric icon", "isometric design", "iso", "2.5d illustration"]),
    ("Maps & Cartography", ["map", "maps", "cartography", "world map", "country map", "city map", "infographic map"]),
    ("Mockups - Apparel", ["tshirt mockup", "hoodie mockup", "apparel mockup", "clothing mockup", "hat mockup", "cap mockup"]),
    ("Mockups - Branding", ["branding mockup", "stationery mockup", "identity mockup", "logo mockup", "brand mockup"]),
    ("Mockups - Devices", ["device mockup", "phone mockup", "iphone mockup", "macbook mockup", "laptop mockup", "tablet mockup", "ipad mockup", "screen mockup", "monitor mockup"]),
    ("Mockups - Packaging", ["packaging mockup", "box mockup", "bag mockup", "bottle mockup", "can mockup", "pouch mockup", "label mockup"]),
    ("Mockups - Print", ["flyer mockup", "poster mockup", "magazine mockup", "book mockup", "brochure mockup", "business card mockup", "invitation mockup"]),
    ("Mockups - Signage", ["sign mockup", "signage mockup", "billboard mockup", "storefront mockup", "window mockup", "neon sign mockup"]),
    ("Overlays & Effects", ["overlay", "overlays", "effect", "effects", "photo overlay", "light overlay", "texture overlay"]),
    ("Patterns - Seamless", ["seamless pattern", "tileable", "repeat pattern", "surface pattern", "fabric pattern", "geometric pattern"]),
    ("PNG - Transparent Assets", ["png", "transparent", "cutout", "isolated", "png asset", "transparent background"]),
    ("Ribbons & Labels", ["ribbon", "ribbons", "label", "tag", "price tag", "sale tag", "decorative ribbon"]),
    ("Shapes & Geometric", ["shape", "shapes", "geometric", "polygon", "circle", "triangle", "hexagon", "abstract shape"]),
    ("Silhouettes", ["silhouette", "silhouettes", "shadow", "outline figure"]),
    ("Smoke & Fog", ["smoke", "fog", "mist", "haze", "atmosphere", "atmospheric", "smoke png"]),
    ("Sparkle & Glitter", ["sparkle", "glitter", "shimmer", "twinkle", "shine", "star burst"]),
    ("Splash & Paint", ["splash", "paint splash", "ink splash", "color splash", "paint splatter", "watercolor splash"]),
    ("Vectors & SVG", ["vector", "vectors", "svg", "vector art", "vector graphic", "scalable vector"]),
    ("Watercolor & Artistic", ["watercolor", "watercolour", "artistic", "hand painted", "gouache", "acrylic"]),

    # ══════════════════════════════════════════════════════════════════════════
    # FONTS, TYPOGRAPHY & TEXT
    # ══════════════════════════════════════════════════════════════════════════
    ("Fonts & Typography", ["font", "fonts", "typography", "typeface", "lettering", "calligraphy", "handwriting", "otf", "ttf", "woff", "opentype", "truetype"]),
    ("Fonts - Display & Decorative", ["display font", "decorative font", "fancy font", "ornamental font", "headline font"]),
    ("Fonts - Script & Handwritten", ["script font", "handwritten font", "cursive font", "calligraphy font", "signature font", "brush font"]),
    ("Fonts - Sans Serif", ["sans serif", "sans-serif", "modern font", "clean font", "geometric font"]),
    ("Fonts - Serif", ["serif font", "classic font", "elegant font", "editorial font"]),
    ("Fonts - Monospace & Code", ["monospace font", "coding font", "mono font", "typewriter font"]),
    ("Font Collections", ["font collection", "font bundle", "font pack", "gomedia", "go media"]),
    ("Text Effects & Styles", ["text effect", "text style", "3d text", "font effect", "text animation", "text preset", "type effect", "letter effect"]),

    # ══════════════════════════════════════════════════════════════════════════
    # PRINT & DOCUMENT DESIGN
    # ══════════════════════════════════════════════════════════════════════════
    ("Flyers & Print", ["flyer", "flyers", "print", "printable", "print ready", "leaflet"]),
    ("Posters", ["poster", "posters", "wall art", "art print", "print poster"]),
    ("Brochures & Bi-Fold & Tri-Fold", ["brochure", "bi-fold", "bifold", "tri-fold", "trifold", "pamphlet"]),
    ("Business Cards", ["business card", "business cards", "visiting card", "name card"]),
    ("Resume & CV", ["resume", "cv", "curriculum vitae", "cover letter"]),
    ("Postcards", ["postcard", "postcards", "greeting card", "greetings card"]),
    ("Certificate", ["certificate", "diploma", "credential", "award certificate"]),
    ("Invitations & Save the Date", ["invitation", "invitations", "invite", "save the date", "rsvp", "announcement card"]),
    ("Letterhead & Stationery", ["letterhead", "stationery", "stationary", "envelope", "notepad"]),
    ("Rollup Banners & Signage", ["rollup", "roll-up", "signage", "sign", "yard sign", "pull up banner", "retractable banner"]),
    ("Billboard", ["billboard", "outdoor advertising", "large format"]),
    ("Menu Design", ["menu design", "restaurant menu", "food menu", "drink menu", "bar menu", "cafe menu"]),
    ("Calendar", ["calendar", "planner", "desk calendar", "wall calendar"]),
    ("Gift Voucher & Coupon", ["gift voucher", "gift card", "coupon", "gift certificate", "discount card", "loyalty card"]),
    ("Annual Report", ["annual report", "company report"]),
    ("Packaging & Product", ["packaging", "package design", "product packaging", "label", "box design", "die cut", "dieline"]),
    ("Book & Literature", ["book cover", "book fair", "bookmark", "books", "literature", "library", "reading", "ebook cover"]),
    ("Forms & Documents", ["form", "forms", "document", "worksheet", "contract"]),

    # ══════════════════════════════════════════════════════════════════════════
    # SOCIAL MEDIA & WEB
    # ══════════════════════════════════════════════════════════════════════════
    ("Social Media", ["social media", "social network", "twitter", "tiktok", "snapchat", "linkedin", "social post"]),
    ("Instagram & Stories", ["instagram", "insta", "ig stories", "reels", "ig post", "instagram carousel"]),
    ("Facebook & Social Covers", ["facebook", "fb cover", "social media cover", "facebook ad", "fb ad"]),
    ("YouTube & Video Platform", ["youtube", "youtuber", "vlog", "thumbnail", "youtube banner", "end screen", "end card", "subscribe", "youtube intro"]),
    ("Pinterest", ["pinterest", "pin design"]),
    ("Twitch & Streaming", ["twitch", "stream overlay", "streaming", "stream package", "stream alert", "webcam frame", "obs overlay", "stream deck", "gaming overlay"]),
    ("Email & Newsletter", ["email", "newsletter", "email template", "mailchimp", "email marketing", "html email"]),
    ("Blog & Content", ["blog", "blogging", "blog post", "content template"]),
    ("Website Design", ["website", "web design", "landing page", "homepage", "web template", "html template", "css template", "wordpress", "webflow"]),
    ("Mobile App Design", ["app design", "mobile app", "app ui", "mobile ui", "app screen", "app template"]),
    ("UI & UX Design", ["ui design", "ux design", "user interface", "user experience", "wireframe", "prototype", "ui kit", "design system"]),
    ("Ad & Banner Design", ["ad design", "banner ad", "google ads", "display ad", "web ad", "facebook ad", "instagram ad", "social ad"]),
    ("Thumbnails", ["thumbnail", "thumbnails", "youtube thumbnail", "video thumbnail"]),

    # ══════════════════════════════════════════════════════════════════════════
    # PRESENTATION & INFOGRAPHIC
    # ══════════════════════════════════════════════════════════════════════════
    ("Presentations & PowerPoint", ["presentation", "powerpoint", "pptx", "keynote", "slide", "slides", "slideshow", "google slides", "pitch deck"]),
    ("Infographic", ["infographic", "infographics", "data visualization", "chart", "diagram", "flowchart", "process diagram"]),

    # ══════════════════════════════════════════════════════════════════════════
    # LOGO & BRANDING
    # ══════════════════════════════════════════════════════════════════════════
    ("Logo & Identity", ["logo", "logos", "identity", "brand mark", "logotype", "logo design", "logo template", "brand identity"]),
    ("Branding & Identity Kits", ["branding kit", "brand kit", "identity kit", "brand guidelines", "style guide", "brand board"]),
    ("Design Inspiration Packs", ["inspiration pack", "identity pack", "branding pack", "mega branding", "toolkit", "graphics toolkit", "pixelsquid", "juicedrops"]),

    # ══════════════════════════════════════════════════════════════════════════
    # VIDEO & CINEMA
    # ══════════════════════════════════════════════════════════════════════════
    ("Cinema & Film", ["cinema", "film", "movie", "theater", "theatre", "screening", "premiere", "hollywood", "trailer", "storyboard"]),
    ("Documentary", ["documentary", "docuseries", "doc film", "mini doc"]),
    ("Music Video", ["music video", "mv", "music clip", "performance video"]),
    ("VFX & Compositing", ["vfx", "visual effects", "compositing", "green screen", "chroma key", "rotoscope", "matte painting", "cgi"]),
    ("Color Grading & LUTs", ["color grading", "color correction", "lut", "luts", "color grade", "color lookup", "cinematic lut", "film lut", "3dl", "cube"]),
    ("Video Editing - General", ["video editing", "video edit", "film editing", "cut", "montage", "compilation"]),
    ("Drone & Aerial Video", ["drone", "aerial", "drone shot", "aerial video", "fpv", "quadcopter"]),
    ("Slow Motion & High Speed", ["slow motion", "slow mo", "slowmo", "high speed", "high frame rate", "ramping"]),
    ("Timelapse & Hyperlapse", ["timelapse", "time lapse", "hyperlapse", "hyper lapse", "time ramp"]),
    ("Stop Motion", ["stop motion", "stop-motion", "claymation", "frame by frame"]),
    ("Screen Recording & Tutorial", ["screen recording", "screencast", "tutorial video", "how to video", "walkthrough"]),
    ("Aspect Ratio & Letterbox", ["letterbox", "widescreen", "anamorphic", "cinemascope", "aspect ratio", "pillarbox"]),

    # ══════════════════════════════════════════════════════════════════════════
    # AUDIO & MUSIC PRODUCTION
    # ══════════════════════════════════════════════════════════════════════════
    ("Music", ["music", "musical", "musician", "band", "album", "playlist", "vinyl", "record", "audio", "sound"]),
    ("Music - Loops & Beats", ["music loop", "drum loop", "beat", "beats", "drum kit", "sample pack", "loop pack"]),
    ("Music - Cinematic & Orchestral", ["cinematic music", "orchestral", "epic music", "trailer music", "film score", "soundtrack"]),
    ("Music - Electronic & EDM", ["electronic music", "edm music", "techno", "house music", "trance", "dubstep", "synthwave"]),
    ("Music - Ambient & Chill", ["ambient music", "chill music", "lofi", "lo-fi", "relaxing music", "meditation music", "calm"]),
    ("Music - Corporate & Upbeat", ["corporate music", "upbeat", "uplifting", "positive music", "happy music", "motivational music"]),
    ("Podcast & Voiceover", ["podcast", "voiceover", "voice over", "narration", "podcast intro", "podcast template"]),
    ("Audio Visualizer", ["audio visualizer", "music visualizer", "spectrum", "equalizer", "audio spectrum", "waveform"]),

    # ══════════════════════════════════════════════════════════════════════════
    # PHOTOGRAPHY & IMAGE EDITING
    # ══════════════════════════════════════════════════════════════════════════
    ("Art & Photography", ["art photography", "photography", "photo studio", "photographer", "camera", "photoshoot", "polaroid"]),
    ("Photography Presets & Actions", ["photoshop", "lightroom", "actions", "styles", "presets", "photo editing", "photo filter"]),
    ("HDR & Tone Mapping", ["hdr", "high dynamic range", "tone mapping", "hdr effect", "hdr photo"]),
    ("Black & White Photography", ["black and white", "monochrome", "grayscale", "bw photo", "noir"]),
    ("Long Exposure", ["long exposure", "light trail", "light painting", "motion blur photo", "smooth water"]),
    ("Macro & Close-Up", ["macro", "close up", "closeup", "micro", "detail shot"]),
    ("Portrait Photography", ["portrait", "headshot", "portrait photography", "portrait lighting", "portrait retouch"]),
    ("Product Photography", ["product photography", "product photo", "product shoot", "ecommerce photo", "catalog photo"]),
    ("Flat Lay & Styled Photography", ["flat lay", "flatlay", "styled stock", "styled photo", "desktop photo", "workspace photo"]),

    # ══════════════════════════════════════════════════════════════════════════
    # TOPICS, THEMES & EVENTS
    # ══════════════════════════════════════════════════════════════════════════
    ("Accounting & Finance", ["accountant", "accounting", "bookkeeping", "income tax", "tax refund", "tax", "invoice", "invoices", "financial", "finance", "money", "bank", "stocks", "stock market", "trading", "investment", "bitcoin", "crypto", "cryptocurrency", "blockchain"]),
    ("Advertising & Marketing", ["advertising", "advertisement", "marketing", "promo", "promotional", "commerce", "seo", "branding", "brand identity"]),
    ("Africa & Afro", ["africa", "african", "afro"]),
    ("Agriculture & Farming", ["agriculture", "farming", "farm", "harvest", "crop"]),
    ("Air Balloon", ["air balloon", "hot air balloon"]),
    ("Aircraft & Aviation", ["aircraft", "airplane", "plane", "aviation", "flight", "jet", "airline", "airport"]),
    ("Alternative Energy", ["alternative power", "alternative energy", "solar power", "solar panel", "wind turbine", "renewable", "green energy"]),
    ("Amusement Park", ["amusement park", "theme park", "roller coaster", "carnival ride"]),
    ("Animals & Pets", ["animal", "animals", "pet", "pets", "pet shop", "dog", "cat", "puppy", "kitten", "wildlife", "zoo", "veterinary", "vet"]),
    ("Anniversary", ["anniversary"]),
    ("April Fools Day", ["april fool", "april fools"]),
    ("Arabian & Middle Eastern", ["arabian", "arabic", "middle eastern", "ramadan", "eid", "mosque", "islamic"]),
    ("Archery", ["archery", "bow and arrow"]),
    ("Architecture & Construction", ["architecture", "architectural", "construction", "building", "contractor", "blueprint"]),
    ("Armed Forces & Military", ["armed forces", "military", "army", "navy", "marines", "air force", "troops", "memorial day", "camo", "camouflage"]),
    ("Arts & Crafts", ["arts", "crafts", "handmade", "artisan"]),
    ("Astrology & Zodiac", ["astrology", "zodiac", "horoscope", "star sign"]),
    ("Auction", ["auction", "bidding"]),
    ("Australia Day", ["australia day", "aussie"]),
    ("Autism Awareness", ["autism"]),
    ("Awards & Ceremonies", ["awards", "award ceremony", "oscars", "grammy", "emmy", "golden globe", "trophy"]),
    ("Baby & Newborn", ["baby", "newborn", "infant", "baby shower", "nursery"]),
    ("Bachelor & Bachelorette", ["bachelor", "bachelorette"]),
    ("Bakery & Pastry", ["bakery", "pastry", "bread", "baking", "donut", "cupcake"]),
    ("Balloons", ["balloon", "balloons"]),
    ("Bar & Nightlife", ["bar lounge", "sports bar", "nightclub", "nightlife", "lounge", "cocktail bar", "hookah", "shisha", "pub crawl", "wine bar"]),
    ("Barbershop & Grooming", ["barbershop", "barber", "grooming", "mens grooming", "haircut", "movember"]),
    ("Baseball", ["baseball", "softball"]),
    ("Basketball", ["basketball", "nba", "hoops"]),
    ("Bat Mitzvah", ["bat mitzvah", "bar mitzvah", "mitzvah"]),
    ("Beach & Coastal", ["beach", "coastal", "ocean", "seaside", "shore", "surfing", "surf"]),
    ("Beauty, Fashion & Spa", ["beauty", "fashion", "spa", "hair salon", "nail salon", "cosmetic", "makeup", "skincare", "glamour"]),
    ("Beer & Alcohol", ["beer", "alcohol", "whiskey", "vodka", "rum", "tequila", "spirits", "liquor", "wine", "winery", "brewery", "craft beer", "happy hour", "cocktail"]),
    ("Bike & Cycling", ["bike", "bicycle", "cycling", "mountain bike", "bmx", "motorcycle", "motorbike", "biker"]),
    ("Billiards & Pool", ["billiard", "billiards", "pool table", "snooker"]),
    ("Bingo", ["bingo"]),
    ("Birthday", ["birthday", "bday"]),
    ("Black Friday", ["black friday"]),
    ("Black History Month", ["black history", "african american history"]),
    ("Black Party & Dark Themes", ["black party", "all black", "dark party", "black and red"]),
    ("Blood Drive", ["blood drive", "blood donation", "donate blood"]),
    ("Blues & Jazz", ["blues", "jazz", "blues festival", "jazz festival", "smooth jazz"]),
    ("Boat & Yacht", ["boat", "yacht", "sailing", "marina", "cruise", "nautical"]),
    ("Boss Day", ["boss day", "bosses day"]),
    ("Bowling", ["bowling"]),
    ("Boxing & MMA", ["boxing", "mma", "mixed martial arts", "ufc", "fight night", "wrestling"]),
    ("Burning Man", ["burning man"]),
    ("Business & Corporate", ["business", "corporate", "company", "enterprise", "professional", "office", "consulting"]),
    ("Cab & Taxi", ["cab", "taxi", "rideshare", "uber", "lyft"]),
    ("Cabaret & Burlesque", ["cabaret", "burlesque"]),
    ("Cafe & Restaurant", ["cafe", "restaurant", "diner", "bistro", "dining", "food truck"]),
    ("Cake & Chocolate", ["cake", "chocolate", "dessert", "confectionery", "candy", "sweets"]),
    ("Call Center & Support", ["call center", "customer service", "helpdesk"]),
    ("Camp & Outdoors", ["camp", "camping", "outdoor", "outdoors", "hiking", "trail", "wilderness", "nature"]),
    ("Canada Day", ["canada day", "canadian"]),
    ("Cancer Awareness", ["cancer", "breast cancer", "pink ribbon", "relay for life"]),
    ("Car & Auto", ["car wash", "car show", "car dealership", "automobile", "mechanic", "automotive", "dealership", "vehicle", "auto repair", "auto body", "car rental"]),
    ("Career & Job Fair", ["career expo", "career fair", "job fair", "job vacancy", "hiring", "recruitment", "jobs", "trades", "employment"]),
    ("Carnival & Mardi Gras", ["carnival", "mardi gras", "fat tuesday", "masquerade"]),
    ("Catering", ["catering", "caterer", "banquet"]),
    ("Charity & Fundraiser", ["charity", "fundraiser", "fundraising", "donation", "nonprofit", "benefit", "volunteer"]),
    ("Cheerleading", ["cheerleading", "cheerleader", "cheer"]),
    ("Chess", ["chess"]),
    ("Children & Kids", ["children", "childrens", "kids", "toddler", "playground"]),
    ("Chinese & Lunar New Year", ["chinese", "chinese new year", "lunar new year"]),
    ("Christmas", ["christmas", "xmas", "santa", "noel", "yuletide", "advent"]),
    ("Church & Gospel", ["church", "gospel", "worship", "faith", "christian", "religious", "spiritual", "praise", "sermon", "good friday"]),
    ("Cinco de Mayo", ["cinco de mayo"]),
    ("Circus", ["circus", "big top", "ringmaster", "clown"]),
    ("City & Urban", ["city", "urban", "downtown", "metro", "skyline", "cityscape"]),
    ("Cleaning Service", ["cleaning service", "cleaning", "maid", "janitorial", "pressure washing"]),
    ("Clothing & Apparel", ["clothing", "tshirt", "t-shirt", "hoodie", "shoes", "sneaker", "apparel", "streetwear", "merch"]),
    ("Club & DJ", ["club", "dj", "nightclub", "night club", "edm", "electro", "electronic music", "rave", "dance party", "dj night"]),
    ("Coffee & Tea", ["coffee", "tea", "espresso", "latte", "barista"]),
    ("College & University", ["college", "university", "campus", "sorority", "fraternity"]),
    ("Colorful & Vibrant", ["colorful", "colourful", "vibrant", "rainbow", "multicolor"]),
    ("Columbus Day", ["columbus day"]),
    ("Comedy & Standup", ["comedy", "comedy show", "standup", "stand-up", "comedian"]),
    ("Communication", ["communication", "telecom"]),
    ("Community", ["community", "neighborhood", "town hall"]),
    ("Computer & IT Services", ["computer repair", "computer", "it services", "tech support", "hardware", "software"]),
    ("Concert & Live Music", ["concert", "live music", "live show", "gig"]),
    ("Conference & Summit", ["conference", "summit", "symposium", "seminar", "convention", "expo", "trade show"]),
    ("Cooking & Grill", ["cooking", "grill", "bbq", "barbecue", "cookout", "recipe", "chef"]),
    ("Cornhole", ["cornhole"]),
    ("Country Music", ["country music", "honky tonk", "bluegrass"]),
    ("Covers & Headers", ["cover", "covers", "facebook cover", "header", "timeline cover"]),
    ("COVID-19", ["covid", "covid19", "coronavirus", "pandemic", "quarantine", "vaccine"]),
    ("Crawfish & Seafood", ["crawfish", "crayfish", "seafood", "lobster", "shrimp", "fish fry"]),
    ("Cyber Monday", ["cyber monday"]),
    ("Dance", ["dance", "dancing", "dancer", "ballet", "salsa", "zumba"]),
    ("Dating & Romance", ["dating", "romance", "romantic", "love", "couples", "valentines", "valentine", "vday", "sweetest day"]),
    ("Dentist & Dental", ["dentist", "dental", "teeth", "orthodontist"]),
    ("Diet & Nutrition", ["diet", "nutrition", "meal plan", "healthy eating", "weight loss"]),
    ("Disco Party", ["disco", "disco party", "funk"]),
    ("Diving & Water Sports", ["diving", "scuba", "snorkeling", "water sport"]),
    ("Earth Day & Environment", ["earth day", "environment", "eco", "recycle", "sustainability", "climate"]),
    ("Easter", ["easter", "easter egg", "resurrection"]),
    ("Education & School", ["education", "school", "student", "teacher", "classroom", "learning", "academy", "tutoring", "training", "spelling bee", "admission"]),
    ("Election & Political", ["election", "political", "politics", "politicians", "campaign", "vote", "voting", "presidents day"]),
    ("Electrician & Electrical", ["electrician", "electrical", "wiring"]),
    ("Electronics & Technology", ["electronics", "technology", "tech", "gadget", "device", "smartphone", "mobile", "digital"]),
    ("Elegant & Luxury", ["elegant", "luxury", "premium", "classy", "sophisticated", "upscale", "vip", "red carpet"]),
    ("Entertainment", ["entertainment", "show", "variety show"]),
    ("Erotic & Adult", ["erotic", "sexy", "sensual"]),
    ("Events & Occasions", ["event", "events", "occasion", "celebration"]),
    ("Exterior & Landscape Design", ["exterior design", "landscape", "landscaping", "garden", "gardening", "patio"]),
    ("Eye & Optical", ["eye exam", "optical", "optometrist", "eyewear", "vision"]),
    ("Family", ["family", "family day", "reunion", "family reunion", "high school reunion"]),
    ("Fathers Day", ["fathers day", "father's day", "dad"]),
    ("Festival", ["festival", "fest", "festive"]),
    ("Fire & Fireworks", ["fire", "flame", "fireworks", "pyro", "bonfire"]),
    ("Fishing", ["fishing", "angler", "bass fishing", "fly fishing"]),
    ("Fitness & Gym", ["fitness", "gym", "workout", "exercise", "bodybuilding", "crossfit", "personal trainer"]),
    ("Flags & Patriotic", ["flag", "flags", "patriotic", "independence day", "4th of july", "fourth of july", "flag day"]),
    ("Florist & Flowers", ["florist", "flower", "flowers", "floral", "bouquet", "rose", "blossom"]),
    ("Food & Menu", ["food", "food menu", "meal", "snack", "fast food"]),
    ("Football", ["football", "nfl", "super bowl", "touchdown"]),
    ("Funeral & Memorial", ["funeral", "memorial", "obituary", "remembrance"]),
    ("Furniture & Interior", ["furniture", "home decor", "interior design", "interior", "home improvement"]),
    ("Futuristic & Sci-Fi", ["future", "futuristic", "sci-fi", "scifi", "cyberpunk", "space", "galaxy", "cosmic", "astronaut"]),
    ("Games & Gaming", ["game", "games", "gaming", "gamer", "esports", "video game", "arcade", "game of thrones", "harry potter"]),
    ("Garage Sale & Yard Sale", ["garage sale", "yard sale", "flea market", "rummage sale"]),
    ("Gay & LGBT Pride", ["gay", "lgbt", "lgbtq", "pride", "queer", "transgender"]),
    ("Girls Night & Ladies Night", ["girls night", "ladies night"]),
    ("Gold & Metallic", ["gold", "golden", "metallic", "silver", "bronze", "chrome"]),
    ("Golf", ["golf", "golfing", "golf course"]),
    ("Graduation & Prom", ["graduation", "grad", "commencement", "prom", "class of"]),
    ("Graffiti & Street Art", ["graffiti", "street art", "mural", "spray paint"]),
    ("Grand Opening", ["grand opening", "now open", "ribbon cutting", "store opening"]),
    ("Halloween", ["halloween", "spooky", "haunted", "trick or treat", "costume", "witch", "zombie", "horror"]),
    ("Handyman & Home Repair", ["handyman", "home repair", "plumber", "plumbing", "hvac", "air conditioner"]),
    ("Hanukkah & Jewish Holidays", ["hanukkah", "chanukah", "jewish", "passover", "rosh hashanah", "kwanzaa"]),
    ("Health & Medical", ["health", "medical", "healthcare", "pharmacy", "hospital", "doctor", "nurse", "clinic", "wellness"]),
    ("Hockey", ["hockey", "nhl", "ice hockey"]),
    ("Holidays & Seasonal", ["holiday", "holidays", "seasonal"]),
    ("Home Security", ["home security", "security camera", "alarm system", "surveillance"]),
    ("Hotel & Hospitality", ["hotel", "hospitality", "resort", "lodge", "motel"]),
    ("Ice Cream & Frozen", ["ice cream", "gelato", "frozen yogurt", "popsicle"]),
    ("Indie & Alternative", ["indie", "indie music", "alternative", "acoustic"]),
    ("Insurance", ["insurance", "life insurance", "coverage"]),
    ("Isometric Design", ["isometric", "isometric design"]),
    ("Karaoke", ["karaoke", "sing along", "open mic"]),
    ("Kentucky Derby", ["kentucky", "derby", "horse racing"]),
    ("Labor Day", ["labor day", "labour day", "workers day"]),
    ("Laundry & Dry Cleaning", ["laundry", "dry cleaning", "laundromat"]),
    ("Lawn Care & Landscaping", ["lawn care", "lawn mowing", "yard work", "lawn service"]),
    ("Lawyer & Legal", ["lawyer", "legal", "attorney", "law firm", "court", "justice"]),
    ("Marijuana & Cannabis", ["marijuana", "cannabis", "hemp", "weed", "420", "dispensary", "cbd"]),
    ("Martin Luther King Day", ["martin luther king", "mlk"]),
    ("Masks", ["mask", "masks", "masquerade mask"]),
    ("Minimal & Clean", ["minimal", "minimalist", "clean style", "simple"]),
    ("Mothers Day", ["mothers day", "mother's day", "mom"]),
    ("Multipurpose", ["multipurpose", "multi-purpose", "all purpose"]),
    ("New Year", ["new year", "new years", "nye", "countdown"]),
    ("Olympic Games", ["olympic", "olympics"]),
    ("Paintball", ["paintball", "airsoft"]),
    ("Party & Celebration", ["party", "celebration", "fiesta", "bash"]),
    ("Pizza & Italian", ["pizza", "italian", "pasta", "pizzeria"]),
    ("Poker & Casino", ["poker", "gambling", "casino", "slot", "blackjack", "roulette", "jackpot"]),
    ("Polar Plunge", ["polar plunge"]),
    ("Pool Party", ["pool party", "swimming pool"]),
    ("Quotes & Motivational", ["quote", "quotes", "motivational", "inspirational"]),
    ("Rap & Hip Hop", ["rap", "hip hop", "hiphop", "rap battle", "freestyle", "emcee"]),
    ("Real Estate", ["real estate", "property", "house", "realtor", "realty", "mortgage"]),
    ("Retirement", ["retirement", "retire", "pension"]),
    ("Retro & Vintage", ["retro", "vintage", "classic", "old school", "throwback", "60s", "70s", "80s", "90s", "nostalgia"]),
    ("Running & Marathon", ["running", "marathon", "5k", "10k", "jogging"]),
    ("Saint Patricks Day", ["saint patrick", "st patrick", "shamrock", "irish", "leprechaun"]),
    ("Shop & Retail", ["shop", "store", "retail", "boutique", "sale", "clearance"]),
    ("Soccer", ["soccer", "futbol"]),
    ("Sports", ["sport", "sports", "athletic", "athlete", "championship", "tournament", "league", "volleyball"]),
    ("Spring", ["spring", "springtime", "cherry blossom"]),
    ("Summer & Tropical", ["summer", "summertime", "tropical", "island", "palm tree", "hawaii"]),
    ("Tattoo", ["tattoo", "ink", "tattoo parlor", "body art"]),
    ("Thanksgiving & Fall", ["thanksgiving", "fall", "autumn", "harvest", "pumpkin", "turkey"]),
    ("Toy Drive", ["toy drive", "toy donation", "angel tree"]),
    ("Travel & Tourism", ["travel", "tourism", "tourist", "vacation", "trip", "wanderlust", "passport", "destination"]),
    ("TV & Broadcast", ["tv", "television", "broadcast"]),
    ("Vape & Smoke", ["vape", "vaping", "e-cigarette"]),
    ("Veterans Day", ["veterans day", "veteran"]),
    ("Wedding", ["wedding", "bride", "groom", "bridal", "engagement", "nuptial"]),
    ("Winter & Snow", ["winter", "snow", "snowflake", "blizzard", "frost", "skiing"]),
    ("Womens Day", ["women day", "womens day", "international women", "girl power"]),
    ("Yoga & Meditation", ["yoga", "yoga class", "meditation", "zen", "mindfulness", "chakra", "pilates"]),

    # ══════════════════════════════════════════════════════════════════════════
    # PLATFORMS & MARKETPLACES
    # ══════════════════════════════════════════════════════════════════════════
]

BUILTIN_CATEGORIES = list(CATEGORIES)  # Keep original copy

# ── Build TOPIC_CATEGORIES set ────────────────────────────────────────────────
# Topic categories describe WHAT a design is ABOUT ("Night Club", "Christmas")
# NOT what the design IS ("Flyers", "Business Cards").
# When design files (PSD/AI) are found in a topic-named folder,
# the context engine overrides the topic with the actual asset type.
TOPIC_CATEGORIES = set()
_in_topics = False
for _cat_name, _ in CATEGORIES:
    if _cat_name == "Accounting & Finance":
        _in_topics = True
    if _in_topics:
        TOPIC_CATEGORIES.add(_cat_name)
    if _cat_name == "Yoga & Meditation":
        break

# Also mark some non-topic categories that are too generic and should be overridden
# when design files + a specific topic are detected
TOPIC_CATEGORIES.update({
    'Cinema & Film', 'Music', 'Art & Photography', 'Photography Presets & Actions',
})


# ── Custom categories persistence ─────────────────────────────────────────────
_CUSTOM_CATS_FILE = os.path.join(_APP_DATA_DIR, 'custom_categories.json')

def load_custom_categories():
    """Load user-defined categories from JSON file."""
    if os.path.exists(_CUSTOM_CATS_FILE):
        try:
            with open(_CUSTOM_CATS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return [(c['name'], c['keywords']) for c in data]
        except Exception:
            pass
    return []

def save_custom_categories(custom_cats):
    """Save user-defined categories to JSON file."""
    data = [{'name': name, 'keywords': kws} for name, kws in custom_cats]
    with open(_CUSTOM_CATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _CategoryIndex.invalidate()  # Rebuild keyword index on next scan

def get_all_categories():
    """Return built-in + custom categories."""
    return BUILTIN_CATEGORIES + load_custom_categories()

def get_all_category_names():
    """Return sorted list of all category names."""
    return sorted(set(name for name, _ in get_all_categories()))



# ── Pre-computed category keyword index ──────────────────────────────────────
# Avoids calling _normalize() on every keyword for every folder during scan.
# Built once on first use, invalidated when custom categories change.
class _CategoryIndex:
    """Pre-normalized keyword index for fast category matching."""
    _instance = None
    _custom_cats_mtime = None

    def __init__(self):
        self._build()

    def _build(self):
        """Build the pre-normalized index from all categories."""
        all_cats = get_all_categories()
        # Pre-normalized list: [(cat_name, cat_norm, [(kw, kw_norm, kw_tokens_sig), ...]), ...]
        self.entries = []
        for cat_name, keywords in all_cats:
            cat_norm = _get_normalize()(cat_name)
            kw_list = []
            for kw in keywords:
                kw_norm = _get_normalize()(kw).strip()
                sig_tokens = frozenset(t for t in kw_norm.split() if len(t) > 2)
                kw_list.append((kw, kw_norm, sig_tokens))
            self.entries.append((cat_name, cat_norm, kw_list))
        try:
            self._custom_cats_mtime = os.path.getmtime(_CUSTOM_CATS_FILE) if os.path.exists(_CUSTOM_CATS_FILE) else None
        except OSError:
            self._custom_cats_mtime = None

    def _is_stale(self):
        """Check if custom categories file has changed since last build."""
        try:
            current = os.path.getmtime(_CUSTOM_CATS_FILE) if os.path.exists(_CUSTOM_CATS_FILE) else None
        except OSError:
            current = None
        return current != self._custom_cats_mtime

    @classmethod
    def get(cls):
        """Get the singleton index, rebuilding if stale."""
        if cls._instance is None or cls._instance._is_stale():
            cls._instance = cls()
        return cls._instance

    @classmethod
    def invalidate(cls):
        """Force rebuild on next access (call after editing custom categories)."""
        cls._instance = None

