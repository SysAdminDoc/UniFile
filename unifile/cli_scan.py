"""Qt-free scan planning and rule application for the command line."""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from unifile.config import is_protected
from unifile.engine import RuleEngine, apply_rule_delta
from unifile.files import (
    _build_ext_map,
    _classify_pc_item,
    _load_pc_categories,
    default_pc_destination,
    load_directory_config,
    load_directory_rules,
    merge_categories,
)

SCAN_SCHEMA_VERSION = "1"
MAX_SCAN_ITEMS = 10_000
DEFAULT_MIN_CONFIDENCE = 80

_SKIP_NAME_PREFIXES = (".", "$")
_INVALID_CATEGORY_CHARS = re.compile(r'[<>:"/\\|?*]')


def _inside(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    """Return whether *path* is inside *root*, including equality."""
    try:
        candidate = os.path.realpath(os.path.abspath(os.fspath(path)))
        base = os.path.realpath(os.path.abspath(os.fspath(root)))
        return os.path.commonpath([candidate, base]) == base
    except (OSError, ValueError):
        return False


def _category_folder_name(category: str) -> str:
    """Turn a user-configured category into one safe destination segment."""
    cleaned = _INVALID_CATEGORY_CHARS.sub("_", str(category or "")).strip(" .")
    return (cleaned or "Other")[:120]


def _effective_categories(source: Path) -> list[dict[str, Any]]:
    categories = _load_pc_categories()
    local = load_directory_config(str(source))
    return merge_categories(categories, local) if local else categories


def _effective_rules(source: Path) -> list[dict[str, Any]]:
    """Load library rules, preferring a source-local rules file when present."""
    local_rules = RuleEngine.load_rules(str(source))
    base_rules = local_rules or RuleEngine.load_rules()
    return apply_rule_delta(base_rules, load_directory_rules(str(source)))


def _destination_for_category(
    category: str,
    categories: list[dict[str, Any]],
    source: Path,
    destination_root: Path | None,
) -> Path:
    if destination_root is not None:
        return destination_root / _category_folder_name(category)

    definition = next(
        (item for item in categories if str(item.get("name", "")).casefold() == category.casefold()),
        {},
    )
    configured = str(definition.get("custom_dst") or definition.get("output_dir") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else source / path
    return Path(default_pc_destination(_category_folder_name(category))).expanduser()


def _collision_safe_path(path: Path, reserved: set[str]) -> Path:
    """Return a non-overwriting destination and reserve its normalized key."""
    def key(candidate: Path) -> str:
        return os.path.normcase(os.path.realpath(str(candidate)))

    candidate = path
    if not os.path.exists(candidate) and key(candidate) not in reserved:
        reserved.add(key(candidate))
        return candidate

    stem = path.stem
    suffix = path.suffix
    for number in range(2, 10_001):
        candidate = path.with_name(f"{stem} ({number}){suffix}")
        if not os.path.exists(candidate) and key(candidate) not in reserved:
            reserved.add(key(candidate))
            return candidate
    raise OSError(f"could not find a free destination for {path.name}")


def _walk_files(source: Path, destination_roots: list[Path]):
    for root, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [
            name for name in dirs
            if not name.startswith(_SKIP_NAME_PREFIXES)
            and not os.path.islink(os.path.join(root, name))
            and not any(_inside(os.path.join(root, name), destination) for destination in destination_roots)
        ]
        for name in sorted(files, key=str.casefold):
            if name.startswith(_SKIP_NAME_PREFIXES):
                continue
            filepath = Path(root) / name
            try:
                if filepath.is_symlink() or not filepath.is_file():
                    continue
            except OSError:
                continue
            yield filepath


def _apply_rule_classification(
    filepath: Path,
    category: str,
    confidence: float,
    method: str,
    rules: list[dict[str, Any]],
) -> tuple[str, float, str]:
    if not rules:
        return category, confidence, method
    item = SimpleNamespace(
        name=filepath.name,
        full_src=str(filepath),
        size=filepath.stat().st_size,
        metadata={},
        category=category,
        confidence=confidence,
    )
    result = RuleEngine.evaluate(item, rules)
    if not result:
        return category, confidence, method
    rule_category, _rename_template, rule_confidence = result
    rule_category = str(rule_category or "").strip()
    try:
        rule_confidence = float(rule_confidence)
    except (TypeError, ValueError):
        rule_confidence = 0
    if rule_category and rule_confidence > confidence:
        return rule_category, rule_confidence, "rule"
    return category, confidence, method


def plan_file_action(
    filepath: Path,
    *,
    source_path: Path,
    destination_path: Path | None,
    categories: list[dict[str, Any]],
    ext_map: dict[str, str],
    rules: list[dict[str, Any]],
    min_confidence: int,
    reserved: set[str],
) -> dict[str, Any]:
    """Classify one file and build the same safe action used by ``scan``.

    The watch daemon uses this narrow helper so a settled file is handled by
    the exact category, confidence, rule, and collision policy as a batch scan.
    """
    stat = filepath.stat()
    category, confidence, method = _classify_pc_item(
        str(filepath), ext_map, is_folder=False, categories=categories
    )
    category, confidence, method = _apply_rule_classification(
        filepath, category, confidence, method, rules
    )
    category = str(category or "Other")
    confidence = float(confidence or 0)
    eligible = bool(category and category.casefold() != "other" and confidence >= min_confidence)
    status = "Pending" if eligible else "Skip"
    reason = "" if eligible else "below confidence threshold or unclassified"
    target = ""
    selected = False
    if eligible:
        destination_dir = _destination_for_category(
            category, categories, source_path, destination_path
        ).resolve()
        target_path = destination_dir / filepath.name
        if _inside(destination_dir, source_path):
            status = "Unsafe destination"
            reason = "destination is inside the source directory"
        elif is_protected(str(destination_dir)):
            status = "Protected destination"
            reason = "destination is protected"
        elif os.path.normcase(os.path.realpath(str(target_path))) == os.path.normcase(
            os.path.realpath(str(filepath))
        ):
            status = "Already organized"
            reason = "source is already at the planned destination"
            target = str(target_path)
        else:
            target = str(_collision_safe_path(target_path, reserved))
            selected = True

    return {
        "name": filepath.name,
        "src": str(filepath),
        "dst": target,
        "category": category,
        "confidence": int(confidence),
        "method": method,
        "size": stat.st_size,
        "selected": selected,
        "status": status,
        "reason": reason,
    }


def scan_directory(
    source: str | os.PathLike[str],
    *,
    destination: str | os.PathLike[str] | None = None,
    limit: int = MAX_SCAN_ITEMS,
    apply_rules: bool = False,
    dry_run: bool = False,
    min_confidence: int = DEFAULT_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Build a deterministic file move plan and optionally apply it.

    The scan is review-first: without ``apply_rules`` it never writes to the
    source or destination. Applying always uses collision-safe names, skips
    protected paths, and never treats a low-confidence ``Other`` result as a
    move candidate.
    """
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_dir():
        raise ValueError(f"not a directory: {source_path}")
    bounded_limit = max(1, min(MAX_SCAN_ITEMS, int(limit)))
    confidence_floor = max(0, min(100, int(min_confidence)))
    destination_path = (
        Path(destination).expanduser().resolve() if destination is not None else None
    )
    if destination_path is not None and _inside(destination_path, source_path):
        raise ValueError("destination must be outside the source directory")

    categories = _effective_categories(source_path)
    ext_map = _build_ext_map(categories)
    rules = _effective_rules(source_path)

    destination_roots = [
        _destination_for_category(str(category.get("name", "Other")), categories, source_path, destination_path)
        for category in categories
    ]
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    reserved: set[str] = set()

    for filepath in _walk_files(source_path, destination_roots):
        if len(items) >= bounded_limit:
            break
        try:
            item = plan_file_action(
                filepath,
                source_path=source_path,
                destination_path=destination_path,
                categories=categories,
                ext_map=ext_map,
                rules=rules,
                min_confidence=confidence_floor,
                reserved=reserved,
            )
        except (OSError, TypeError, ValueError) as exc:
            errors.append({"src": str(filepath), "error": str(exc)})
            continue
        items.append(item)

    moved = 0
    would_move = sum(1 for item in items if item["selected"])
    failed = 0
    if apply_rules:
        planned_keys = {
            os.path.normcase(os.path.realpath(item["dst"]))
            for item in items
            if item["selected"] and item["dst"]
        }
        runtime_keys: set[str] = set()
        if dry_run:
            for item in items:
                if item["selected"]:
                    item["status"] = "Dry run"
        else:
            for item in items:
                if not item["selected"]:
                    continue
                source_file = Path(item["src"])
                if is_protected(str(source_file)):
                    item["selected"] = False
                    item["status"] = "Protected"
                    item["reason"] = "source is protected"
                    continue
                target_file = Path(item["dst"])
                current_key = os.path.normcase(os.path.realpath(str(target_file)))
                if os.path.exists(target_file) or current_key in runtime_keys:
                    available_keys = (planned_keys - {current_key}) | runtime_keys
                    try:
                        target_file = _collision_safe_path(target_file, available_keys)
                    except OSError as exc:
                        failed += 1
                        item["status"] = "Error"
                        item["reason"] = str(exc)
                        errors.append({"src": item["src"], "error": str(exc)})
                        continue
                    item["dst"] = str(target_file)
                try:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source_file), str(target_file))
                except (OSError, shutil.Error) as exc:
                    failed += 1
                    item["status"] = "Error"
                    item["reason"] = str(exc)
                    errors.append({"src": item["src"], "error": str(exc)})
                    continue
                runtime_keys.add(os.path.normcase(os.path.realpath(str(target_file))))
                item["status"] = "Done"
                moved += 1

    return {
        "version": SCAN_SCHEMA_VERSION,
        "timestamp": datetime.now().isoformat(),
        "source": str(source_path),
        "destination": str(destination_path) if destination_path else "",
        "mode": "headless-rule-apply" if apply_rules else "headless-rule-based",
        "apply_rules": bool(apply_rules),
        "dry_run": bool(dry_run and apply_rules),
        "min_confidence": confidence_floor,
        "rules_count": len(rules),
        "items": items,
        "count": len(items),
        "selected_count": sum(1 for item in items if item["selected"]),
        "would_move": would_move,
        "moved": moved,
        "failed": failed,
        "errors": errors,
    }
