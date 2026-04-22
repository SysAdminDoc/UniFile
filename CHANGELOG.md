# Changelog

All notable changes to UniFile will be documented in this file.

## [v8.9.4]

- Refined: **Niche helper dialogs now feel more review-first** — Before/After comparison, AI Event Grouping, and the rename-source file picker now provide clearer summaries, better empty/selection guidance, and calmer card-based layout treatment so these smaller decision points feel intentional instead of legacy
- Refined: **Comparison and rename trust signals** — source-vs-destination previews now explain what each side means more clearly, while rename-source selection now reports candidate counts, filtered results, and the currently selected cleaned filename more explicitly
- Fixed: **Thin selection feedback in helper flows** — event grouping now makes selection state and apply intent clearer, and the rename picker no longer leaves filtering or candidate availability ambiguous

## [v8.9.3]

- Refined: **Editor and rules workflows feel calmer and more deliberate** — Custom Categories, Destination Preview, Classification Rules, Plugin Manager, Watch History, and CSV Sort Rules now present stronger summaries, clearer helper copy, and better action emphasis so power-user setup screens feel consistent with the premium shell
- Refined: **Automation dialogs now communicate order and intent better** — rule-driven workflows now explain that first-match-wins logic more clearly, surface better empty states, and reduce silent or ambiguous editor states while creating, cloning, testing, and saving rules
- Fixed: **Thin utility-screen affordances** — destructive actions in supporting dialogs now read more clearly, list-heavy views provide stronger context before selection, and CSV rule editing now keeps its summary in sync with the current table state

## [v8.9.2]

- Refined: **Secondary workflow panels now match the premium shell** — Tag Library, Media Lookup, and Virtual Library now use stronger section hierarchy, calmer search and empty-state copy, more intentional cards, clearer review-first action emphasis, and better feedback after add/apply/export/search flows
- Refined: **Theme consistency inside inline content panels** — the remaining heavy inline panels now re-apply their custom header, preview, detail, and status styling when the active theme changes, preventing the shell from feeling cohesive while those panels drift
- Fixed: **Thin or silent panel states** — Media Lookup now disables metadata actions until detail is ready, Tag Library surfaces clearer no-selection and action feedback, and Virtual Library now reports invalid paths, zero-match searches, empty overlays, and completed scans more clearly

## [v8.9.1]

- Refined: **Premium shell polish across the main workspace** — upgraded the organizer shell with a stronger action hierarchy, richer workflow copy, trust badges, more spacious cards, clearer empty states, calmer progress feedback, and better status-bar defaults so the product feels more intentional at first glance and during long sessions
- Refined: **Shared dark-theme design system** — improved the global QSS for button emphasis, danger/success semantics, focus/disabled states, input surfaces, tabs, tables, scrollbars, and splitter affordances to make the entire application feel more cohesive and premium
- Refined: **Settings, cleanup, duplicate, and support dialogs** — introduced a consistent dialog-header pattern, normalized action emphasis, simplified status messaging, and improved review-first affordances across AI settings, advanced settings, cleanup tools, duplicate tools, protected paths, theme picker, and utility dialogs
- Fixed: **Stale version and trust surfaces** — the app window title, sidebar branding, launch/bootstrap metadata, and docs now all reflect the current release instead of showing outdated `v8.0.0` references

## [v8.9.0]

