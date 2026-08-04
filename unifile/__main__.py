"""UniFile — Application entry point.

Usage:
    python -m unifile                              Launch the GUI.
    python -m unifile --source <path>              Auto-scan a folder.
    python -m unifile --profile <name> --auto-apply
    python -m unifile classify <path> [--json]     Headless classify one path.
    python -m unifile scan <path> [--apply-rules]  Headless scan and apply.
    python -m unifile watch <path>                 Watch and classify arrivals.
    python -m unifile tag --query <query>          Query the tag library.
    python -m unifile report --format html        Export a library report.
    python -m unifile list-profiles [--json]       List saved scan profiles.
    python -m unifile list-models [--json]         List installed Ollama models.
    python -m unifile plugin create --name <name>  Generate a plugin scaffold.
    python -m unifile serve [--host HOST]          Run the Qt-free headless API.
    python -m unifile collab init --library DIR    Initialize LAN collaboration.
    python -m unifile collab search URL --user ID --token TOKEN
                                                   Search a shared library.
    python -m unifile verify <path> [--json]       Verify stored SHA-256 checksums.
    python -m unifile import-tagstudio SOURCE LIBRARY
                                                   Import a TagStudio SQLite library.
    python -m unifile export-tagstudio LIBRARY OUTPUT
                                                   Export a TagStudio SQLite library.
    python -m unifile books scan SOURCE --lookup
                                                   Scan and enrich ebook metadata.
    python -m unifile books export-opf LIBRARY
                                                   Export Calibre metadata.opf files.
    python -m unifile nfo generate MEDIA [--metadata-json FILE]
                                                   Write a Kodi/Plex NFO sidecar.
    python -m unifile projects audit SOURCE [--apply]
                                                   Audit project media references.
    python -m unifile mobile --library LIBRARY
                                                   Start the read-only LAN companion.
    python -m unifile validate-rules <dir> [--json]
                                                   Verify a directory's
                                                   .unifile_rules.json and
                                                   report the effective rule set.
    python -m unifile --version                    Print version + exit.
"""
import json
import os
import re
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


