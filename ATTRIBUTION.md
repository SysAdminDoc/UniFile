# Attribution

UniFile adapts ideas and — in some cases — code from the following upstream
open-source projects. All are MIT-licensed or under a compatible permissive
license; each is re-used in the spirit of its original license.

| Project | License | Stars | What UniFile uses |
|---------|---------|-------|-------------------|
| [TagStudio](https://github.com/TagStudioDev/TagStudio) | GPL-3.0 | 42k | Inspiration for tag library data model (hierarchical tags, aliases, entry fields, color coding). UniFile's implementation in `unifile/tagging/` is a clean-room re-implementation. |
| [FileOrganizer](https://github.com/SysAdminDoc/FileOrganizer) | MIT | — | Same author. Upstream foundation: 7-level classification pipeline, Ollama integration, PyQt6 GUI scaffolding, 384+ categories. |
| [Local-File-Organizer](https://github.com/QiuYannworworworworworworworwor/Local-File-Organizer) | MIT | 3.1k | Inspiration for the Nexa SDK vision backend (`unifile/nexa_backend.py`). |
| [classifier](https://github.com/bhrigu123/classifier) | MIT | 1.1k | `.classifier.conf` extension-to-category file format compatibility in `unifile/files.py:import_classifier_config()`. |
| [mnamer](https://github.com/jkwill87/mnamer) | MIT | 1k | Media provider abstraction + `guessit` filename parsing in `unifile/media/providers.py`. |

## Notes

- **TagStudio is GPL-3.0**, which would normally prevent redistribution under
  MIT. UniFile does *not* include verbatim TagStudio source code — the tag
  library schema and CRUD layer in `unifile/tagging/` were written from scratch
  against the public TagStudio data model documentation. If you plan to
  redistribute UniFile's tagging code separately, double-check that your own
  usage stays on the right side of this boundary.
- The TMDb API key embedded in `unifile/media/providers.py` is a shared
  demo key inherited from mnamer. For heavy use, set the `API_KEY_TMDB`
  environment variable to your own key.
- If you believe attribution is missing or incorrect, please open an issue.

## Third-party runtime dependencies

Core + optional dependencies are listed in `requirements.txt` and
`pyproject.toml`. Notable runtime dependencies with their licenses:

| Package | License |
|---------|---------|
| PyQt6   | GPL-3.0 / commercial |
| SQLAlchemy | MIT |
| Pillow  | MIT-CMU |
| rapidfuzz | MIT |
| send2trash | BSD-3 |
| mutagen | GPL-2.0 |
| pypdf   | BSD-3 |
| guessit | LGPL-3 |

Note: **PyQt6 is GPL-licensed.** Distributing UniFile as a bundled application
(PyInstaller exe) inherits that obligation — if you redistribute binaries,
make source available to end users. UniFile's own source is MIT so this is
satisfied by keeping the GitHub repository public.
