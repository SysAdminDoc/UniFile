"""Validated, review-first file action plans shared by GUI and CLI flows.

An action plan is deliberately narrower than a general workflow language: the
only filesystem operation currently supported is a collision-safe file move.
The narrow contract lets provider output, exported CLI plans, and the GUI
review surface share the same validation and approval boundary.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

ACTION_PLAN_SCHEMA_VERSION = 1
MAX_ACTIONS = 100_000
MAX_PLAN_BYTES = 12 * 1024 * 1024
SUPPORTED_OPERATIONS = frozenset({"move", "rename"})


class ActionPlanError(ValueError):
    """Raised when an action plan is malformed, unsafe, or cannot be applied."""


def _path_within(candidate: str, root: str) -> bool:
    try:
        return os.path.commonpath([
            os.path.normcase(os.path.abspath(candidate)),
            os.path.normcase(os.path.abspath(root)),
        ]) == os.path.normcase(os.path.abspath(root))
    except (OSError, ValueError):
        return False


def _real_path_within(candidate: str, root: str) -> bool:
    return _path_within(os.path.realpath(candidate), os.path.realpath(root))


def _root_path(value: Any, *, label: str, require_directory: bool = True) -> str:
    text = str(value or "").strip()
    if not text:
        raise ActionPlanError(f"The action plan needs a {label}.")
    path = os.path.realpath(os.path.abspath(os.path.expanduser(text)))
    if require_directory and os.path.exists(path) and not os.path.isdir(path):
        raise ActionPlanError(f"The action plan {label} is not a directory: {path}")
    if os.path.islink(text):
        raise ActionPlanError(f"The action plan {label} must not be a link.")
    return path


def _coerce_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        if len(payload) > MAX_PLAN_BYTES:
            raise ActionPlanError("The action plan is larger than the safety limit.")
        payload = bytes(payload).decode("utf-8")
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_PLAN_BYTES:
            raise ActionPlanError("The action plan is larger than the safety limit.")
        try:
            payload = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ActionPlanError("The action plan is not valid JSON.") from exc
    if isinstance(payload, list):
        payload = {"actions": payload}
    if isinstance(payload, dict) and isinstance(payload.get("action_plan"), dict):
        payload = payload["action_plan"]
    if not isinstance(payload, dict):
        raise ActionPlanError("The action plan must be a JSON object or action list.")
    return dict(payload)


def _normalise_roots(data: dict[str, Any], source_root: str | os.PathLike[str] | None,
                     destination_roots: Iterable[str | os.PathLike[str]] | None) -> tuple[str, list[str]]:
    source_value = data.get("source_root") or data.get("source") or source_root
    root = _root_path(source_value, label="source_root")

    values: list[Any] = []
    raw_destinations = data.get("destination_roots", data.get("destination_root", []))
    if isinstance(raw_destinations, (str, os.PathLike)):
        values.append(raw_destinations)
    elif isinstance(raw_destinations, list):
        values.extend(raw_destinations)
    elif raw_destinations:
        raise ActionPlanError("destination_roots must be a string or list.")
    if destination_roots is not None:
        values.extend(destination_roots)

    normalised: list[str] = []
    for value in values:
        if value is None or not str(value).strip():
            continue
        path = _root_path(value, label="destination_root")
        if os.path.normcase(path) not in {os.path.normcase(item) for item in normalised}:
            normalised.append(path)
    return root, normalised


def _allowed_destination(path: str, source_root: str, destination_roots: list[str]) -> bool:
    roots = [source_root, *destination_roots]
    return any(_path_within(path, root) and _real_path_within(os.path.dirname(path) or root, root)
               for root in roots)


def _relative_path(path: str, roots: list[str]) -> str:
    for root in roots:
        if _path_within(path, root):
            return os.path.relpath(path, root).replace(os.sep, "/")
    return path.replace(os.sep, "/")


def _safe_text(value: Any, field: str, maximum: int = 2_000) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        raise ActionPlanError(f"Action field '{field}' must be a scalar value.")
    text = str(value).strip()
    if len(text) > maximum:
        raise ActionPlanError(f"Action field '{field}' is too long.")
    return text


def _normalise_action(action: Any, index: int, source_root: str,
                      destination_roots: list[str]) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise ActionPlanError(f"Action {index + 1} must be an object.")
    raw_source = action.get("source", action.get("src"))
    raw_destination = action.get("destination", action.get("dst"))
    if raw_source is None or raw_destination is None:
        raise ActionPlanError(f"Action {index + 1} needs source and destination paths.")

    source_text = _safe_text(raw_source, "source", 8_000)
    destination_text = _safe_text(raw_destination, "destination", 8_000)
    source = os.path.abspath(source_text if os.path.isabs(source_text)
                             else os.path.join(source_root, source_text))
    destination = os.path.abspath(destination_text if os.path.isabs(destination_text)
                                  else os.path.join(source_root, destination_text))
    source = os.path.normpath(source)
    destination = os.path.normpath(destination)
    if not _path_within(source, source_root) or not _real_path_within(source, source_root):
        raise ActionPlanError(f"Action {index + 1} source leaves source_root.")
    if not _allowed_destination(destination, source_root, destination_roots):
        raise ActionPlanError(f"Action {index + 1} destination leaves the approved roots.")
    if os.path.normcase(source) == os.path.normcase(destination):
        raise ActionPlanError(f"Action {index + 1} has identical source and destination paths.")

    operation = _safe_text(action.get("operation", "move"), "operation", 32).lower()
    if operation == "rename":
        operation = "move"
    if operation not in SUPPORTED_OPERATIONS:
        raise ActionPlanError(f"Unsupported action operation: {operation}")

    action_id = _safe_text(action.get("id", f"action-{index + 1:05d}"), "id", 160)
    if not action_id:
        raise ActionPlanError(f"Action {index + 1} needs an id.")
    confidence = action.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            raise ActionPlanError(f"Action {index + 1} confidence must be numeric.") from None
        if confidence != confidence or not 0 <= confidence <= 100:
            raise ActionPlanError(f"Action {index + 1} confidence must be from 0 to 100.")
        confidence = int(round(confidence))
    metadata = action.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ActionPlanError(f"Action {index + 1} metadata must be an object.")

    result = dict(action)
    result.update({
        "id": action_id,
        "operation": operation,
        "source": source,
        "destination": destination,
        "relative_source": _relative_path(source, [source_root]),
        "relative_destination": _relative_path(destination, [source_root, *destination_roots]),
        "reason": _safe_text(action.get("reason", ""), "reason", 2_000),
        "metadata": metadata,
    })
    if confidence is not None:
        result["confidence"] = confidence
    return result


def _default_nodes() -> list[dict[str, Any]]:
    return [
        {"id": "propose", "type": "action_list", "depends_on": []},
        {"id": "review", "type": "diff_preview", "depends_on": ["propose"],
         "requires_approval": True},
        {"id": "apply", "type": "atomic_apply", "depends_on": ["review"],
         "requires_approval": True},
    ]


def _normalise_nodes(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return _default_nodes()
    if not isinstance(value, list) or not value:
        raise ActionPlanError("The action plan nodes must be a non-empty list.")
    nodes: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, node in enumerate(value):
        if not isinstance(node, dict):
            raise ActionPlanError(f"Action plan node {index + 1} must be an object.")
        node_id = _safe_text(node.get("id"), "node.id", 120)
        if not node_id or node_id in ids:
            raise ActionPlanError("Action plan nodes need unique ids.")
        depends = node.get("depends_on", [])
        if not isinstance(depends, list) or any(not isinstance(item, str) for item in depends):
            raise ActionPlanError(f"Action plan node '{node_id}' has invalid dependencies.")
        if node_id in depends:
            raise ActionPlanError(f"Action plan node '{node_id}' cannot depend on itself.")
        ids.add(node_id)
        nodes.append({**node, "id": node_id, "depends_on": list(dict.fromkeys(depends))})
    for node in nodes:
        if any(dependency not in ids for dependency in node["depends_on"]):
            raise ActionPlanError(f"Action plan node '{node['id']}' has an unknown dependency.")

    pending = {node["id"]: set(node["depends_on"]) for node in nodes}
    completed: set[str] = set()
    while pending:
        ready = [node_id for node_id, dependencies in pending.items()
                 if dependencies <= completed]
        if not ready:
            raise ActionPlanError("The action plan nodes contain a dependency cycle.")
        completed.update(ready)
        for node_id in ready:
            pending.pop(node_id)
    apply_nodes = [node for node in nodes if node["id"] == "apply"]
    if not apply_nodes or not bool(apply_nodes[0].get("requires_approval")):
        raise ActionPlanError("The action plan apply node must require approval.")
    return nodes


def normalize_action_plan(payload: Any, *, source_root: str | os.PathLike[str] | None = None,
                          destination_roots: Iterable[str | os.PathLike[str]] | None = None) -> dict[str, Any]:
    """Validate provider/CLI JSON and return the canonical action-plan shape."""
    data = _coerce_payload(payload)
    schema = data.get("schema_version", ACTION_PLAN_SCHEMA_VERSION)
    if isinstance(schema, bool) or schema != ACTION_PLAN_SCHEMA_VERSION:
        raise ActionPlanError("Unsupported action plan schema version.")
    root, destinations = _normalise_roots(data, source_root, destination_roots)
    raw_actions = data.get("actions")
    if not isinstance(raw_actions, list):
        raise ActionPlanError("The action plan needs an actions list.")
    if len(raw_actions) > MAX_ACTIONS:
        raise ActionPlanError("The action plan is larger than the safety limit.")
    actions: list[dict[str, Any]] = []
    ids: set[str] = set()
    sources: set[str] = set()
    for index, raw_action in enumerate(raw_actions):
        action = _normalise_action(raw_action, index, root, destinations)
        if action["id"] in ids:
            raise ActionPlanError("The action plan contains duplicate action ids.")
        source_key = os.path.normcase(os.path.realpath(action["source"]))
        if source_key in sources:
            raise ActionPlanError("The action plan contains duplicate source paths.")
        ids.add(action["id"])
        sources.add(source_key)
        actions.append(action)

    nodes = _normalise_nodes(data.get("nodes"))
    stats = data.get("stats", {})
    if stats is None:
        stats = {}
    if not isinstance(stats, dict):
        raise ActionPlanError("Action plan stats must be an object.")
    stats = dict(stats)
    stats.setdefault("actions", len(actions))
    stats.setdefault("proposed", len(actions))

    result = dict(data)
    result.update({
        "schema_version": ACTION_PLAN_SCHEMA_VERSION,
        "plan_type": "file-actions",
        "source_root": root,
        "destination_roots": destinations,
        "nodes": nodes,
        "stats": stats,
        "actions": actions,
    })
    return result


def build_action_plan(*, source_root: str | os.PathLike[str], actions: Iterable[dict[str, Any]],
                      destination_roots: Iterable[str | os.PathLike[str]] | None = None,
                      prompt: str = "", provider: str = "", nodes: list[dict[str, Any]] | None = None,
                      stats: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None,
                      **extra: Any) -> dict[str, Any]:
    """Build and validate a canonical plan from local or provider actions."""
    payload: dict[str, Any] = {
        "schema_version": ACTION_PLAN_SCHEMA_VERSION,
        "source_root": os.fspath(source_root),
        "destination_roots": [os.fspath(path) for path in (destination_roots or [])],
        "prompt": str(prompt or "").strip()[:2_000],
        "provider": str(provider or "").strip()[:160],
        "actions": list(actions),
        "nodes": nodes,
        "stats": dict(stats or {}),
    }
    if metadata is not None:
        payload["metadata"] = dict(metadata)
    payload.update(extra)
    return normalize_action_plan(payload)


def load_action_plan_file(path: str | os.PathLike[str], *, source_root: str | os.PathLike[str] | None = None,
                          destination_roots: Iterable[str | os.PathLike[str]] | None = None) -> dict[str, Any]:
    """Load a bounded UTF-8 JSON action plan, including a CLI scan envelope."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ActionPlanError(f"Could not read action plan: {exc}") from exc
    if len(data) > MAX_PLAN_BYTES:
        raise ActionPlanError("The action plan is larger than the safety limit.")
    return normalize_action_plan(data, source_root=source_root, destination_roots=destination_roots)


