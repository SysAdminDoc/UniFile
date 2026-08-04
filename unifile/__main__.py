"""UniFile — Application entry point.

Usage:
    python -m unifile                              Launch the GUI.
    python -m unifile --source <path>              Auto-scan a folder.
    python -m unifile --profile <name> --auto-apply
    python -m unifile classify <path> [--json]     Headless classify one path.
    python -m unifile list-profiles [--json]       List saved scan profiles.
    python -m unifile list-models [--json]         List installed Ollama models.
    python -m unifile plugin create --name <name>  Generate a plugin scaffold.
    python -m unifile serve [--host HOST]          Run the Qt-free headless API.
    python -m unifile import-tagstudio SOURCE LIBRARY
                                                   Import a TagStudio SQLite library.
    python -m unifile export-tagstudio LIBRARY OUTPUT
                                                   Export a TagStudio SQLite library.
    python -m unifile books scan SOURCE --lookup
                                                   Scan and enrich ebook metadata.
    python -m unifile books export-opf LIBRARY
                                                   Export Calibre metadata.opf files.
    python -m unifile validate-rules <dir> [--json]
                                                   Verify a directory's
                                                   .unifile_rules.json and
                                                   report the effective rule set.
    python -m unifile --version                    Print version + exit.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path


def _branding_icon_path() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "icon.png")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "icon.png")
    current = Path(__file__).resolve()
    candidates.extend([current.parent / "icon.png",
                       current.parent.parent / "icon.png",
                       current.parent.parent.parent / "icon.png"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("icon.png")


def _cmd_list_profiles(args) -> int:
    """List saved profiles. Prints one name per line, or a JSON array."""
    from unifile.plugins import ProfileManager
    names = ProfileManager.list_profiles()
    if getattr(args, 'json', False):
        print(json.dumps(names, indent=2))
        return 0
    if not names:
        print("(no saved profiles)")
        return 0
    for n in names:
        print(n)
    return 0


def _cmd_list_models(args) -> int:
    """List locally-installed Ollama models. Safe when Ollama isn't running."""
    from unifile.ollama import _ollama_list_models, load_ollama_settings
    url = getattr(args, 'url', None) or load_ollama_settings().get('url', '')
    try:
        models = _ollama_list_models(url)
    except Exception as e:
        print(f"error: could not reach Ollama at {url}: {e}", file=sys.stderr)
        return 1
    if getattr(args, 'json', False):
        print(json.dumps(models, indent=2))
        return 0
    if not models:
        print("(no models installed)")
        print(f"Check that Ollama is running at {url} and run `ollama pull qwen3.5:9b`.",
              file=sys.stderr)
        return 0
    for m in models:
        print(m)
    return 0


def _cmd_classify(args) -> int:
    """Headless classification of a single file or folder.

    Writes either a human-readable summary or (with --json) a JSON object to
    stdout. No GUI is imported — safe to use in scripts and cron jobs.
    """
    target = os.path.abspath(args.path)
    if not os.path.exists(target):
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 2
    # Route based on whether it's a file or folder, using rule-based classification
    # (no LLM) so headless runs are fast and deterministic.
    try:
        if os.path.isfile(target):
            from unifile.files import _build_ext_map, _classify_pc_item, _load_pc_categories
            cats = _load_pc_categories()
            ext_map = _build_ext_map(cats)
            category, confidence, method = _classify_pc_item(
                target, ext_map, is_folder=False, categories=cats
            )
            result = {
                "kind": "file",
                "path": target,
                "category": category,
                "confidence": confidence,
                "method": method,
            }
        else:
            from unifile.classifier import tiered_classify
            tr = tiered_classify(os.path.basename(target), target)
            result = {
                "kind": "folder",
                "path": target,
                "category": tr.get("category"),
                "confidence": tr.get("confidence", 0),
                "method": tr.get("method", ""),
                "cleaned_name": tr.get("cleaned_name", ""),
                "detail": tr.get("detail", ""),
            }
    except Exception as e:
        err = {"error": str(e), "type": type(e).__name__, "path": target}
        if args.json:
            print(json.dumps(err, indent=2))
        else:
            print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        cat = result.get("category") or "(unclassified)"
        conf = result.get("confidence", 0)
        method = result.get("method", "")
        print(f"{result['kind']}: {target}")
        print(f"  category:   {cat}")
        print(f"  confidence: {conf}")
        print(f"  method:     {method}")
        if result.get("cleaned_name"):
            print(f"  cleaned:    {result['cleaned_name']}")
    return 0