- Fixed: **`.cube`/`.3dl`/`.lut` extension mapping** — previously routed to `Premiere Pro - LUTs & Color`; corrected to `Color Grading & LUTs` since LUT files are app-agnostic (work in Resolve, FCPX, Premiere, Photoshop, etc.); confidence adjusted to 90/88
- Added: **AI art platform rules** in `archive_inference.py` — `civitai`/`civit.ai` with model/lora/checkpoint/merge sub-types (88), generic `\bcivitai\b` catch-all (82), and `hugging.face` model/lora/safetensor/checkpoint (85); placed before the existing `safetensor`/`stable.diffusion` generic rule
- Added: **3D marketplace archive rules** — TurboSquid (sub-typed character/vehicle/weapon/prop 88, generic 82), CGTrader (sub-typed model/character/scene 88, generic 80), Sketchfab (sub-typed model/scene/pack 85, generic 78), KitBash3D (kit/pack/model/bundle 88), Renderosity/Daz3D/Poser (sub-typed figure/character/prop 85, generic 78), Poly Haven/HDRI Haven/AmbientCG (→ `3D - Materials & Textures` 88), Substance Painter/Designer/SBSAR (material/texture/pack 88), HDRI pack keyword (85), Fab/Unreal marketplace (→ `Unreal Engine - Assets` 85)
- Added: **Game asset marketplace rules** — itch.io (asset/pack/tileset/sprite/game 85), OpenGameArt (85), Kenney (asset/pack/sprite 85), RPG Maker (asset/pack/tileset 83)
- Added: **Music production marketplace rules** — Loopmasters (sample/loop/pack/kit 85, generic 78), Native Instruments/NI Komplete (library/preset/pack/expansion 87), Spitfire Audio (library/pack/expansion/instrument 87), ADSR/ADSR Sounds (sample/preset/pack 82), Samples From Mars (85)
- Added: **10 new extension mappings** — `.cr3` → `Photography - RAW Files` (Canon CR3 RAW), `.exr` → `3D - Materials & Textures` (OpenEXR for HDRI/VFX renders), `.sbs`/`.sbsar` → `3D - Materials & Textures` (Substance Designer/Painter), `.ztl` → `3D` (ZBrush tool), `.usd`/`.usda`/`.usdc`/`.usdz` → `3D - Models & Objects` (Apple AR/USD scene files), `.sf2`/`.sfz` → `Music Production - Presets` (SoundFont), `.nki`/`.nkx`/`.nkc` → `Music Production - Presets` (Kontakt instruments), `.ptx` → `Music Production - DAW Projects` (Pro Tools session), `.cpr` → `Music Production - DAW Projects` (Cubase project), `.xcf` → `Clipart & Illustrations` (GIMP)
- Added: **Composition heuristics** — USD/USDZ detection (≥ 2 files at ≥ 30% → `3D - Models & Objects` 76), Substance material detection (≥ 2 `.sbs`/`.sbsar` at ≥ 30% → `3D - Materials & Textures` 78), OpenEXR detection (≥ 3 `.exr` at ≥ 30% → `3D - Materials & Textures` 72); `.cr3` added to `raw_exts` counter
- Added: **14 new FILENAME_ASSET_MAP entries** — TurboSquid, CGTrader, Sketchfab, KitBash3D, Poly Haven/HDRI Haven/AmbientCG, Substance material packs, Daz3D/Poser/Renderosity, Civitai, itch.io, OpenGameArt/Kenney, Loopmasters, Native Instruments/Kontakt/Spitfire Audio



