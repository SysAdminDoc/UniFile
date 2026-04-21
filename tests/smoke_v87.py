"""UniFile v8.7.0 smoke tests — new rules validation."""
import sys, io
sys.path.insert(0, '.')

# Force UTF-8 output so the arrow character in detail strings doesn't crash on cp1252 terminals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from unifile.archive_inference import classify_archive_name, aggregate_archive_names

passed = 0
failed = 0


def check(stem, expected_cat, min_conf=70, label=None):
    global passed, failed
    cat, conf = classify_archive_name(stem)
    ok = cat == expected_cat and conf >= min_conf
    tag = 'OK  ' if ok else 'FAIL'
    display = label or stem
    print(f"  {tag} [{conf}] {display!r} -> {cat!r}")
    if ok:
        passed += 1
    else:
        failed += 1
        if cat != expected_cat:
            print(f"          expected: {expected_cat!r}")


# ── Final Cut Pro ─────────────────────────────────────────────────────────────
print("Final Cut Pro rules:")
check('final-cut-pro-title-pack',        'Final Cut Pro - Templates', label='final-cut-pro-title-pack')
check('fcpx-transition-bundle',           'Final Cut Pro - Templates', label='fcpx-transition-bundle')
check('final-cut-effects-vol2',           'Final Cut Pro - Templates', label='final-cut-effects-vol2')
check('fcpx-plugin-collection',           'Final Cut Pro - Templates', label='fcpx-plugin-collection')

# ── Canva ─────────────────────────────────────────────────────────────────────
print("\nCanva rules:")
check('canva-social-media-templates',     'Canva - Templates', label='canva-social-media-templates')
check('canva-flyer-design-bundle',        'Canva - Templates', label='canva-flyer-design-bundle')
check('canva-presentation-pack',          'Canva - Templates', label='canva-presentation-pack')
check('canva-logo-kit',                   'Canva - Templates', label='canva-logo-kit')

# ── Filmora ───────────────────────────────────────────────────────────────────
print("\nFilmora rules:")
check('filmora-title-templates',          'After Effects - Templates', label='filmora-title-templates')
check('wondershare-filmora-effects',      'After Effects - Templates', label='wondershare-filmora-effects')

# ── Pond5 ─────────────────────────────────────────────────────────────────────
print("\nPond5 rules:")
check('pond5-sfx-pack',                   'Sound Effects & SFX',      label='pond5-sfx-pack')
check('pond5-drone-footage',              'Stock Footage - General',  label='pond5-drone-footage')
check('pond5-motion-template',            'After Effects - Templates', label='pond5-motion-template')
check('pond5-ambient-music',              'Stock Music & Audio',      label='pond5-ambient-music')

# ── Storyblocks / Videoblocks ────────────────────────────────────────────────
print("\nStoryblocks/Videoblocks rules:")
check('storyblocks-footage-bundle',       'Stock Footage - General',  label='storyblocks-footage-bundle')
check('videoblocks-music-pack',           'Stock Music & Audio',      label='videoblocks-music-pack')
check('storyblocks-motion-graphics',      'After Effects - Templates', label='storyblocks-motion-graphics')

# ── Epidemic Sound / Looperman / Splice / ZapSplat ───────────────────────────
print("\nAudio source rules:")
check('epidemic-sound-collection',        'Stock Music & Audio',      label='epidemic-sound-collection')
check('looperman-drum-loops',             'Stock Music & Audio',      label='looperman-drum-loops')
check('splice-sample-pack-vol3',          'Stock Music & Audio',      label='splice-sample-pack-vol3')
check('zapsplat-sfx-library',             'Sound Effects & SFX',      label='zapsplat-sfx-library')
check('soundsnap-effects-bundle',         'Sound Effects & SFX',      label='soundsnap-effects-bundle')

# ── AEJuice / MotionBro / Mixkit ─────────────────────────────────────────────
print("\nAEJuice / MotionBro / Mixkit rules:")
check('aejuice-starter-pack',             'After Effects - Templates', label='aejuice-starter-pack')
check('motionbro-extension-pack',         'After Effects - Templates', label='motionbro-extension-pack')
check('mixkit-music-pack',                'Stock Music & Audio',      label='mixkit-music-pack')
check('mixkit-video-clips',               'Stock Footage - General',  label='mixkit-video-clips')
check('mixkit-ae-template',               'After Effects - Templates', label='mixkit-ae-template')

# ── Numeric Envato ID new subcategories ─────────────────────────────────────
print("\nNumeric ID extended subcategories:")
check('12345678-particle-fx-pack',        'After Effects - Particles & FX',  label='12345678-particle-fx-pack')
check('23456789-character-animation-rig', 'After Effects - Character Animation', label='23456789-character-animation-rig')
check('34567890-lyric-video-template',    'After Effects - Lyric Video',     label='34567890-lyric-video-template')
check('45678901-hud-elements-pack',       'After Effects - HUD & UI',        label='45678901-hud-elements-pack')
check('56789012-countdown-timer',         'After Effects - Countdown & Timer', label='56789012-countdown-timer')
check('67890123-logo-mockup-pack',        'Photoshop - Mockups',             label='67890123-logo-mockup-pack')
check('78901234-business-card-template',  'Business Cards',                  label='78901234-business-card-template')
check('89012345-resume-cv-pack',          'Resume & CV',                     label='89012345-resume-cv-pack')
check('90123456-logo-design-kit',         'Logo & Identity',                 label='90123456-logo-design-kit')
check('12309876-presentation-template',   'Presentations & PowerPoint',      label='12309876-presentation-template')

# ── PS subcategory collapse ──────────────────────────────────────────────────
print("\nPS subcategory collapse test:")
stems = [
    'photoshop-actions-collection-vol1',
    'photoshop-brushes-mega-pack',
    'photoshop-styles-and-effects',
    'photoshop-actions-pro-bundle',
    'photoshop-brushes-watercolor',
]
cat, conf, detail = aggregate_archive_names(stems)
ok = cat == 'Photoshop - Templates & Composites' and conf >= 70
tag = 'OK  ' if ok else 'FAIL'
print(f"  {tag} [{conf}] PS collapse -> {cat!r}")
if ok:
    passed += 1
else:
    failed += 1
    print(f"       expected: 'Photoshop - Templates & Composites'")
print(f"  Detail: {str(detail)[:100]}")

print(f"\n{passed}/{passed + failed} passed")
if failed:
    sys.exit(1)
