"""UniFile — Archive name inference engine.

When a folder contains mostly .zip/.rar/.7z files, their names become the
primary classification signal.  This module maps archive stems to categories
using ordered regex rules, then aggregates votes across all archives in the
folder to produce a single (category, confidence, detail) result.

Rule format: (pattern, category, base_confidence)
  - pattern   : compiled re, matched against the lowercased archive stem
  - category  : must exist in CATEGORIES or custom_categories
  - base_conf : confidence awarded when pattern matches (50-95)

Rules are applied in order; FIRST match per archive wins.
"""

import re
from collections import Counter
from typing import Optional

# ---------------------------------------------------------------------------
# Rule table — ordered, first match wins
# ---------------------------------------------------------------------------
# Each entry: (regex_pattern, category, base_confidence)
# Patterns are matched against the FULL lowercased archive stem.

_RAW_RULES: list[tuple[str, str, int]] = [

    # ── VIDEOHIVE sub-types ────────────────────────────────────────────────
    # Must come before the generic videohive catch-all
    (r'videohive.{0,60}logo.{0,40}(reveal|sting|animation|intro|opener)',    'After Effects - Logo Reveals',           88),
    (r'videohive.{0,60}(logo)',                                               'After Effects - Logo Reveals',           85),
    (r'videohive.{0,60}slideshow',                                            'After Effects - Slideshows',             87),
    (r'videohive.{0,60}(intro|opener)',                                       'After Effects - Intros & Openers',       87),
    (r'videohive.{0,60}(title|titles|kinetic)',                               'After Effects - Titles & Typography',    86),
    (r'videohive.{0,60}lower.{0,5}third',                                     'After Effects - Lower Thirds',           88),
    (r'videohive.{0,60}(promo|commercial|advertisement)',                     'After Effects - Explainer & Promo',      86),
    (r'videohive.{0,60}(corporate)',                                          'After Effects - Explainer & Promo',      83),
    (r'videohive.{0,60}(wedding)',                                            'After Effects - Wedding & Events',       87),
    (r'videohive.{0,60}(christmas|xmas|holiday)',                             'Christmas',                              85),
    (r'videohive.{0,60}transition',                                           'After Effects - Transitions',            87),
    (r'videohive.{0,60}broadcast',                                            'After Effects - Broadcast Package',      88),
    (r'videohive.{0,60}infographic',                                          'After Effects - Infographics & Data',    87),
    (r'videohive.{0,60}countdown',                                            'After Effects - Countdown & Timer',      87),
    (r'videohive.{0,60}(glitch|distortion)',                                  'Glitch & Distortion FX',                 85),
    (r'videohive.{0,60}(instagram|story|stories|social.?media)',              'After Effects - Social Media Templates', 87),
    (r'videohive.{0,60}youtube',                                              'YouTube & Streaming',                    82),
    (r'videohive.{0,60}(particle|particles|dust|snow|sparkle)',               'After Effects - Particles & FX',         85),
    (r'videohive.{0,60}(cinematic|trailer|epic|film)',                        'After Effects - Cinematic & Trailers',   84),
    (r'videohive.{0,60}(lyric|music.?video)',                                 'After Effects - Lyric Video',            85),
    (r'videohive.{0,60}(hud|ui)',                                             'After Effects - HUD & UI',               85),
    (r'videohive.{0,60}(mockup|device)',                                      'After Effects - Mockup & Device',        85),
    (r'videohive.{0,60}(real.?estate)',                                       'Real Estate',                            80),
    (r'videohive',                                                            'After Effects - Templates',              75),

    # ── GRAPHICRIVER / ENVATO ELEMENTS (print/graphics marketplace) ───────
    (r'(graphicriver|graphicstock).{0,60}flyer',                              'Flyers & Print',                         88),
    (r'(graphicriver|graphicstock).{0,60}brochure',                           'Flyers & Print',                         87),
    (r'(graphicriver|graphicstock).{0,60}business.?card',                     'Business Cards',                         90),
    (r'(graphicriver|graphicstock).{0,60}logo',                               'Logos & Branding',                       86),
    (r'(graphicriver|graphicstock).{0,60}(resume|cv)',                        'Resume & CV Templates',                  88),
    (r'(graphicriver|graphicstock).{0,60}mockup',                             'Mockups',                                88),
    (r'(graphicriver|graphicstock).{0,60}(poster|billboard)',                 'Posters',                                85),
    (r'(graphicriver|graphicstock).{0,60}invitation',                         'Invitations & Save the Date',            88),
    (r'(graphicriver|graphicstock).{0,60}certificate',                        'Certificates & Awards',                  88),
    (r'(graphicriver|graphicstock).{0,60}social',                             'Social Media Templates',                 85),
    (r'(graphicriver|graphicstock).{0,60}(powerpoint|presentation)',          'Presentations & PowerPoint',             87),
    (r'(graphicriver|graphicstock).{0,60}infographic',                        'Infographics & Data Viz',                87),
    (r'(graphicriver|graphicstock).{0,60}menu',                               'Menus & Food Templates',                 85),
    (r'(graphicriver|graphicstock).{0,60}banner',                             'Banners & Ads',                          83),
    (r'(graphicriver|graphicstock).{0,60}(t.?shirt|apparel)',                 'Apparel & Merchandise',                  83),
    (r'(graphicriver|graphicstock).{0,60}(catalog|catalogue)',                'Catalogs & Lookbooks',                   83),
    (r'graphicriver|graphicstock',                                            'Flyers & Print',                         70),

    # ── MOTIONELEMENTS / OTHER VIDEO MARKETPLACES ─────────────────────────
    (r'motionelements',                                                       'After Effects - Templates',              72),
    (r'(motion.?array|motionarray)',                                          'After Effects - Templates',              73),
    (r'shareae|ae\.com',                                                      'After Effects - Templates',              72),

    # ── TOOL-SPECIFIC (high-confidence standalone) ────────────────────────
    (r'lightroom.{0,30}(preset|profile|filter)',                              'Lightroom - Presets & Profiles',         90),
    (r'(lr|lrtemplate).{0,15}preset',                                         'Lightroom - Presets & Profiles',         87),
    (r'photoshop.{0,30}action',                                               'Photoshop - Actions',                    90),
    (r'photoshop.{0,30}brush',                                                'Photoshop - Brushes',                    90),
    (r'photoshop.{0,30}(style|effect)',                                       'Photoshop - Styles & Effects',           87),
    (r'(lut|color.?grading).{0,20}(pack|bundle|collection)',                  'Color Grading & LUTs',                   88),
    (r'\blut(s)?\b',                                                          'Color Grading & LUTs',                   82),
    (r'after.?effects?.{0,20}(template|preset|project)',                      'After Effects - Templates',              87),
    (r'premiere.{0,20}(pro.{0,15})?(template|mogrt)',                         'Premiere Pro - Templates',               87),
    (r'\bmogrt\b',                                                            'Premiere Pro - Templates',               85),
    (r'davinci.{0,20}(resolve.{0,15})?(template|macro|grade)',                'DaVinci Resolve - Templates',            85),
    (r'\bdrp\b|\bdrfx\b',                                                     'DaVinci Resolve - Templates',            83),
    (r'capcut.{0,20}(template|effect|pack)',                                  'CapCut - Templates',                     85),
    (r'procreate.{0,20}(brush|stamp|texture|palette|swatch)',                 'Procreate - Brushes & Stamps',           88),
    (r'figma.{0,20}(template|kit|ui|component|resource)',                     'Figma - Templates & UI Kits',            87),
    (r'(serum|sylenth|massive|omnisphere|kontakt|spire|nexus).{0,20}(preset|bank|patch)',   'Music Production - Presets', 88),
    (r'(vst|plugin).{0,15}preset',                                            'Music Production - Presets',             82),
    (r'(ableton|fl.?studio|logic.?pro|pro.?tools|cubase|reaper).{0,20}(project|session|template|pack)', 'Music Production - DAW Projects', 87),
    (r'unreal.{0,20}(engine.{0,15})?(asset|pack|material)',                   'Unreal Engine - Assets',                 85),
    (r'(unity|unity3d).{0,20}(asset|pack)',                                   'Game Assets & Sprites',                  85),
    (r'(safetensor|stable.?diffusion|midjourney|lora|sdxl|comfyui)',          'AI Art & Generative',                    87),

    # ── FONTS ──────────────────────────────────────────────────────────────
    (r'(font|typeface|typography).{0,20}(pack|bundle|family|set)',            'Fonts & Typography',                     88),
    (r'\bfont\b',                                                             'Fonts & Typography',                     78),

    # ── MOCKUPS ────────────────────────────────────────────────────────────
    (r'(device|phone|iphone|laptop|apparel|t.?shirt|mug|bag|packaging).{0,20}mockup', 'Mockups', 90),
    (r'mockup',                                                               'Mockups',                                87),

    # ── LOGO & BRANDING ────────────────────────────────────────────────────
    (r'logo.{0,30}(reveal|sting|animation|intro|opener)',                     'After Effects - Logo Reveals',           88),
    (r'logo.{0,20}(template|kit|pack|bundle|design)',                         'Logos & Branding',                       85),
    (r'(brand|branding).{0,20}(identity|kit|guide|pack)',                     'Logos & Branding',                       87),

    # ── SLIDESHOW ──────────────────────────────────────────────────────────
    (r'(photo|wedding|travel|fashion|event|corporate|minimal|clean).{0,20}slideshow', 'After Effects - Slideshows', 84),
    (r'slideshow',                                                            'After Effects - Slideshows',             78),

    # ── AE SUBCATEGORIES (standalone) ─────────────────────────────────────
    (r'lower.{0,5}thirds?',                                                   'After Effects - Lower Thirds',           85),
    (r'(intro|opener).{0,20}(template|pack)?',                               'After Effects - Intros & Openers',       78),
    (r'kinetic.{0,10}typography',                                             'After Effects - Titles & Typography',    85),
    (r'(title|titles|text).{0,20}(animation|reveal|template)',                'After Effects - Titles & Typography',    82),
    (r'transitions?.{0,10}(pack|bundle)?',                                    'After Effects - Transitions',            82),
    (r'broadcast.{0,20}(package|pack|graphics)',                              'After Effects - Broadcast Package',      87),
    (r'infographic',                                                          'After Effects - Infographics & Data',    80),
    (r'countdown',                                                            'After Effects - Countdown & Timer',      82),
    (r'(glitch|distortion)',                                                  'Glitch & Distortion FX',                 80),
    (r'(particle|bokeh|dust|snow|fire|magic|sparkle).{0,15}(effect|pack|overlay)?', 'After Effects - Particles & FX', 76),
    (r'(cinematic|trailer|epic|film)',                                        'After Effects - Cinematic & Trailers',   75),
    (r'(hud|heads.?up.?display)',                                             'After Effects - HUD & UI',               80),
    (r'lyric.?video',                                                         'After Effects - Lyric Video',            83),
    (r'(emoji|sticker).{0,15}pack',                                           'After Effects - Emoji & Stickers',       80),
    (r'character.{0,15}(animation|animator|rig)',                             'After Effects - Character Animation',    83),

    # ── PRINT & STATIONERY ─────────────────────────────────────────────────
    (r'(flyer|flier|leaflet)',                                                'Flyers & Print',                         85),
    (r'brochure',                                                             'Flyers & Print',                         83),
    (r'business.?card',                                                       'Business Cards',                         88),
    (r'(resume|curriculum.?vitae|\bcv\b.{0,10}template)',                     'Resume & CV Templates',                  88),
    (r'(menu|restaurant.?template|food.?menu|cafe.?menu)',                    'Menus & Food Templates',                 85),
    (r'(certificate|diploma|award.{0,10}ceremony)',                           'Certificates & Awards',                  87),
    (r'(invitation|save.?the.?date)',                                         'Invitations & Save the Date',            85),
    (r'(letterhead|stationery)',                                              'Flyers & Print',                         82),
    (r'(voucher|coupon|gift.?card)',                                          'Coupons & Vouchers',                     85),
    (r'(packaging|box.?design|dieline|label.?design)',                        'Packaging & Product',                    83),
    (r'(book.?cover|ebook.?cover)',                                           'Book Covers & eBook',                    85),
    (r'(t.?shirt|apparel|merch)',                                             'Apparel & Merchandise',                  82),
    (r'(catalog|catalogue|lookbook)',                                         'Catalogs & Lookbooks',                   83),
    (r'(poster|billboard)',                                                   'Posters',                                80),
    (r'(rollup|roll.?up|pull.?up.?banner)',                                   'Flyers & Print',                         80),
    (r'(banner|web.?banner|ad.?banner)',                                      'Banners & Ads',                          78),

    # ── SOCIAL MEDIA ───────────────────────────────────────────────────────
    (r'instagram.{0,20}(story|stories|post|template|pack)',                   'After Effects - Social Media Templates', 85),
    (r'(twitch|stream|obs).{0,20}(overlay|template|alert|pack)',              'YouTube & Streaming',                    83),
    (r'youtube.{0,20}(thumbnail|banner|template|pack)',                       'YouTube & Streaming',                    85),
    (r'social.?media.{0,20}(pack|template|kit)',                              'Social Media Templates',                 85),
    (r'instagram|facebook|tiktok',                                            'Social Media Templates',                 75),

    # ── PRESENTATIONS ──────────────────────────────────────────────────────
    (r'(powerpoint|pptx).{0,15}(template|slide)',                             'Presentations & PowerPoint',             88),
    (r'keynote.{0,15}(template|slide)',                                       'Presentations & PowerPoint',             88),
    (r'(presentation|pitch.?deck|google.?slides)',                            'Presentations & PowerPoint',             82),

    # ── ILLUSTRATION / ART ─────────────────────────────────────────────────
    (r'(watercolor|watercolour)',                                             'Illustrations & Clipart',                78),
    (r'(clipart|clip.?art)',                                                  'Illustrations & Clipart',                82),
    (r'(hand.?drawn|hand.?lettered)',                                         'Illustrations & Clipart',                78),
    (r'illustration.{0,15}(pack|set|bundle)',                                 'Illustrations & Clipart',                82),

    # ── ICONS ──────────────────────────────────────────────────────────────
    (r'icon.{0,15}(pack|set|bundle)',                                         'Icons & Icon Packs',                     85),

    # ── PATTERNS ───────────────────────────────────────────────────────────
    (r'(seamless.?pattern|pattern.{0,15}(pack|set|bundle))',                  'Patterns & Seamless',                    83),

    # ── UI/UX ──────────────────────────────────────────────────────────────
    (r'(ui.?kit|wireframe|design.?system)',                                   'UI & UX Design',                         83),

    # ── PHOTO EFFECTS & OVERLAYS ───────────────────────────────────────────
    (r'(light.?leak|lens.?flare|bokeh|film.?grain).{0,15}(pack|overlay)',    'Photo Effects & Overlays',               83),
    (r'(overlay|overlays).{0,15}(pack|bundle)',                               'Photo Effects & Overlays',               80),

    # ── STOCK CONTENT ──────────────────────────────────────────────────────
    (r'stock.{0,10}(photo|photos?|image)',                                    'Stock Photos - General',                 83),
    (r'stock.{0,10}(footage|video)',                                          'Stock Footage - General',                83),

    # ── SEASONAL / EVENTS ──────────────────────────────────────────────────
    (r'(christmas|xmas).{0,20}(template|pack|card|flyer|bundle)',             'Christmas',                              86),
    (r'christmas|xmas',                                                       'Christmas',                              75),
    (r'wedding.{0,20}(template|invitation|card|pack)',                        'Wedding',                                83),
    (r'wedding',                                                              'Wedding',                                75),
    (r'birthday.{0,20}(card|invitation|flyer|template)',                      'Flyers & Print',                         78),
    (r'(halloween|hanukkah|thanksgiving|valentine)',                          'Holidays & Seasonal',                    75),

    # ── AUDIO / MUSIC PRODUCTION ───────────────────────────────────────────
    (r'(sfx|sound.?effect).{0,15}(pack|library)',                             'Sound Effects & SFX',                    85),
    (r'(sample|loop).{0,15}(pack|library)',                                   'Stock Music & Audio',                    78),

    # ── GAME DEVELOPMENT ───────────────────────────────────────────────────
    (r'(game.?asset|sprite.?sheet|tileset|pixel.?art)',                       'Game Assets & Sprites',                  85),
    (r'(svg|dxf).{0,20}(cut|cricut|silhouette)',                              'Cutting Machine - SVG & DXF',            87),
    (r'(cricut|silhouette.?cameo|glowforge)',                                 'Cutting Machine - SVG & DXF',            87),
    (r'(svg|dxf).{0,10}(file|design|bundle)',                                 'Cutting Machine - SVG & DXF',            78),

    # ── WEB ────────────────────────────────────────────────────────────────
    (r'(html|bootstrap).{0,15}template',                                      'Web Templates & HTML',                   83),
    (r'(landing.?page|website.?template)',                                    'Web Templates & HTML',                   82),
    (r'email.{0,15}(template|newsletter)',                                    'Email Templates',                        85),

    # ── 3D ─────────────────────────────────────────────────────────────────
    (r'(c4d|cinema.?4d).{0,15}(pack|template|model)',                         '3D',                                     83),
    (r'blender.{0,15}(pack|addon|asset|model)',                               '3D',                                     78),
    (r'3d.{0,15}(model|object|scene|asset|pack)',                             '3D - Models & Objects',                  78),

    # ── INFOGRAPHIC ────────────────────────────────────────────────────────
    (r'infographic',                                                          'Infographics & Data Viz',                78),

    # ── GENERAL MOTION / VIDEO ─────────────────────────────────────────────
    (r'(promo|promotional).{0,20}(video|template)',                           'After Effects - Explainer & Promo',      74),
    (r'motion.{0,15}(graphic|template|pack)',                                 'After Effects - Templates',              72),
]