- Fixed: **Duplicate `is_generic_aep` and `_score_aep` definitions** in `categories.py` — first copy (lines 26–143) was silently shadowed by an identical second copy (lines 150–267); removed the second (dead) copy; `CATEGORY ENGINE` header now appears once
- Removed: **Dead code in `classifier.py`** — `analyze_folder_composition()` (superseded by `_scan_folder_once()`), `_classify_by_composition()` (superseded by `_classify_composition_from_scan()`), and `find_near_duplicates()` (referenced undefined `IMAGE_EXTS` and `_compute_phash`; never called) — all three functions deleted
- Added: **`_PREMIERE_SUBCATEGORIES` frozenset + PR collapse logic** in `aggregate_archive_names()` — mirrors AE/PS collapse; when ≥ 2 Premiere Pro subcategories (`Premiere Pro - Transitions`, `- Titles & Text`, `- LUTs & Color`, `- Presets & Effects`, `- Sound Design`) each receive votes and PR votes dominate by 1.5× (≥ 3 total), result collapses to `Premiere Pro - Templates`
- Added: **Motion Array sub-typed rules** — 10 sub-type rules before the generic MotionArray catch-all: titles, transitions, logo reveals, slideshows, lower thirds, broadcast, social/Instagram, promo/explainer, mogrt/premiere (→ `Premiere Pro - Templates`), LUT/color grade (→ `Color Grading & LUTs`)
- Added: **Envato Elements marketplace block** — 10 sub-typed rules for `envato.elements` / `elements.envato`: mogrt/premiere, transitions, logo reveals, titles, slideshows, fonts, mockups, stock photos, stock music, generic catch-all
- Added: **Shutterstock / Getty Images / iStock archive rules** — footage sub-type (→ `Stock Footage - General`), music sub-type (→ `Stock Music & Audio`), generic (→ `Stock Photos - General`) for each platform
- Added: **UI8 / Gumroad / ArtStation / Iconscout archive rules** — UI8 (kit/template/component → `UI & UX Design`), Gumroad (font/brush/svg/action sub-typed + catch-all), Iconscout/Craftwork (icons), ArtStation (brush/texture/model sub-typed + catch-all)
- Added: **Standalone Premiere Pro sub-typed archive rules** — `premiere.*transition`, `handy.seamless`, `premiere.*title`, `premiere.*lower third`, `premiere.*lut`, `premiere.*preset`, `premiere.*sound` — all routed to appropriate `Premiere Pro - *` subcategories for the collapse to work correctly
- Added: **10 new extension mappings** — `.glb`/`.gltf` → `3D - Models & Objects`, `.otc`/`.ttc` → `Fonts & Typography` (font collections), `.lottie` → `Animated Icons`, `.bmpr` → `UI & UX Design` (Balsamiq), `.rp`/`.rplib` → `UI & UX Design` (Axure RP), `.vsdx`/`.vsd` → `Forms & Documents` (Visio), `.sla`/`.slaz` → `Flyers & Print` (Scribus), `.pxm`/`.pxd` → `Clipart & Illustrations` (Pixelmator), `.splinecode` → `UI & UX Design`
- Added: **Composition heuristics improvements** — mixed RAW+JPEG detection (≥ 2 RAW + ≥ 1 JPEG at ≥ 50% total → `Photography - RAW Files` 73), glTF/GLB detection (≥ 2 GLB/GLTF at ≥ 40% → `3D - Models & Objects` 78), Lottie animation detection (≥ 2 `.lottie` files → `Animated Icons` 72); `.rpp` added to DAW extensions; `.otc`/`.ttc` added to font extension counts
- Added: **17 new FILENAME_ASSET_MAP entries** — Motion Array, Envato Elements, Shutterstock, Getty/iStock, UI8, Iconscout/Craftwork/Flaticon, Lottie/Bodymovin, Balsamiq, Axure RP, Visio, Scribus, Spline, glTF/GLB, ArtStation assets, Gumroad, Premiere Pro mogrt/transitions, Handy Seamless Transitions



- Fixed: **`SystemExit` swallowed by `except ImportError`** in `bootstrap.py` — `face_recognition` module calls `quit()` when `face_recognition_models` is absent, raising `SystemExit`; changed to `except (ImportError, SystemExit)` so the missing-models case is handled gracefully without killing the process
- Fixed: **`"Calendars & Planners"`** in `FILENAME_ASSET_MAP` → corrected to `"Calendar"` to match actual category name; also added `monthly planner`, `wall calendar`, `desk calendar`, `editorial calendar` keywords
- Added: **3 new categories** — `Canva - Templates`, `Final Cut Pro - Templates`, `3D Printing - STL Files` (with rich keyword lists)
- Added: **11 new extension mappings** — `.rpp` → `Music Production - DAW Projects`, `.band`/`.bandproject` → `Music Production - DAW Projects`, `.fcpbundle`/`.fcpxml` → `Final Cut Pro - Templates`, `.aco` → `Photoshop - Gradients & Swatches`, `.brushset` → `Procreate - Brushes & Stamps`, `.hip`/`.hiplc`/`.hipnc` → `3D` (Houdini), `.ma`/`.mb` → `3D` (Maya), `.max` → `3D` (3ds Max), `.stl`/`.3mf` → `3D Printing - STL Files` (overrides `3D - Models & Objects` when STL-dominant); `.fcpbundle`/`.fcpxml` added to `DESIGN_TEMPLATE_EXTS`
- Added: **`_PS_SUBCATEGORIES` frozenset + PS collapse logic** in `aggregate_archive_names()` — mirrors the AE collapse pattern; when ≥ 2 PS subcategories (`Photoshop - Actions`, `Brushes`, `Styles & Effects`, `Gradients & Swatches`, `Patterns`, `Mockups`, `Overlays`) each receive votes and PS votes dominate by 1.5× (≥ 3 total PS votes), result collapses to `Photoshop - Templates & Composites`
- Added: **14 numeric Envato ID subcategory rules** — previously unhandled sub-types now classified instead of falling through to the generic AE catch-all: particle/FX, character animation, lyric video, HUD/UI, countdown/timer, mockup, font/typeface, flyer, business card, resume/CV, logo, presentation/PowerPoint
- Added: **4 GraphicRiver PS sub-rules** — `graphicriver.*(action|actions)` → `Photoshop - Actions`, `graphicriver.*(brush|brushes)` → `Photoshop - Brushes`, `graphicriver.*(style|styles|effect|effects)` → `Photoshop - Styles & Effects`, `graphicriver.*(pattern|patterns)` → `Photoshop - Patterns`
- Added: **New marketplace archive rules** — Final Cut Pro/FCPX (typed: title/transition/effect/template/plugin/generator + catch-all), Canva (typed: template/design/graphic/social/flyer/resume/presentation + catch-all), Filmora/Wondershare (typed + catch-all), Pond5 (typed: SFX/footage/motion/music), Storyblocks/Videoblocks (typed: footage/music/motion), Epidemic Sound, Looperman (typed + catch-all), Splice (typed), ZapSplat/SoundSnap (typed + catch-all), AEJuice (typed + catch-all), MotionBro, Mixkit (typed: footage/music/motion + catch-all)
- Added: **FILENAME_ASSET_MAP entries** — Canva, Final Cut Pro, 3D printing, Filmora, Pond5/Storyblocks/Videoblocks/Epidemic Sound (stock audio), Looperman/Splice/ZapSplat/SoundSnap (SFX/loops), AEJuice/MotionBro/Mixkit/Envato Elements
- Added: **Composition heuristics improvements** in `_classify_composition_from_scan()` — LUT packs (≥ 2 `.cube`/`.3dl`/`.lut` files at ≥ 30% ratio → `Color Grading & LUTs`), 3D printing packs (≥ 2 `.stl`/`.3mf` at ≥ 40% → `3D Printing - STL Files`), icon packs (≥ 8 PNG/SVG in `/icons/` subfolder → `Icons & Symbols`), texture packs (images in `/textures/` or `/materials/` subfolder → `3D - Materials & Textures`), large icon packs (≥ 20 PNG/SVG at ≥ 70% → `Icons & Symbols`)
- Rule ordering: FCPX, Canva, and Filmora rules placed in tool-specific section (before generic AE standalone subcategory rules) to prevent false matches on generic title/transition/social-media rules