def _cmd_validate_rules(args) -> int:
    """Validate a directory's `.unifile_rules.json` file.

    Loads the per-folder delta, applies it against the saved global rule
    set, and reports (human-readable or JSON) what the effective rules
    would be. Exit codes:
      0 — valid (file present and parsed)
      2 — file missing
      3 — file present but malformed / not a dict
      4 — delta references unknown global rule names (include/exclude
          that don't match anything in the global rule set)
    """
    target = os.path.abspath(args.path)
    if not os.path.isdir(target):
        print(f"error: not a directory: {target}", file=sys.stderr)
        return 2

    from unifile.engine import RuleEngine, apply_rule_delta
    from unifile.files import DIRRULES_FILENAME, load_directory_rules

    rules_path = os.path.join(target, DIRRULES_FILENAME)
    if not os.path.exists(rules_path):
        if args.json:
            print(json.dumps({"ok": False, "reason": "missing",
                              "expected_path": rules_path}))
        else:
            print(f"No {DIRRULES_FILENAME} in {target}", file=sys.stderr)
        return 2

    delta = load_directory_rules(target)
    if delta is None:
        if args.json:
            print(json.dumps({"ok": False, "reason": "malformed",
                              "expected_path": rules_path}))
        else:
            print(f"Malformed or empty {DIRRULES_FILENAME}", file=sys.stderr)
        return 3

    base = RuleEngine.load_rules()
    base_names = {r.get('name') for r in base}
    unknown_include = [n for n in (delta.get('include') or []) if n not in base_names]
    unknown_exclude = [n for n in (delta.get('exclude') or []) if n not in base_names]

    effective = apply_rule_delta(base, delta)
    report = {
        "ok": not (unknown_include or unknown_exclude),
        "path": rules_path,
        "base_rule_count": len(base),
        "include": delta.get('include', []),
        "exclude": delta.get('exclude', []),
        "inline_count": len(delta.get('inline', [])),
        "effective_rule_count": len(effective),
        "effective_rule_names": [r.get('name', '') for r in effective],
        "unknown_include_names": unknown_include,
        "unknown_exclude_names": unknown_exclude,
    }
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"rules file:  {rules_path}")
        print(f"base rules:  {report['base_rule_count']}")
        if report['include']:
            print(f"include:     {', '.join(report['include'])}")
        if report['exclude']:
            print(f"exclude:     {', '.join(report['exclude'])}")
        print(f"inline:      {report['inline_count']}")
        print(f"effective:   {report['effective_rule_count']} rule(s)")
        if report['effective_rule_names']:
            print("names:")
            for name in report['effective_rule_names']:
                print(f"  - {name}")
        if unknown_include:
            print(f"WARNING: include references unknown global rules: {', '.join(unknown_include)}",
                  file=sys.stderr)
        if unknown_exclude:
            print(f"WARNING: exclude references unknown global rules: {', '.join(unknown_exclude)}",
                  file=sys.stderr)
    return 0 if report['ok'] else 4


def _cmd_plugin_create(args) -> int:
    """Create a manifest-backed plugin package without importing the GUI."""
    from unifile.config import _APP_DATA_DIR
    from unifile.plugin_manifest import ManifestError, create_plugin_scaffold

    output_dir = args.output or os.path.join(_APP_DATA_DIR, 'plugins')
    try:
        result = create_plugin_scaffold(args.name, output_dir, force=args.force)
    except (ManifestError, OSError, ValueError) as exc:
        print(f"error: could not create plugin: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Created plugin scaffold: {result['directory']}")
        print(f"  manifest:   {result['manifest']}")
        print(f"  entrypoint: {result['entrypoint']}")
        print("Review it, then trust it from Settings -> Plugins.")
    return 0


def _cmd_serve(args) -> int:
    """Run the optional Flask API without importing any Qt modules."""
    from unifile.headless import create_app

    app = create_app({"START_SCHEDULER": True})
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