# Compiled rule cache
_COMPILED: Optional[list] = None


def _get_rules() -> list:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = [(re.compile(p), cat, conf) for p, cat, conf in _RAW_RULES]
    return _COMPILED


def classify_archive_name(stem: str) -> tuple[Optional[str], int]:
    """Classify a single archive stem.  Returns (category, confidence) or (None, 0)."""
    s = stem.lower()
    for pattern, category, confidence in _get_rules():
        if pattern.search(s):
            return category, confidence
    return None, 0


def aggregate_archive_names(archive_stems: list[str]) -> tuple[Optional[str], int, str]:
    """Aggregate classification votes from multiple archive names.

    Returns (category, confidence, detail) or (None, 0, '').
    Confidence is boosted when archives strongly agree.
    """
    if not archive_stems:
        return None, 0, ''

    votes: Counter = Counter()
    conf_sum: dict[str, int] = {}
    match_count = 0

    for stem in archive_stems:
        cat, conf = classify_archive_name(stem)
        if cat:
            votes[cat] += 1
            conf_sum[cat] = conf_sum.get(cat, 0) + conf
            match_count += 1

    if not votes:
        return None, 0, ''

    top_cat, top_votes = votes.most_common(1)[0]
    total = len(archive_stems)
    match_ratio = top_votes / total
    avg_conf = conf_sum[top_cat] // top_votes

    # Base confidence from rule average
    conf = avg_conf

    # Boost for consensus
    if match_ratio >= 0.9:
        conf = min(conf + 8, 95)
    elif match_ratio >= 0.7:
        conf = min(conf + 5, 93)
    elif match_ratio >= 0.5:
        conf = min(conf + 2, 90)
    elif match_ratio < 0.3:
        conf = max(conf - 10, 50)

    # Boost for large sample sizes
    if top_votes >= 10:
        conf = min(conf + 3, 95)
    elif top_votes >= 5:
        conf = min(conf + 1, 93)

    # Penalise if there's strong competition from another category
    if len(votes) >= 2:
        second_cat, second_votes = votes.most_common(2)[1]
        competition = second_votes / top_votes
        if competition > 0.5:
            conf = max(conf - 8, 50)

    detail = (f"archive:{top_votes}/{total} archives→{top_cat} "
              f"({match_ratio:.0%} consensus, avg_rule={avg_conf})")
    return top_cat, conf, detail