- Added: **5 new tool-specific categories** — `Sketch - UI Resources`, `Adobe XD - Templates`, `Affinity - Designer Files`, `Affinity - Photo Edits`, `Affinity - Publisher Layouts`
- Added: **7 new extension mappings** — `.sketch` → `Sketch - UI Resources`, `.xd` → `Adobe XD - Templates`, `.afdesign` → `Affinity - Designer Files`, `.afphoto` → `Affinity - Photo Edits`, `.afpub` → `Affinity - Publisher Layouts`, `.kra`/`.clip` → `Clipart & Illustrations`; `.xd`, `.kra`, `.clip` added to `DESIGN_TEMPLATE_EXTS`
- Added: **26 new marketplace archive rules** — Creative Market (sub-typed: font/brush/mockup/logo/vector/action + catch-all), Creative Fabrica (SVG/craft + font), Design Bundles (SVG/craft), Font Bundles, Freepik (mockup/photo/vector), Vecteezy/VectorStock → `Vectors & SVG`, ArtGrid → `Stock Footage - General`, ArtList → `Stock Music & Audio`, Placeit/SmartMockups → `Photoshop - Mockups`, Pixabay/Unsplash/Pexels → `Stock Photos - General`
- Added: **Sketch/XD/Affinity archive rules** — archive names containing these tool names now route to the correct new categories
- Added: **`_AE_SUBCATEGORIES` collapse in `aggregate_archive_names()`** — when ≥ 2 After Effects subcategories each receive votes and AE votes dominate by 1.5× over non-AE votes (≥ 3 total AE votes), result collapses to `After Effects - Templates` instead of a single arbitrarily-winning subcategory
- Fixed: **Dead infographic rule** — standalone `(r'infographic', 'After Effects - Infographics & Data')` at position ~156 made the generic `(r'infographic', 'Infographic')` rule unreachable. Replaced with two motion-specific rules (`animated?.*infographic` / `infographic.*(animated?|motion|video)`); generic `Infographic` rule now fires for non-motion packs
- Added: **FILENAME_ASSET_MAP entries** — Sketch/XD/Affinity keyword entries; Cricut/SVG cut file / sublimation / vinyl cut → `Cutting Machine - SVG & DXF`; Shopify/WooCommerce themes → `Website Design`; sample/loop packs → `Stock Music & Audio`; MIDI pack → `Music Production - DAW Projects`