def _cmd_scan(args) -> int:
    """Build or apply a Qt-free PC file organization plan."""
    from unifile.cli_scan import scan_directory

    try:
        result = scan_directory(
            args.path,
            destination=getattr(args, "destination", None),
            limit=getattr(args, "limit", 10_000),
            apply_rules=bool(getattr(args, "apply_rules", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            min_confidence=getattr(args, "min_confidence", 80),
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: scan failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    output_path = getattr(args, "output_json", None)
    if output_path:
        from unifile.config import save_json_safe

        if not save_json_safe(output_path, result):
            print(f"error: could not write scan plan: {output_path}", file=sys.stderr)
            return 2

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Scan: {result['source']}")
        print(f"  files:       {result['count']}")
        print(f"  candidates:  {result['selected_count']}")
        if result["apply_rules"]:
            action = "would move" if result["dry_run"] else "moved"
            print(f"  {action}:      {result['would_move'] if result['dry_run'] else result['moved']}")
        if result["failed"]:
            print(f"  failed:      {result['failed']}")
        if output_path:
            print(f"  plan:        {output_path}")
        for item in result["errors"]:
            print(f"  error:       {item['src']}: {item['error']}", file=sys.stderr)
    return 1 if result["failed"] or result["errors"] else 0


def _cmd_watch(args) -> int:
    """Run a Qt-free settled-file watch daemon."""
    from unifile.cli_watch import WatchDaemon

    try:
        daemon = WatchDaemon(
            args.path,
            destination=args.destination,
            apply_rules=args.apply_rules,
            settle_seconds=args.settle_seconds,
            poll_seconds=args.poll_seconds,
            min_confidence=args.min_confidence,
            include_existing=args.include_existing,
        )
        try:
            events = daemon.run_once() if args.once else daemon.run()
        except KeyboardInterrupt:
            daemon.request_stop()
            events = daemon.flush_pending()
        result = daemon.result(events)
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: watch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.output_json:
        from unifile.config import save_json_safe

        if not save_json_safe(args.output_json, result):
            print(f"error: could not write watch report: {args.output_json}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Watch: {result['source']}")
        print(f"  events:       {result['detected']}")
        print(f"  moved:        {result['moved']}")
        print(f"  errors:       {result['errors']}")
        print(f"  deferred:     {result['deferred']}")
        if args.output_json:
            print(f"  report:       {args.output_json}")
        for event in result["events"]:
            item = event.get("item", {})
            target = f" -> {item['dst']}" if item.get("dst") else ""
            print(f"  {event.get('status', 'unknown')}: {event.get('path', '')}{target}")
    return 1 if result["errors"] else 0


_TAG_QUERY_SELECTORS = (
    "tag:", "-tag:", "ext:", "field:", "special:", "rating:",
    "inbox:", "ns:", "group:", "color:",
)


def _normalize_tag_query(query: str) -> str:
    """Interpret bare CLI terms as tags while preserving query selectors."""
    raw = str(query or "").strip()
    if not raw:
        raise ValueError("a query is required")
    if len(raw) > 500:
        raise ValueError("search query is too long")
    parts = re.split(r"\s+(AND|OR)\s+", raw, flags=re.IGNORECASE)
    terms = []
    for index in range(0, len(parts), 2):
        term = parts[index].strip()
        if not term:
            raise ValueError("query contains an empty term")
        lowered = term.casefold()
        selector = next(
            (candidate for candidate in _TAG_QUERY_SELECTORS if lowered.startswith(candidate)),
            None,
        )
        if selector:
            normalized = selector + term[len(selector):]
        elif term.startswith("-"):
            normalized = "-tag:" + term[1:].strip()
        else:
            normalized = "tag:" + term
        if normalized in {"tag:", "-tag:"}:
            raise ValueError("query contains an empty tag")
        terms.append(normalized)
        if index + 1 < len(parts):
            terms.append(parts[index + 1].upper())
    return " ".join(terms)


def _cmd_tag(args) -> int:
    """Search a local Tag Library without importing Qt."""
    from unifile.headless import HeadlessService

    raw_query = str(args.query or "").strip()
    try:
        normalized_query = _normalize_tag_query(raw_query)
        service = HeadlessService(args.library)
        entries = service.search(normalized_query, limit=args.limit)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"error: tag search failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    result = {
        "version": "1",
        "library": str(Path(args.library).expanduser().resolve()),
        "query": raw_query,
        "normalized_query": normalized_query,
        "count": len(entries),
        "entries": entries,
    }
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Tag search: {raw_query}")
        print(f"Results: {len(entries)}")
        for entry in entries:
            tags = ", ".join(entry.get("tags", [])) or "(untagged)"
            print(f"{entry.get('id')}\t{entry.get('path', entry.get('name', ''))}\t{tags}")
    return 0


def _cmd_report(args) -> int:
    """Export a Tag Library category distribution and file list."""
    from unifile.reports import build_library_report, write_report

    try:
        report = build_library_report(args.library, limit=args.limit)
        output_path = write_report(report, args.output, args.format)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"error: report export failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"Report written: {output_path}")
    print(f"  entries:     {report['entry_count']}")
    print(f"  listed:      {report['reported_entries']}")
    print(f"  categories:  {len(report['category_distribution'])}")
    if report["truncated"]:
        print("  note:        report entry limit truncated the file list")
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

    config = {
        "START_SCHEDULER": True,
        "LIBRARY_ROOT": args.library,
        "COLLABORATIVE_MODE": bool(args.collaborative),
    }
    if args.collaborative:
        from unifile.collaboration import CollaborationStore

        if not CollaborationStore(args.library).has_users:
            print(
                "error: collaborative mode has no users; run `unifile collab init --library DIR` first",
                file=sys.stderr,
            )
            return 2
    app = create_app(config)
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


def _cmd_collab_init(args) -> int:
    """Create the first administrator and print its one-time token."""
    from unifile.collaboration import CollaborationError, CollaborationStore

    store = CollaborationStore(args.library)
    if store.has_users:
        print("error: collaboration is already initialized", file=sys.stderr)
        return 2
    try:
        user = store.create_user(args.user_id, args.display_name, "admin", token=args.token)
    except (CollaborationError, OSError, ValueError) as exc:
        print(f"error: could not initialize collaboration: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(user, indent=2, ensure_ascii=False))
    else:
        print(f"Collaboration initialized for {args.library}")
        print(f"  user:  {user['user_id']} ({user['display_name']})")
        print(f"  role:  {user['role']}")
        print(f"  token: {user['token']}")
        print("Store this token securely; it is not written to the library.")
    return 0


def _cmd_collab_add_user(args) -> int:
    """Add a collaboration user locally, without exposing a server endpoint."""
    from unifile.collaboration import CollaborationError, CollaborationStore

    store = CollaborationStore(args.library)
    if not store.has_users:
        print("error: initialize collaboration first", file=sys.stderr)
        return 2
    try:
        user = store.create_user(
            args.user_id, args.display_name, args.role, token=args.token
        )
    except (CollaborationError, OSError, ValueError) as exc:
        print(f"error: could not add collaboration user: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(user, indent=2, ensure_ascii=False))
    else:
        print(f"Added {user['role']} user {user['user_id']} ({user['display_name']})")
        print(f"  token: {user['token']}")
        print("Store this token securely; it is not written to the library.")
    return 0


def _cmd_collab_list_users(args) -> int:
    from unifile.collaboration import CollaborationStore

    users = CollaborationStore(args.library).list_users()
    if args.json:
        print(json.dumps(users, indent=2, ensure_ascii=False))
    elif not users:
        print("(no collaboration users)")
    else:
        for user in users:
            print(f"{user['user_id']}\t{user['role']}\t{user['display_name']}")
    return 0


def _cmd_collab_search(args) -> int:
    from unifile.collaboration import CollaborationClient, CollaborationError

    try:
        result = CollaborationClient(args.url, args.user, args.token).search(
            args.query, limit=args.limit
        )
    except CollaborationError as exc:
        print(f"error: collaboration search failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Search results: {len(result.get('entries', []))}")
        for entry in result.get("entries", []):
            tags = ", ".join(entry.get("tags", [])) or "(untagged)"
            print(f"{entry.get('id')}\t{entry.get('path', entry.get('name', ''))}\t{tags}")
    return 0


def _cmd_collab_tag(args) -> int:
    from unifile.collaboration import CollaborationClient, CollaborationError

    try:
        result = CollaborationClient(args.url, args.user, args.token).apply_tag(
            entry_id=args.entry_id,
            path=args.path,
            tag=args.tag,
            action=args.action,
            field_timestamp=args.field_timestamp,
        )
    except CollaborationError as exc:
        print(f"error: collaboration tag operation failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        entry = result.get("entry", {})
        print(f"{result.get('action', args.action)} tag {result.get('tag', args.tag)}")
        print(f"  entry: {entry.get('id', args.entry_id)} ({entry.get('path', entry.get('name', ''))})")
        print(f"  field version: {result.get('field_version', {}).get('timestamp', '')}")
    return 0


def _cmd_verify(args) -> int:
    """Verify or establish a persistent SHA-256 ledger for a file tree."""
    from unifile.file_health import FileHealthError, FileHealthMonitor, export_health_log

    target = Path(args.path).expanduser().resolve()
    if not target.exists() or not (target.is_file() or target.is_dir()):
        print(f"error: path does not exist or is not a file/directory: {target}", file=sys.stderr)
        return 2
    try:
        monitor = FileHealthMonitor(target)
        for expected in args.expect:
            candidate = Path(expected)
            if not candidate.is_absolute():
                candidate = monitor.library_root / candidate
            monitor.expect_change(candidate, args.reason)
        report = monitor.verify(str(target))
        if args.output:
            report["log_path"] = export_health_log(report, args.output, fmt=args.format)
    except (FileHealthError, OSError, ValueError) as exc:
        print(f"error: file health verification failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"File health: {report.get('status', 'unknown')} — {report.get('scope', target)}")
        print(f"  verified:              {report.get('files_verified', 0)}")
        print(f"  unchanged:             {report.get('unchanged', 0)}")
        print(f"  baselined:             {report.get('baselined', 0)}")
        print(f"  changed unexpectedly:  {report.get('changed_unexpectedly', 0)}")
        print(f"  expected changes:      {report.get('expected_changes', 0)}")
        print(f"  missing:               {report.get('missing', 0)}")
        print(f"  errors:                {report.get('errors', 0)}")
        for item in report.get("diff", []):
            print(f"  {item.get('change', 'change')}: {item.get('path', '')}")
        if report.get("log_path"):
            print(f"  log:                   {report['log_path']}")
    return 1 if report.get("changed_unexpectedly") or report.get("missing") or report.get("errors") else 0


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


def _cmd_nfo_generate(args) -> int:
    """Generate a Kodi/Plex-compatible NFO sidecar without launching Qt."""
    from unifile.media.nfo import NfoError, metadata_from_json, write_nfo_sidecar
    from unifile.media.providers import MediaType, parse_media_filename

    source = Path(args.path).expanduser().resolve()
    if not source.is_file():
        print(f"error: media file does not exist: {source}", file=sys.stderr)
        return 2

    try:
        if args.metadata_json:
            metadata = metadata_from_json(args.metadata_json)
        else:
            parsed = parse_media_filename(source.name)
            parsed_type = parsed.get("type", MediaType.MOVIE)
            media_type = parsed_type.value if isinstance(parsed_type, MediaType) else str(parsed_type)
            metadata = {
                "title": parsed.get("episode_title") or parsed.get("title") or source.stem,
                "year": parsed.get("year", ""),
                "season": parsed.get("season", ""),
                "episode": parsed.get("episode", ""),
                "media_type": media_type,
            }
            if parsed_type is MediaType.EPISODE:
                metadata["series"] = parsed.get("title", "") or source.stem
        kind = None if args.kind == "auto" else args.kind
        result = write_nfo_sidecar(
            source,
            metadata,
            kind=kind,
            output_path=args.output,
            overwrite=not args.no_overwrite,
        )
    except (NfoError, OSError, ValueError) as exc:
        print(f"error: NFO generation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    elif result.skipped:
        print(f"NFO sidecar skipped: {result.path}")
    else:
        verb = "updated" if result.overwritten else "written"
        print(f"NFO sidecar {verb}: {result.path}")
    return 0


def _cmd_projects_audit(args) -> int:
    """Audit project-file media references without changing source projects."""
    from unifile.project_awareness import apply_project_tags, build_project_audit

    if args.apply and not args.library:
        print("error: --apply requires --library", file=sys.stderr)
        return 2
    try:
        audit = build_project_audit(args.source)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: project audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    payload = audit.to_dict()
    if args.apply:
        applied = apply_project_tags(audit, args.library)
        payload["apply"] = applied.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        counts = payload["counts"]
        print(f"Project audit: {audit.source}")
        print(f"  projects:             {counts['projects']}")
        print(f"  references:           {counts['references']}")
        print(f"  resolved references:  {counts['resolved_references']}")
        print(f"  shared assets:        {counts['shared_assets']}")
        print(f"  orphaned assets:      {counts['orphaned_assets']}")
        print(f"  missing references:   {counts['missing_references']}")
        if args.apply:
            print(f"  tagged assets:        {payload['apply']['applied']}")
            print(f"  skipped assets:       {payload['apply']['skipped']}")
        for error in audit.errors + payload.get("apply", {}).get("errors", []):
            print(f"  error: {error}")
    return 0 if not audit.errors and not payload.get("apply", {}).get("errors") else 2


def _cmd_mobile(args) -> int:
    """Start the token-protected, read-only PWA companion server."""
    from unifile.mobile import run_mobile_server

    return run_mobile_server(args.library, host=args.host, port=args.port, token=args.token)


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
            "confidence_tier": getattr(it, 'confidence_tier', 'skip'),
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

    p_scan = subparsers.add_parser(
        "scan",
        help="Headless scan a directory and optionally apply category rules",
    )
    p_scan.add_argument("path", type=str, help="Directory to scan")
    p_scan.add_argument(
        "--apply-rules", action="store_true",
        help="Move high-confidence classified files to their category destinations",
    )
    p_scan.add_argument(
        "--dry-run", action="store_true",
        help="Show the moves that --apply-rules would perform without changing files",
    )
    p_scan.add_argument(
        "--destination", type=str, default=None,
        help="Optional destination root; category folders are created beneath it",
    )
    p_scan.add_argument(
        "--min-confidence", type=int, default=80,
        help="Minimum confidence for an apply candidate (default: 80)",
    )
    p_scan.add_argument(
        "--limit", type=int, default=10_000,
        help="Maximum files to include (default: 10000)",
    )
    p_scan.add_argument("--json", action="store_true", help="Emit the scan plan as JSON")
    p_scan.add_argument("--output-json", help="Write the scan plan to a JSON file")

    p_watch = subparsers.add_parser(
        "watch",
        help="Watch a directory and classify settled file arrivals",
    )
    p_watch.add_argument("path", type=str, help="Directory to watch recursively")
    p_watch.add_argument(
        "--apply-rules", action="store_true",
        help="Move settled high-confidence files to category destinations",
    )
    p_watch.add_argument(
        "--destination", type=str, default=None,
        help="Optional destination root; category folders are created beneath it",
    )
    p_watch.add_argument(
        "--min-confidence", type=int, default=80,
        help="Minimum confidence for a move candidate (default: 80)",
    )
    p_watch.add_argument(
        "--settle-seconds", "--settle", dest="settle_seconds", type=float, default=0.5,
        help="Required size/mtime stability before processing (default: 0.5)",
    )
    p_watch.add_argument(
        "--poll-seconds", "--poll", dest="poll_seconds", type=float, default=0.25,
        help="Polling interval (default: 0.25)",
    )
    p_watch.add_argument(
        "--include-existing", action="store_true",
        help="Process files already present when the watcher starts",
    )
    p_watch.add_argument(
        "--once", action="store_true",
        help="Run one discovery/settle cycle and exit",
    )
    p_watch.add_argument("--json", action="store_true", help="Emit a JSON summary")
    p_watch.add_argument("--output-json", help="Write the final watch summary to a JSON file")

    p_tag = subparsers.add_parser(
        "tag",
        help="Query a local Tag Library from the shell",
    )
    p_tag.add_argument(
        "--library",
        default=os.environ.get(
            "UNIFILE_LIBRARY_DIR", os.path.join(os.path.expanduser("~"), "UniFileLibrary")
        ),
        help="Tag Library root (default: UNIFILE_LIBRARY_DIR or ~/UniFileLibrary)",
    )
    p_tag.add_argument("--query", required=True, help="Tag query, e.g. 'cat AND outdoor'")
    p_tag.add_argument("--limit", type=int, default=100, help="Maximum results (default: 100)")
    p_tag.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    p_report = subparsers.add_parser(
        "report",
        help="Export a category distribution and file list",
    )
    p_report.add_argument(
        "--library",
        default=os.environ.get(
            "UNIFILE_LIBRARY_DIR", os.path.join(os.path.expanduser("~"), "UniFileLibrary")
        ),
        help="Tag Library root (default: UNIFILE_LIBRARY_DIR or ~/UniFileLibrary)",
    )
    p_report.add_argument(
        "--format", choices=("html", "pdf", "json"), default="html",
        help="Report format (default: html)",
    )
    p_report.add_argument("--output", required=True, help="Output report path")
    p_report.add_argument(
        "--limit", type=int, default=10_000,
        help="Maximum file rows to include (default: 10000)",
    )

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
    p_serve.add_argument(
        "--library",
        default=os.environ.get(
            "UNIFILE_LIBRARY_DIR", os.path.join(os.path.expanduser("~"), "UniFileLibrary")
        ),
        help="Library root (default: UNIFILE_LIBRARY_DIR or ~/UniFileLibrary)",
    )
    p_serve.add_argument(
        "--collaborative",
        action="store_true",
        help="Require library-scoped collaboration users and role permissions",
    )

    p_verify = subparsers.add_parser(
        "verify",
        help="Verify stored SHA-256 checksums for a file or directory",
    )
    p_verify.add_argument("path", help="File or directory to verify")
    p_verify.add_argument("--json", action="store_true", help="Emit a JSON report")
    p_verify.add_argument("--output", help="Export the verification diff to a JSON, CSV, or text log")
    p_verify.add_argument(
        "--format", choices=("json", "csv", "txt", "text"), default="",
        help="Override the output log format (otherwise inferred from --output)",
    )
    p_verify.add_argument(
        "--expect", action="append", default=[],
        help="Relative path whose next digest change is intentional; may be repeated",
    )
    p_verify.add_argument("--reason", default="", help="Reason recorded with expected changes")

    p_collab = subparsers.add_parser(
        "collab",
        help="Initialize and use the collaborative LAN tag API",
    )
    collab_subparsers = p_collab.add_subparsers(dest="collab_command")
    p_collab_init = collab_subparsers.add_parser(
        "init", help="Create the first administrator and token"
    )
    p_collab_init.add_argument("--library", required=True, help="Shared library root")
    p_collab_init.add_argument("--user-id", default="admin", help="Administrator user id")
    p_collab_init.add_argument("--display-name", default=None, help="Administrator display name")
    p_collab_init.add_argument("--token", default=None, help="Optional token (16+ characters)")
    p_collab_init.add_argument("--json", action="store_true", help="Emit JSON")

    p_collab_add = collab_subparsers.add_parser("add-user", help="Add a local collaboration user")
    p_collab_add.add_argument("--library", required=True, help="Shared library root")
    p_collab_add.add_argument("--user-id", required=True, help="User id")
    p_collab_add.add_argument("--display-name", default=None, help="Display name")
    p_collab_add.add_argument("--role", choices=("viewer", "editor", "admin"), default="viewer")
    p_collab_add.add_argument("--token", default=None, help="Optional token (16+ characters)")
    p_collab_add.add_argument("--json", action="store_true", help="Emit JSON")

    p_collab_users = collab_subparsers.add_parser("list-users", help="List users without tokens")
    p_collab_users.add_argument("--library", required=True, help="Shared library root")
    p_collab_users.add_argument("--json", action="store_true", help="Emit JSON")

    p_collab_search = collab_subparsers.add_parser("search", help="Search a shared library")
    p_collab_search.add_argument("url", help="Collaborative server URL")
    p_collab_search.add_argument("--user", required=True, help="Collaboration user id")
    p_collab_search.add_argument(
        "--token", default=os.environ.get("UNIFILE_COLLAB_TOKEN", ""), help="User token"
    )
    p_collab_search.add_argument("--query", default="", help="Search query")
    p_collab_search.add_argument("--limit", type=int, default=100, help="Maximum results")
    p_collab_search.add_argument("--json", action="store_true", help="Emit JSON")

    p_collab_tag = collab_subparsers.add_parser("tag", help="Apply or remove a shared tag")
    p_collab_tag.add_argument("url", help="Collaborative server URL")
    p_collab_tag.add_argument("--user", required=True, help="Collaboration user id")
    p_collab_tag.add_argument(
        "--token", default=os.environ.get("UNIFILE_COLLAB_TOKEN", ""), help="User token"
    )
    entry_selector = p_collab_tag.add_mutually_exclusive_group(required=True)
    entry_selector.add_argument("--entry-id", type=int, help="Server-side entry id")
    entry_selector.add_argument("--path", help="Path on the server, relative to its library root")
    p_collab_tag.add_argument("--tag", required=True, help="Tag name")
    p_collab_tag.add_argument("--action", choices=("add", "remove"), default="add")
    p_collab_tag.add_argument("--field-timestamp", default=None, help="Client field timestamp for conflict checks")
    p_collab_tag.add_argument("--json", action="store_true", help="Emit JSON")

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

    p_nfo = subparsers.add_parser(
        "nfo",
        help="Generate Kodi/Plex-compatible NFO sidecars",
    )
    nfo_subparsers = p_nfo.add_subparsers(dest="nfo_command")
    p_nfo_generate = nfo_subparsers.add_parser(
        "generate",
        help="Write an NFO sidecar beside a media file",
    )
    p_nfo_generate.add_argument("path", help="Media file to describe")
    p_nfo_generate.add_argument(
        "--metadata-json",
        help="JSON object containing normalized metadata or Tag Library fields",
    )
    p_nfo_generate.add_argument(
        "--kind",
        choices=("auto", "movie", "tvshow", "episode", "musicvideo", "book"),
        default="auto",
        help="NFO root kind (default: infer it from metadata or filename)",
    )
    p_nfo_generate.add_argument("--output", help="Explicit NFO output path")
    p_nfo_generate.add_argument(
        "--no-overwrite", action="store_true", help="Keep an existing NFO sidecar"
    )
    p_nfo_generate.add_argument("--json", action="store_true", help="Emit a JSON result")

    p_projects = subparsers.add_parser(
        "projects",
        help="Audit media references in video-project files",
    )
    projects_subparsers = p_projects.add_subparsers(dest="projects_command")
    p_projects_audit = projects_subparsers.add_parser(
        "audit",
        help="Find referenced, shared, orphaned, and missing media assets",
    )
    p_projects_audit.add_argument("source", help="Project file or directory to audit")
    p_projects_audit.add_argument(
        "--library",
        help="UniFile library root to update when --apply is specified",
    )
    p_projects_audit.add_argument(
        "--apply",
        action="store_true",
        help="Tag resolved assets with project names and project modified dates",
    )
    p_projects_audit.add_argument("--json", action="store_true", help="Emit a JSON report")

    p_mobile = subparsers.add_parser(
        "mobile",
        help="Start the read-only LAN PWA companion",
    )
    p_mobile.add_argument(
        "--library",
        default=os.environ.get("UNIFILE_LIBRARY_DIR", os.path.join(os.path.expanduser("~"), "UniFileLibrary")),
        help="UniFile library root (default: UNIFILE_LIBRARY_DIR or ~/UniFileLibrary)",
    )
    p_mobile.add_argument(
        "--host",
        default=os.environ.get("UNIFILE_MOBILE_HOST", "0.0.0.0"),
        help="Bind address (default: 0.0.0.0 for LAN access)",
    )
    p_mobile.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("UNIFILE_MOBILE_PORT", "8788")),
        help="Bind port (default: 8788)",
    )
    p_mobile.add_argument(
        "--token",
        default=None,
        help="Optional URL token; a random token is generated when omitted",
    )

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
    if args.subcommand == "scan":
        sys.exit(_cmd_scan(args))
    if args.subcommand == "watch":
        sys.exit(_cmd_watch(args))
    if args.subcommand == "tag":
        sys.exit(_cmd_tag(args))
    if args.subcommand == "report":
        sys.exit(_cmd_report(args))
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
    if args.subcommand == "verify":
        sys.exit(_cmd_verify(args))
    if args.subcommand == "collab":
        if args.collab_command == "init":
            sys.exit(_cmd_collab_init(args))
        if args.collab_command == "add-user":
            sys.exit(_cmd_collab_add_user(args))
        if args.collab_command == "list-users":
            sys.exit(_cmd_collab_list_users(args))
        if args.collab_command == "search":
            sys.exit(_cmd_collab_search(args))
        if args.collab_command == "tag":
            sys.exit(_cmd_collab_tag(args))
        print("error: choose a collab command (init, add-user, list-users, search, or tag)", file=sys.stderr)
        sys.exit(2)
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
    if args.subcommand == "nfo":
        if args.nfo_command == "generate":
            sys.exit(_cmd_nfo_generate(args))
        print("error: choose an nfo command (currently: generate)", file=sys.stderr)
        sys.exit(2)
    if args.subcommand == "projects":
        if args.projects_command == "audit":
            sys.exit(_cmd_projects_audit(args))
        print("error: choose a projects command (currently: audit)", file=sys.stderr)
        sys.exit(2)
    if args.subcommand == "mobile":
        sys.exit(_cmd_mobile(args))

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
                    window._prepare_auto_apply()
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