def action_plan_from_scan_result(result: dict[str, Any]) -> dict[str, Any]:
    """Convert a headless scan result into the shared review/apply contract."""
    source_root = str(result.get("source", ""))
    raw_items = result.get("items", [])
    if not isinstance(raw_items, list):
        raise ActionPlanError("The scan result items must be a list.")
    actions = []
    destination_roots: list[str] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict) or not item.get("selected"):
            continue
        source = str(item.get("src", "")).strip()
        destination = str(item.get("dst", "")).strip()
        if not source or not destination:
            continue
        destination_roots.append(str(Path(destination).parent))
        category = str(item.get("category", "Other") or "Other")
        reason = str(item.get("reason", "") or "")
        if not reason:
            reason = f"{category} ({int(item.get('confidence', 0) or 0)}% confidence)"
        actions.append({
            "id": f"scan-action-{index + 1:05d}",
            "operation": "move",
            "source": source,
            "destination": destination,
            "reason": reason,
            "confidence": item.get("confidence"),
            "category": category,
            "method": str(item.get("method", "") or ""),
            "status": str(item.get("status", "Pending") or "Pending"),
            "metadata": {"size": item.get("size", 0)},
        })
    explicit_destination = str(result.get("destination", "") or "").strip()
    if explicit_destination:
        destination_roots = [explicit_destination]
    stats = dict(result.get("stats", {}) if isinstance(result.get("stats"), dict) else {})
    stats.update({
        "scanned": result.get("count", len(raw_items)),
        "candidates": result.get("selected_count", len(actions)),
        "actions": len(actions),
        "would_move": result.get("would_move", len(actions)),
    })
    return build_action_plan(
        source_root=source_root,
        destination_roots=destination_roots,
        actions=actions,
        prompt="Headless scan dry-run",
        provider="rule-based classifier",
        nodes=[
            {"id": "discover", "type": "scan", "depends_on": []},
            {"id": "classify", "type": "rule_classifier", "depends_on": ["discover"]},
            {"id": "route", "type": "destination_resolve", "depends_on": ["classify"]},
            {"id": "review", "type": "diff_preview", "depends_on": ["route"],
             "requires_approval": True},
            {"id": "apply", "type": "atomic_apply", "depends_on": ["review"],
             "requires_approval": True},
        ],
        stats=stats,
        metadata={
            "scan_schema_version": result.get("version", ""),
            "dry_run": bool(result.get("dry_run", False)),
        },
        mode=str(result.get("mode", "headless-rule-based")),
    )