- Fixed: **Critical category name mismatches** — ~19 category names in `archive_inference.py` and `FILENAME_ASSET_MAP` didn't match actual category names in `categories.py`, causing files to land in wrong/nonexistent folders. All corrected:
  - `'YouTube & Streaming'` → `'YouTube & Video Platform'`; twitch/stream rules → `'Twitch & Streaming'`
  - `'Web Templates & HTML'` → `'Website Design'`
  - `'Email Templates'` → `'Email & Newsletter'`
  - `'Banners & Ads'` → `'Banners'`
  - `'Icons & Icon Packs'` → `'Icons & Symbols'`
  - `'Patterns & Seamless'` → `'Patterns - Seamless'`
  - `'Photo Effects & Overlays'` → `'Overlays & Effects'`
  - `'Infographics & Data Viz'` → `'Infographic'`
  - `'Illustrations & Clipart'` → `'Clipart & Illustrations'`
  - `'Coupons & Vouchers'` → `'Gift Voucher & Coupon'`
  - `'Apparel & Merchandise'` → `'Clothing & Apparel'`
  - `'Catalogs & Lookbooks'` → `'InDesign - Magazine & Editorial'`
  - `'Book Covers & eBook'` → `'Book & Literature'`
  - `'Logos & Branding'` → `'Logo & Identity'`
  - `'Mockups'` (generic) → `'Photoshop - Mockups'`; device/apparel/packaging/branding/print/signage → specific `Mockups - *` subcategories
  - `'Social Media Templates'` → `'Social Media'`
  - `'Certificates & Awards'` → `'Certificate'`
  - `'Resume & CV Templates'` → `'Resume & CV'`
  - `'Menus & Food Templates'` → `'Menu Design'`
  - `'Wedding & Events'` → `'Wedding'`
  - Letterhead/stationery rules → `'Letterhead & Stationery'`
  - Rollup banner rules → `'Rollup Banners & Signage'`
- Fixed: **Archive inference skipped on topic-named folders** — `_apply_context_from_scan()` exited early at `has_design_files=False` before archive inference could fire. Archive check now runs before that gate so folders like "Christmas" full of Videohive ZIPs classify correctly
- Fixed: **Archive threshold too strict** — changed from `>= 25%` to `>= 5 archives OR >= 15%` so preview images don't dilute the archive ratio
- Added: **AudioJungle marketplace rules** — `audiojungle` → `'Stock Music & Audio'`; sfx variants → `'Sound Effects & SFX'`
- Added: **ThemeForest/CodeCanyon rules** — `themeforest`/WordPress themes → `'Website Design'`
- Added: **Numeric Envato ID prefix rules** (7-9 digit IDs like `25461234-wedding-slideshow.zip`) — 12 specific AE subcategory rules + generic catch-all `'After Effects - Templates'`
- Added: WordPress/WooCommerce/Elementor template rules → `'Website Design'`



- Added: **Archive name inference engine** (`unifile/archive_inference.py`) — 140+ regex rules classify ZIP/RAR/7z folders by filename patterns (marketplace-aware: Videohive, GraphicRiver, MotionElements; AE subcategories, print, social, seasonal, audio, game dev, 3D, and more)
- Added: `aggregate_archive_names(stems)` voting system — samples all archive names in a folder, computes consensus category with confidence scaling
- Changed: `_scan_folder_once()` now collects archive stems; adds them to `all_filenames_clean` for keyword matching bonus
- Changed: `_classify_composition_from_scan()` — when a folder is ≥25% archives and has ≥2 archives, triggers archive name inference as highest-priority rule
- Added: 4 new categories — `CorelDRAW - Vectors & Assets`, `Apple Motion - Templates`, `Cutting Machine - SVG & DXF`, `After Effects - Cinematic & Trailers`
- Added: 9 new extension mappings — `.cdr` (CorelDRAW), `.motn` (Apple Motion), `.dxf` (cutting machine), `.dds/.tga` (3D textures), `.hdr` (3D HDR), `.fon` (bitmap fonts), `.ait` (Illustrator templates), `.pub` (Publisher)

## [v8.3.0]