def _print_tagstudio_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return
    print(f"{result.operation} TagStudio library: {result.database}")
    print(f"  tags:        {result.tags}")
    print(f"  entries:     {result.entries}")
    print(f"  fields:      {result.fields}")
    print(f"  thumbnails:  {result.thumbnails}")
    print(f"  merged:      {result.merged}")
    print(f"  skipped:     {result.skipped}")
    for conflict in result.conflicts:
        print(f"  conflict:    {conflict}")
    for warning in result.warnings:
        print(f"  warning:     {warning}")


def _cmd_import_tagstudio(args) -> int:
    """Import a TagStudio database without modifying its source files."""
    from unifile.tagstudio import TagStudioInteropError, import_tagstudio

    try:
        result = import_tagstudio(
            args.source,
            args.library,
            copy_thumbnails=not args.no_thumbnails,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, OSError, TagStudioInteropError) as exc:
        print(f"error: TagStudio import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    _print_tagstudio_result(result, args.json)
    return 0


def _cmd_export_tagstudio(args) -> int:
    """Export UniFile metadata to an additive TagStudio database."""
    from unifile.tagstudio import TagStudioInteropError, export_tagstudio

    try:
        result = export_tagstudio(
            args.library,
            args.output,
            copy_thumbnails=not args.no_thumbnails,
        )
    except (FileNotFoundError, OSError, TagStudioInteropError) as exc:
        print(f"error: TagStudio export failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    _print_tagstudio_result(result, args.json)
    return 0


def _print_books_result(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return
    if hasattr(result, "books"):
        print(f"Book scan: {result.source}")
        print(f"  books:             {len(result.books)}")
        print(f"  looked up:         {result.looked_up}")
        print(f"  applied:           {result.applied}")
        print(f"  covers downloaded: {result.covers_downloaded}")
    else:
        print(f"Calibre OPF export: {result.output}")
        print(f"  exported:      {result.exported}")
        print(f"  skipped:       {result.skipped}")
        print(f"  covers copied: {result.covers_copied}")
    for error in result.errors:
        print(f"  error: {error}")


def _cmd_books_scan(args) -> int:
    """Scan ebooks and optionally enrich an open UniFile library."""
    from unifile.books import BookMetadataClient, scan_book_library

    providers = tuple(args.provider) if args.provider else ("openlibrary", "googlebooks")
    client = None
    if args.lookup and (args.cache or args.min_interval != 1.0):
        client = BookMetadataClient(args.cache or None, min_interval=args.min_interval)
    result = scan_book_library(
        args.source,
        target_library=args.library,
        lookup=args.lookup,
        download_covers=args.download_covers,
        providers=providers,
        client=client,
    )
    _print_books_result(result, args.json)
    return 0 if result.books or not result.errors else 2


def _cmd_books_export_opf(args) -> int:
    """Export book entries as non-destructive Calibre metadata sidecars."""
    from unifile.books import export_calibre_opf

    result = export_calibre_opf(args.library, args.output, overwrite=not args.no_overwrite)
    _print_books_result(result, args.json)
    return 0 if not result.errors else 2


def _write_scan_json(window, output_path: str) -> None:
    """Serialize the current scan results to a JSON plan file.

    Call this after a scan completes. Covers all three op modes by reading
    whichever item list is populated.
    """
    plan: dict = {
        "version": "1",
        "timestamp": datetime.now().isoformat(),
        "source": getattr(window, '_cli_source', '') or window.txt_src.text(),
        "mode": window.cmb_op.currentText() if hasattr(window, 'cmb_op') else '',
        "items": [],
    }
    # Pick the populated list
    items = (getattr(window, 'file_items', None)
             or getattr(window, 'cat_items', None)
             or getattr(window, 'aep_items', None) or [])
    for it in items:
        entry = {
            "name": getattr(it, 'name', '') or getattr(it, 'folder_name', '') or getattr(it, 'current_name', ''),
            "src":  getattr(it, 'full_src', '') or getattr(it, 'full_source_path', '') or getattr(it, 'full_current_path', ''),
            "dst":  getattr(it, 'full_dst', '') or getattr(it, 'full_dest_path', '') or getattr(it, 'full_new_path', ''),
            "category":  getattr(it, 'category', ''),
            "confidence": getattr(it, 'confidence', 0),
            "method":    getattr(it, 'method', ''),
            "size":      getattr(it, 'size', 0) or getattr(it, 'file_size', 0),
            "selected":  getattr(it, 'selected', True),
            "status":    getattr(it, 'status', 'Pending'),
        }
        plan['items'].append(entry)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        window._log(f"Scan plan exported: {output_path}  ({len(plan['items'])} items)")
    except OSError as e:
        window._log(f"Failed to export scan plan: {e}")


def main():
    """Launch the UniFile application or dispatch a CLI subcommand."""
    from unifile import __version__
    from unifile.config import _APP_DATA_DIR

    _CRASH_LOG = os.path.join(_APP_DATA_DIR, 'crash.log')
    _CRASH_LOG_MAX = 512 * 1024  # 500 KB

    def _rotate_crash_log():
        try:
            if os.path.exists(_CRASH_LOG) and os.path.getsize(_CRASH_LOG) > _CRASH_LOG_MAX:
                rotated = _CRASH_LOG + '.1'
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(_CRASH_LOG, rotated)
        except OSError:
            pass

    def _crash_handler(exc_type, exc_value, exc_tb):
        import traceback as _tb
        lines = _tb.format_exception(exc_type, exc_value, exc_tb)
        crash_text = ''.join(lines)
        timestamp = datetime.now().isoformat()
        entry = f"\n{'='*60}\n[{timestamp}] Unhandled {exc_type.__name__}\n{crash_text}"
        try:
            _rotate_crash_log()
            with open(_CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write(entry)
        except OSError:
            pass
        from PyQt6.QtWidgets import QApplication, QMessageBox
        qapp = QApplication.instance()
        if qapp:
            QMessageBox.critical(None, "UniFile — Crash",
                f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}\n\n"
                f"Details saved to:\n{_CRASH_LOG}")
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    import argparse

    parser = argparse.ArgumentParser(
        prog="unifile",
        description="UniFile — Context-Aware File Organizer",
    )
    parser.add_argument("--version", action="version", version=f"UniFile {__version__}")
    parser.add_argument("--install-deps", action="store_true",
                        help="Opt in to pip-install missing dependencies before running.")
    parser.add_argument("--source", type=str, default=None,
                        help="Source folder to auto-scan (used by shell integration)")
    parser.add_argument("--show-preview", action="store_true",
                        help="After an auto-scan, open the review preview")
    parser.add_argument("--profile", type=str, default=None,
                        help="Load a named profile for scheduled/automated scans")
    parser.add_argument("--auto-apply", action="store_true",
                        help="Automatically apply after scan (for scheduled tasks)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate apply without moving/renaming files")
    parser.add_argument("--output-json", type=str, default=None,
                        help="After scan completes, write a machine-readable "
                             "scan plan to this path (JSON).")

    subparsers = parser.add_subparsers(dest="subcommand")

    p_classify = subparsers.add_parser(
        "classify",
        help="Headless classify a file or folder and print the result",
    )
    p_classify.add_argument("path", type=str, help="File or folder to classify")
    p_classify.add_argument("--json", action="store_true",
                            help="Emit JSON instead of human-readable output")

    p_list_profiles = subparsers.add_parser(
        "list-profiles",
        help="List saved scan profiles (one per line, or --json)",
    )
    p_list_profiles.add_argument("--json", action="store_true")

    p_list_models = subparsers.add_parser(
        "list-models",
        help="List installed Ollama models",
    )
    p_list_models.add_argument("--json", action="store_true")
    p_list_models.add_argument("--url", type=str, default=None,
                               help="Ollama server URL (default: saved setting)")

    p_validate_rules = subparsers.add_parser(
        "validate-rules",
        help="Validate a directory's .unifile_rules.json and report the effective rule set",
    )
    p_validate_rules.add_argument("path", type=str, help="Directory containing .unifile_rules.json")
    p_validate_rules.add_argument("--json", action="store_true",
                                  help="Emit a JSON report instead of human-readable output")

    p_plugin = subparsers.add_parser(
        "plugin",
        help="Create or inspect manifest-backed plugins",
    )
    plugin_subparsers = p_plugin.add_subparsers(dest="plugin_command")
    p_plugin_create = plugin_subparsers.add_parser(
        "create",
        help="Generate a YAML manifest and Python entrypoint scaffold",
    )
    p_plugin_create.add_argument("--name", required=True, help="Human-readable plugin name")
    p_plugin_create.add_argument(
        "--output",
        default=None,
        help="Plugin root directory (default: UniFile app-data plugins folder)",
    )
    p_plugin_create.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the generated plugin.yaml and plugin.py in an existing target folder",
    )
    p_plugin_create.add_argument("--json", action="store_true", help="Emit generated paths as JSON")

    p_serve = subparsers.add_parser(
        "serve",
        help="Run the Qt-free Flask headless API",
    )
    p_serve.add_argument(
        "--host",
        default=os.environ.get("UNIFILE_API_HOST", "127.0.0.1"),
        help="Bind address (default: 127.0.0.1)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("UNIFILE_API_PORT", "8787")),
        help="Bind port (default: 8787)",
    )

    p_import_tagstudio = subparsers.add_parser(
        "import-tagstudio",
        help="Import a TagStudio SQLite library into a UniFile library",
    )
    p_import_tagstudio.add_argument("source", help="TagStudio library root or SQLite database")
    p_import_tagstudio.add_argument("library", help="Target UniFile library root")
    p_import_tagstudio.add_argument(
        "--no-thumbnails", action="store_true", help="Do not copy TagStudio's cached thumbnails"
    )
    p_import_tagstudio.add_argument("--dry-run", action="store_true", help="Inspect without writing")
    p_import_tagstudio.add_argument("--json", action="store_true", help="Emit a JSON result")

    p_export_tagstudio = subparsers.add_parser(
        "export-tagstudio",
        help="Export a UniFile library to an additive TagStudio SQLite library",
    )
    p_export_tagstudio.add_argument("library", help="Source UniFile library root")
    p_export_tagstudio.add_argument(
        "output", help="TagStudio library root or output SQLite database path"
    )
    p_export_tagstudio.add_argument(
        "--no-thumbnails", action="store_true", help="Do not copy preserved cached thumbnails"
    )
    p_export_tagstudio.add_argument("--json", action="store_true", help="Emit a JSON result")

    p_books = subparsers.add_parser(
        "books",
        help="Scan ebooks and export Calibre metadata",
    )
    books_subparsers = p_books.add_subparsers(dest="books_command")
    p_books_scan = books_subparsers.add_parser(
        "scan",
        help="Scan EPUB, PDF, MOBI, and AZW3 files for book metadata",
    )
    p_books_scan.add_argument("source", help="Ebook file or directory to scan")
    p_books_scan.add_argument("--library", help="Optional UniFile library to enrich with fields and tags")
    p_books_scan.add_argument("--lookup", action="store_true", help="Query OpenLibrary, then Google Books")
    p_books_scan.add_argument("--download-covers", action="store_true", help="Cache covers returned by lookup")
    p_books_scan.add_argument("--cache", help="JSON cache path for remote responses")
    p_books_scan.add_argument(
        "--provider",
        action="append",
        choices=("openlibrary", "googlebooks"),
        help="Restrict lookup providers; may be repeated",
    )
    p_books_scan.add_argument("--min-interval", type=float, default=1.0, help="Minimum seconds between remote requests")
    p_books_scan.add_argument("--json", action="store_true", help="Emit a JSON result")

    p_books_export = books_subparsers.add_parser(
        "export-opf",
        help="Export book entries as Calibre-compatible metadata.opf files",
    )
    p_books_export.add_argument("library", help="Source UniFile library root")
    p_books_export.add_argument("--output", help="Output directory (default: .unifile/calibre-opf)")
    p_books_export.add_argument("--no-overwrite", action="store_true", help="Keep existing generated OPF files")
    p_books_export.add_argument("--json", action="store_true", help="Emit a JSON result")

    p_shell = subparsers.add_parser(
        "install-shell",
        help="Install Windows Explorer shell integration (context menu + Send To)",
    )
    p_shell.add_argument("--context-menu", action="store_true", default=False,
                         help="Install context menu only (omit to install both)")
    p_shell.add_argument("--sendto", action="store_true", default=False,
                         help="Install Send To shortcut only (omit to install both)")

    subparsers.add_parser(
        "uninstall-shell",
        help="Remove Windows Explorer shell integration",
    )

    p_backup = subparsers.add_parser(
        "backup",
        help="Export tag library, config, and checksums to a ZIP",
    )
    p_backup.add_argument("library", type=str, help="Library root directory")
    p_backup.add_argument("--dest", type=str, default=".",
                          help="Destination directory for the backup ZIP")

    p_restore = subparsers.add_parser(
        "restore",
        help="Restore a tag library from a backup ZIP",
    )
    p_restore.add_argument("zip", type=str, help="Path to backup ZIP")
    p_restore.add_argument("library", type=str, help="Library root directory")

    args, qt_args = parser.parse_known_args()

    if args.install_deps:
        os.environ['UNIFILE_INSTALL_DEPS'] = '1'
        from unifile import bootstrap as _bootstrap  # noqa: F401

    # Headless subcommands — no GUI at all.
    if args.subcommand == "classify":
        sys.exit(_cmd_classify(args))
    if args.subcommand == "list-profiles":
        sys.exit(_cmd_list_profiles(args))
    if args.subcommand == "list-models":
        sys.exit(_cmd_list_models(args))
    if args.subcommand == "validate-rules":
        sys.exit(_cmd_validate_rules(args))
    if args.subcommand == "plugin":
        if args.plugin_command == "create":
            sys.exit(_cmd_plugin_create(args))
        print("error: choose a plugin command (currently: create)", file=sys.stderr)
        sys.exit(2)
    if args.subcommand == "serve":
        sys.exit(_cmd_serve(args))
    if args.subcommand == "import-tagstudio":
        sys.exit(_cmd_import_tagstudio(args))
    if args.subcommand == "export-tagstudio":
        sys.exit(_cmd_export_tagstudio(args))
    if args.subcommand == "books":
        if args.books_command == "scan":
            sys.exit(_cmd_books_scan(args))
        if args.books_command == "export-opf":
            sys.exit(_cmd_books_export_opf(args))
        print("error: choose a books command (currently: scan or export-opf)", file=sys.stderr)
        sys.exit(2)

    if args.subcommand == "install-shell":
        from unifile import shell_integration as si
        both = not args.context_menu and not args.sendto
        results = {}
        if both or args.context_menu:
            results["context_menu"] = si.install_context_menu()
        if both or args.sendto:
            results["sendto"] = si.install_sendto()
        for k, ok in results.items():
            print(f"{'OK' if ok else 'FAILED'}: {k}")
        sys.exit(0 if all(results.values()) else 1)

    if args.subcommand == "uninstall-shell":
        from unifile import shell_integration as si
        results = si.uninstall()
        for k, ok in results.items():
            print(f"{'Removed' if ok else 'Not found'}: {k}")
        sys.exit(0)

    if args.subcommand == "backup":
        from pathlib import Path as _Path

        from unifile.config import _APP_DATA_DIR
        from unifile.tagging.db import export_library_backup, make_engine

        db_path = _Path(args.library) / '.unifile' / 'unifile_tags.sqlite'
        if not db_path.is_file():
            print(f"ERROR: No tag library at {db_path}", file=sys.stderr)
            sys.exit(1)
        engine = make_engine(str(db_path))
        zip_path = export_library_backup(engine, _Path(args.dest),
                                         config_dir=_Path(_APP_DATA_DIR))
        engine.dispose()
        print(f"Backup saved: {zip_path}")
        sys.exit(0)

    if args.subcommand == "restore":
        from pathlib import Path as _Path

        from unifile.config import _APP_DATA_DIR
        from unifile.tagging.db import make_engine, restore_library_backup, verify_library_backup

        ok, msg = verify_library_backup(_Path(args.zip))
        if not ok:
            print(f"ERROR: {msg}", file=sys.stderr)
            sys.exit(1)
        db_path = _Path(args.library) / '.unifile' / 'unifile_tags.sqlite'
        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = make_engine(str(db_path))
        restore_library_backup(engine, _Path(args.zip),
                               config_dir=_Path(_APP_DATA_DIR))
        print(f"Library restored from {args.zip}")
        sys.exit(0)

    # GUI path — install crash handler before touching Qt.
    sys.excepthook = _crash_handler

    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from unifile.config import get_active_stylesheet
    from unifile.main_window import UniFile
    from unifile.plugins import ProfileManager

    app = QApplication(qt_args)

    branding_icon = QIcon(str(_branding_icon_path()))

    app.setWindowIcon(branding_icon)
    app.setStyle("Fusion")

    from unifile.i18n import install_translator
    install_translator(app)

    app.setStyleSheet(get_active_stylesheet())
    window = UniFile()
    window._cli_dry_run = args.dry_run
    window._cli_source = args.source or ''
    window._cli_show_preview = args.show_preview

    if args.profile:
        try:
            profile = ProfileManager.load(args.profile)
            if profile:
                apply_cfg = getattr(window, '_apply_profile_config', None)
                if apply_cfg is None:
                    apply_cfg = getattr(window, '_apply_profile', None)
                if apply_cfg is not None:
                    apply_cfg(profile)
                    window._log(f"Loaded profile: {args.profile}")
                else:
                    window._log(f"Profile loader unavailable — ignoring '{args.profile}'")
        except FileNotFoundError:
            window._log(f"Profile not found: {args.profile}")
        except Exception as e:
            window._log(f"Failed to load profile '{args.profile}': {e}")
    window.show()

    if args.source and os.path.isdir(args.source):
        window.cmb_op.setCurrentIndex(UniFile.OP_FILES)
        window.cmb_pc_src.setCurrentText(args.source)
        if hasattr(window, 'txt_pc_src'):
            window.txt_pc_src.setText(args.source)
        QTimer.singleShot(200, window._on_scan)

        if args.output_json or args.show_preview:
            _deadline_out = [time.time() + 30 * 60]
            def _wait_and_dump():
                if time.time() > _deadline_out[0]:
                    window._log("Auto-scan follow-up aborted: 30 minute deadline exceeded")
                    return
                scan_worker = getattr(window, 'worker', None)
                still_scanning = (
                    getattr(window, '_scanning', False)
                    or (scan_worker is not None and scan_worker.isRunning())
                )
                if not still_scanning:
                    if args.output_json:
                        _write_scan_json(window, args.output_json)
                    if args.show_preview:
                        try:
                            if window.cmb_op.currentIndex() == UniFile.OP_FILES and getattr(window, 'file_items', None):
                                window._show_before_after()
                            elif window.btn_preview.isEnabled():
                                window._show_preview()
                            else:
                                window._log("Preview skipped: scan produced no reviewable items")
                        except Exception as e:
                            window._log(f"Preview failed: {e}")
                else:
                    QTimer.singleShot(500, _wait_and_dump)
            QTimer.singleShot(1000, _wait_and_dump)

    elif args.profile and args.auto_apply:
        def _auto_scan_apply():
            window._on_scan()
            _deadline = [time.time() + 30 * 60]  # 30-minute safety ceiling
            def _check_and_apply():
                if time.time() > _deadline[0]:
                    window._log("Auto-apply aborted: scan exceeded 30 minute deadline")
                    return
                scan_worker = getattr(window, 'worker', None)
                still_scanning = (
                    getattr(window, '_scanning', False)
                    or (scan_worker is not None and scan_worker.isRunning())
                )
                if not still_scanning:
                    if args.output_json:
                        _write_scan_json(window, args.output_json)
                    op_idx = window.cmb_op.currentIndex()
                    if op_idx == UniFile.OP_FILES:
                        window._apply_files(dry_run=args.dry_run)
                    elif op_idx in (UniFile.OP_CAT, UniFile.OP_SMART):
                        window._apply_cat()
                    else:
                        window._apply_aep(dry_run=args.dry_run)
                else:
                    QTimer.singleShot(500, _check_and_apply)
            QTimer.singleShot(1000, _check_and_apply)
        QTimer.singleShot(200, _auto_scan_apply)

    smoke_exit_ms = os.environ.get("UNIFILE_GUI_SMOKE_EXIT_MS")
    if smoke_exit_ms:
        try:
            QTimer.singleShot(max(0, int(smoke_exit_ms)), app.quit)
        except ValueError:
            QTimer.singleShot(1200, app.quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
