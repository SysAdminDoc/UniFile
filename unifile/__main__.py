"""UniFile — Application entry point.

Usage:
    python -m unifile                              Launch the GUI.
    python -m unifile --source <path>              Auto-scan a folder.
    python -m unifile --profile <name> --auto-apply
    python -m unifile classify <path> [--json]     Headless classify one path.
    python -m unifile list-profiles [--json]       List saved scan profiles.
    python -m unifile list-models [--json]         List installed Ollama models.
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


# codex-branding:start
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
# codex-branding:end


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
    parser.add_argument("--source", type=str, default=None,
                        help="Source folder to auto-scan (used by shell integration)")
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

    args, qt_args = parser.parse_known_args()

    # Headless subcommands — no GUI at all.
    if args.subcommand == "classify":
        sys.exit(_cmd_classify(args))
    if args.subcommand == "list-profiles":
        sys.exit(_cmd_list_profiles(args))
    if args.subcommand == "list-models":
        sys.exit(_cmd_list_models(args))
    if args.subcommand == "validate-rules":
        sys.exit(_cmd_validate_rules(args))

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
    app.setStyleSheet(get_active_stylesheet())
    window = UniFile()
    window._cli_dry_run = args.dry_run
    window._cli_source = args.source or ''

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

        if args.output_json:
            _deadline_out = [time.time() + 30 * 60]
            def _wait_and_dump():
                if time.time() > _deadline_out[0]:
                    window._log("Scan-plan export aborted: 30 minute deadline exceeded")
                    return
                scan_worker = getattr(window, 'worker', None)
                still_scanning = (
                    getattr(window, '_scanning', False)
                    or (scan_worker is not None and scan_worker.isRunning())
                )
                if not still_scanning:
                    _write_scan_json(window, args.output_json)
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