- Fixed: **Critical NameError bug** — `DESIGN_TEMPLATE_EXTS`, `VIDEO_TEMPLATE_EXTS`, `FILENAME_ASSET_MAP`, `_GENERIC_DESIGN_CATEGORIES` were defined in `ollama.py` but referenced in `classifier.py` without import; any `tiered_classify()` call on a real folder path would crash
- Changed: Moved and expanded all four constants into `classifier.py` (their actual point of use); removed stale definitions from `ollama.py`
- Added: 10 new categories — `Figma - Templates & UI Kits`, `DaVinci Resolve - Templates`, `CapCut - Templates`, `Game Assets & Sprites`, `Unreal Engine - Assets`, `AI Art & Generative`, `Procreate - Brushes & Stamps`, `Music Production - Presets`, `Music Production - DAW Projects`, `Photography - RAW Files`
- Added: 20 new extension mappings in `EXTENSION_CATEGORY_MAP` covering `.fig`, `.drp/.drfx`, `.als/.flp/.logicx`, `.procreate`, `.nks/.nksn`, `.vstpreset/.fxp/.fxb`, `.unitypackage`, `.uproject/.uasset`, `.ase/.aseprite`, RAW camera formats (`.nef/.cr2/.arw` etc.), `.safetensors/.ckpt`, `.lora`, `.capcut`
- Added: Composition rules for RAW files (≥3 at ≥40% → Photography - RAW Files), DAW projects (any `.als/.flp/.logicx` → Music Production - DAW Projects), MIDI-only folders, and Lightroom preset heavy folders
- Added: Expanded `FILENAME_ASSET_MAP` from 35 → 45+ entries covering Procreate, game assets, music production, RAW photos, calendars, patterns, and more
- Added: `DESIGN_TEMPLATE_EXTS` now includes `.fig`, `.afdesign`, `.afphoto`, `.afpub`, `.sketch`
- Added: `VIDEO_TEMPLATE_EXTS` now includes `.drp`, `.drfx`
- Changed: Keyword expansions across 10 existing categories: After Effects, 3D/3D Materials, Motion Graphics, Backgrounds & Textures, Fonts & Typography, Sound Effects, Lightroom, DaVinci Resolve, CapCut



- Added: CSV sort rules engine (`unifile/csv_rules.py`) — user-editable regex patterns that classify folders without consuming AI tokens
- Added: `CsvRulesDialog` editor accessible via **Tools → Sort Rules...** — add/remove/test rules inline
- Added: CSV rules hooked into both `ScanSmartWorker` and `ScanLLMWorker` (priority: corrections → CSV rules → cache → AI)
- Added: `source_dir` and `mode` metadata stored in every undo batch for richer history display
- Added: Undo history limit increased from 10 → 50 batches
- Changed: Undo timeline now shows mode (categorize / aep / files) and source folder name per batch
- Changed: Undone batches are now archived with `status: 'undone'` instead of deleted from stack — full history preserved
- Changed: Undo logic moved into `UndoTimelineDialog._perform_undo()` — shows confirmation message, refreshes list inline

## [v8.1.0]

- Added: Route AI scans through ProviderChain (OpenAI, Groq, LM Studio, Ollama) — any enabled non-Ollama provider is now used automatically
- Added: `classify_folder_via_chain()` in `ai_providers.py` with full context-building, system/user prompt split, JSON parsing, and category validation
- Added: System message support (`system` param) on `AIProvider.classify()`, `ProviderChain.classify()`, `_openai_chat()`, and `_ollama_generate()`
- Fixed: `context_lines` initialization order bug in `ollama_classify_folder()` (ID-only hints were being overwritten)
- Changed: `_get_ai_backend()` now returns `'providers'` when any non-Ollama AI provider is enabled
- Changed: `ScanLLMWorker` skips Ollama connection check and batching when using provider chain



- docs: add Related Tools section clarifying relationship to FileOrganizer
- Fixed: Fix runtime bug, thread safety, and silent exception swallowing
- Added: Add 15 intelligence and architecture features
- Fixed: Fix NameError bugs found during code audit
- Added: Add search query language and file preview panel to Tag Library
- Added: Add classifier-compatible config import/export and per-directory overrides
- Added: Add Nexa SDK as alternative AI backend alongside Ollama
- Added: Add Media Lookup panel with TMDb, OMDb, and TVMaze providers
- UniFile v8.0.0 — unified AI-powered file organization platform