def _collision_free_path(path: str, reserved: set[str]) -> str:
    def key(candidate: str) -> str:
        return os.path.normcase(os.path.realpath(candidate))

    candidate = os.path.abspath(path)
    if not os.path.lexists(candidate) and key(candidate) not in reserved:
        reserved.add(key(candidate))
        return candidate
    base, extension = os.path.splitext(candidate)
    for number in range(2, 10_001):
        candidate = f"{base} ({number}){extension}"
        if not os.path.lexists(candidate) and key(candidate) not in reserved:
            reserved.add(key(candidate))
            return candidate
    raise ActionPlanError(f"Could not find a collision-free destination for {path}.")


def apply_action_plan(plan: dict[str, Any], *, approved: bool = False,
                      action_ids: Iterable[str] | None = None,
                      log_cb: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Apply approved moves transactionally, rolling back on a failed batch."""
    if not approved:
        raise ActionPlanError("Plan approval is required before applying moves.")
    normalised = normalize_action_plan(plan)
    selected_ids = None if action_ids is None else {str(item) for item in action_ids}
    actions = [
        action for action in normalised["actions"]
        if (selected_ids is None or action["id"] in selected_ids)
        and action.get("selected", True) is not False
    ]
    result: dict[str, Any] = {
        "applied": 0,
        "skipped": len(normalised["actions"]) - len(actions),
        "rolled_back": 0,
        "errors": [],
        "undo_ops": [],
        "details": [],
    }
    if not actions:
        return result

    source_keys: set[str] = set()
    for action in actions:
        source = action["source"]
        if os.path.normcase(os.path.realpath(source)) in source_keys:
            raise ActionPlanError("The approved action selection contains duplicate sources.")
        if not os.path.isfile(source) or os.path.islink(source):
            result["errors"].append({"id": action["id"], "error": "source missing or is not a regular file"})
            result["details"].append({"id": action["id"], "status": "error", "reason": "source missing"})
            continue
        source_keys.add(os.path.normcase(os.path.realpath(source)))
    if result["errors"]:
        return result

    reserved: set[str] = set()
    planned: list[tuple[dict[str, Any], str]] = []
    for action in actions:
        destination = action["destination"]
        destination_key = os.path.normcase(os.path.realpath(destination))
        if os.path.lexists(destination) and destination_key not in source_keys:
            actual = _collision_free_path(destination, reserved)
        elif destination_key in reserved:
            actual = _collision_free_path(destination, reserved)
        else:
            reserved.add(destination_key)
            actual = destination
        planned.append((action, actual))

    root = normalised["source_root"]
    try:
        stage_dir = tempfile.mkdtemp(prefix=".unifile-action-plan-", dir=root)
    except OSError as exc:
        raise ActionPlanError(f"Could not create the action staging area: {exc}") from exc

    staged: list[tuple[dict[str, Any], str, str]] = []
    committed: list[tuple[dict[str, Any], str, str]] = []
    try:
        for index, (action, actual) in enumerate(planned):
            stage_path = os.path.join(stage_dir, f"{index:08d}.stage")
            shutil.move(action["source"], stage_path)
            staged.append((action, stage_path, actual))
        for action, stage_path, actual in staged:
            parent = os.path.dirname(actual) or root
            os.makedirs(parent, exist_ok=True)
            if not _allowed_destination(actual, root, normalised["destination_roots"]):
                raise ActionPlanError("The destination changed outside the approved roots.")
            if os.path.lexists(actual):
                reserved.discard(os.path.normcase(os.path.realpath(actual)))
                actual = _collision_free_path(actual, reserved)
            shutil.move(stage_path, actual)
            committed.append((action, stage_path, actual))
    except (OSError, ActionPlanError) as exc:
        rollback_errors: list[str] = []
        for action, stage_path, actual in reversed(committed):
            try:
                if os.path.exists(actual):
                    shutil.move(actual, stage_path)
            except (OSError, shutil.Error) as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for action, stage_path, _actual in reversed(staged):
            try:
                if os.path.exists(stage_path):
                    shutil.move(stage_path, action["source"])
            except (OSError, shutil.Error) as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        result["rolled_back"] = len(committed)
        result["errors"].append({"error": str(exc), "rollback_errors": rollback_errors})
        result["details"] = [
            {"id": action["id"], "status": "rolled back", "reason": str(exc)}
            for action, _stage, _actual in staged
        ]
        return result
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)

    result["applied"] = len(committed)
    for action, _stage_path, actual in committed:
        relative_source = _relative_path(action["source"], [root])
        relative_destination = _relative_path(
            actual, [root, *normalised["destination_roots"]]
        )
        result["undo_ops"].append({
            "type": "move",
            "src": actual,
            "dst": action["source"],
            "status": "Done",
        })
        result["details"].append({
            "id": action["id"],
            "status": "applied",
            "source": relative_source,
            "destination": relative_destination,
        })
        if log_cb:
            log_cb(f"Moved {relative_source} → {relative_destination}")
    return result


__all__ = [
    "ACTION_PLAN_SCHEMA_VERSION",
    "ActionPlanError",
    "action_plan_from_scan_result",
    "apply_action_plan",
    "build_action_plan",
    "load_action_plan_file",
    "normalize_action_plan",
]
