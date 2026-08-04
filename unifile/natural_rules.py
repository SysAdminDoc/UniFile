"""Review-first natural-language file rules.

The language model is used once to compile a request into a small, validated
rule.  File discovery, matching, destination expansion, preview generation,
and applying the approved moves all happen locally in this module.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime
from types import SimpleNamespace

from unifile.action_plan import (
    ActionPlanError,
    apply_action_plan,
    build_action_plan,
    normalize_action_plan,
)
from unifile.ai_providers import ProviderChain
from unifile.engine import RenameTemplateEngine, RuleEngine

NATURAL_FIELDS = (
    "name",
    "extension",
    "size",
    "modified_date",
    "created_date",
    "path_contains",
    "name_regex",
    "content",
    "has_ocr_text",
)
NATURAL_OPS = tuple(RuleEngine._OPS)
NATURAL_DESTINATION_TOKENS = ("YYYY-MM", "YYYY", "MM", "DD", "name", "stem", "extension")

# Keep this schema small enough for Ollama, OpenAI-compatible endpoints,
# Anthropic's prompt-constrained JSON, and Gemini responseSchema alike.
NATURAL_RULE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "enabled": {"type": "boolean"},
        "priority": {"type": "integer", "minimum": 1, "maximum": 99},
        "logic": {"type": "string", "enum": ["all", "any"]},
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string", "enum": list(NATURAL_FIELDS)},
                    "op": {"type": "string", "enum": list(NATURAL_OPS)},
                    "value": {"type": "string"},
                },
                "required": ["field", "op", "value"],
            },
        },
        "action_destination": {"type": "string"},
        "action_category": {"type": "string"},
        "action_rename": {"type": "string"},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["name", "conditions", "action_destination"],
}

PLAN_SCHEMA_VERSION = 1
_RULE_KEYS = {
    "name",
    "enabled",
    "priority",
    "logic",
    "conditions",
    "action_destination",
    "action_category",
    "action_rename",
    "confidence",
    "source_prompt",
}
_INVALID_PATH_CHARS = re.compile(r"[\x00-\x1f<>:\"|?*]")
_BRACE_TOKEN = re.compile(r"\{([^{}]+)\}")


class NaturalRuleError(ValueError):
    """Raised when a natural rule or action plan fails validation."""


def _extract_json(raw: str | dict) -> dict:
    """Extract one JSON object from a provider response."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        raise NaturalRuleError("The provider returned an empty rule.")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        value = None
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
                break
            except json.JSONDecodeError:
                continue
        if value is None:
            raise NaturalRuleError("The provider did not return a JSON rule.")
    if not isinstance(value, dict):
        raise NaturalRuleError("The provider rule must be a JSON object.")
    return value


def _as_bounded_string(value, field: str, maximum: int = 512) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        raise NaturalRuleError(f"Rule field '{field}' must be a scalar value.")
    result = str(value).strip()
    if not result:
        raise NaturalRuleError(f"Rule field '{field}' cannot be empty.")
    if len(result) > maximum:
        raise NaturalRuleError(f"Rule field '{field}' is too long.")
    return result


def _normalise_destination_template(value: str) -> str:
    template = _as_bounded_string(value, "action_destination")
    template = template.replace("\\", "/")
    if template.startswith("/") or template.startswith("//"):
        raise NaturalRuleError("The destination must be a relative folder template.")
    if re.match(r"^[A-Za-z]:", template) or os.path.isabs(template):
        raise NaturalRuleError("The destination must not be an absolute path.")
    if "{" in template or "}" in template:
        matches = _BRACE_TOKEN.findall(template)
        rebuilt = _BRACE_TOKEN.sub("", template)
        if len(matches) != template.count("{") or "{" in rebuilt or "}" in rebuilt:
            raise NaturalRuleError("The destination contains an invalid template token.")
        unknown = set(matches) - set(NATURAL_DESTINATION_TOKENS)
        if unknown:
            raise NaturalRuleError(f"Unsupported destination token: {sorted(unknown)[0]}")
    parts = template.split("/")
    if not parts or any(not part or part == "." or part == ".." for part in parts):
        raise NaturalRuleError("The destination contains an unsafe path component.")
    for part in parts:
        if _INVALID_PATH_CHARS.search(part) or part.endswith((".", " ")):
            raise NaturalRuleError("The destination contains an invalid path component.")
    return "/".join(parts)


def normalize_natural_rule(payload: str | dict, prompt: str = "") -> dict:
    """Validate and normalize one provider-produced rule."""
    data = _extract_json(payload)
    if isinstance(data.get("rule"), dict):
        data = data["rule"]
    unknown = set(data) - _RULE_KEYS
    if unknown:
        raise NaturalRuleError(f"Unsupported rule field: {sorted(unknown)[0]}")

    name = _as_bounded_string(data.get("name"), "name", 160)
    raw_conditions = data.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise NaturalRuleError("A natural rule needs at least one condition.")
    conditions = []
    for index, condition in enumerate(raw_conditions):
        if not isinstance(condition, dict):
            raise NaturalRuleError(f"Condition {index + 1} must be an object.")
        if set(condition) != {"field", "op", "value"}:
            raise NaturalRuleError(f"Condition {index + 1} has unsupported fields.")
        field = _as_bounded_string(condition.get("field"), "condition.field", 64).lower()
        op = _as_bounded_string(condition.get("op"), "condition.op", 64).lower()
        if field not in NATURAL_FIELDS:
            raise NaturalRuleError(f"Unsupported rule field: {field}")
        if op not in NATURAL_OPS:
            raise NaturalRuleError(f"Unsupported rule operator: {op}")
        value = _as_bounded_string(condition.get("value"), "condition.value", 300)
        conditions.append({"field": field, "op": op, "value": value})

    logic = str(data.get("logic", "all") or "all").strip().lower()
    if logic not in {"all", "any"}:
        raise NaturalRuleError("Rule logic must be 'all' or 'any'.")

    try:
        priority = int(data.get("priority", 50))
    except (TypeError, ValueError):
        raise NaturalRuleError("Rule priority must be an integer from 1 to 99.") from None
    if isinstance(data.get("priority", 50), bool) or not 1 <= priority <= 99:
        raise NaturalRuleError("Rule priority must be an integer from 1 to 99.")

    try:
        confidence = float(data.get("confidence", 90))
    except (TypeError, ValueError):
        raise NaturalRuleError("Rule confidence must be a number from 0 to 100.") from None
    if not math.isfinite(confidence) or not 0 <= confidence <= 100:
        raise NaturalRuleError("Rule confidence must be a number from 0 to 100.")

    destination = data.get("action_destination") or data.get("action_category")
    if not destination:
        raise NaturalRuleError("The rule needs an action_destination folder.")
    destination = _normalise_destination_template(destination)

    rename = str(data.get("action_rename", "") or "").strip()
    if len(rename) > 240 or "/" in rename or "\\" in rename:
        raise NaturalRuleError("action_rename must be a single safe filename template.")

    return {
        "name": name,
        "enabled": bool(data.get("enabled", True)),
        "priority": priority,
        "logic": logic,
        "conditions": conditions,
        "action_destination": destination,
        "action_category": str(data.get("action_category", "") or "").strip(),
        "action_rename": rename,
        "confidence": int(round(confidence)),
        "source_prompt": str(prompt or "").strip()[:2_000],
    }


def parse_natural_rule(prompt: str, provider_chain: ProviderChain | None = None) -> tuple[dict, str]:
    """Ask the configured provider chain to compile one natural rule."""
    prompt = str(prompt or "").strip()
    if not prompt:
        raise NaturalRuleError("Describe the files and destination first.")
    system = (
        "Compile the user's request into exactly one JSON file-routing rule. "
        "Do not inspect files, perform operations, or invent metadata. "
        "Use only the listed fields and operators. action_destination must be "
        "a relative folder template under the selected source root; it may use "
        "YYYY, MM, DD, YYYY-MM, name, stem, or extension. "
        "Return only the JSON object."
    )
    chain = provider_chain or ProviderChain()
    raw, provider_key = chain.classify(
        prompt,
        system=system,
        format=NATURAL_RULE_SCHEMA,
    )
    if not raw:
        raise NaturalRuleError("No configured AI provider returned a rule.")
    return normalize_natural_rule(raw, prompt=prompt), str(provider_key or "")


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


def _root_directory(source_root: str) -> str:
    if not source_root:
        raise NaturalRuleError("Choose a source folder first.")
    root = os.path.realpath(os.path.abspath(os.path.expanduser(str(source_root))))
    if not os.path.isdir(root) or os.path.islink(source_root):
        raise NaturalRuleError("The source folder does not exist or is a link.")
    return root


def _safe_component(value: str, fallback: str = "file") -> str:
    value = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", str(value or ""))
    value = value.strip(" .")
    return value or fallback


def expand_destination_template(template: str, path: str, root: str) -> str:
    """Expand date/name tokens and return a safe relative destination folder."""
    root = _root_directory(root)
    source = os.path.abspath(path)
    if not _real_path_within(source, root) or not os.path.isfile(source):
        raise NaturalRuleError("The source file is outside the selected root.")
    template = _normalise_destination_template(template)
    try:
        stamp = datetime.fromtimestamp(os.path.getmtime(source))
    except OSError as exc:
        raise NaturalRuleError(f"Could not read the source timestamp: {exc}") from exc
    stem, extension = os.path.splitext(os.path.basename(source))
    values = {
        "YYYY-MM": stamp.strftime("%Y-%m"),
        "YYYY": stamp.strftime("%Y"),
        "MM": stamp.strftime("%m"),
        "DD": stamp.strftime("%d"),
        "name": _safe_component(os.path.basename(source)),
        "stem": _safe_component(stem),
        "extension": _safe_component(extension, "") if extension else "",
    }
    parts = []
    for raw_part in template.split("/"):
        part = _BRACE_TOKEN.sub(lambda match: values[match.group(1)], raw_part)
        for token in ("YYYY-MM", "YYYY", "MM", "DD"):
            part = part.replace(token, values[token])
        part = _safe_component(part)
        if not part or part in {".", ".."}:
            raise NaturalRuleError("The expanded destination is unsafe.")
        parts.append(part)
    relative = "/".join(parts)
    destination = os.path.abspath(os.path.join(root, *parts))
    if not _real_path_within(destination, root):
        raise NaturalRuleError("The expanded destination leaves the selected root.")
    return relative


def _iter_rule_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames
            if not os.path.islink(os.path.join(dirpath, name))
        )
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            if _real_path_within(path, root):
                yield os.path.abspath(path)


def _collision_free_path(path: str, reserved: set[str] | None = None) -> str:
    reserved = reserved or set()
    candidate = os.path.abspath(path)
    if not os.path.lexists(candidate) and os.path.normcase(candidate) not in reserved:
        return candidate
    base, extension = os.path.splitext(candidate)
    for index in range(2, 10_000):
        candidate = f"{base} ({index}){extension}"
        if not os.path.lexists(candidate) and os.path.normcase(candidate) not in reserved:
            return candidate
    raise NaturalRuleError(f"Could not find a collision-free destination for {path}.")


def _condition_reason(rule: dict) -> str:
    conditions = [
        f"{item['field']} {item['op']} {item['value']}"
        for item in rule.get("conditions", [])
    ]
    logic = str(rule.get("logic", "all")).upper()
    joined = f" {logic} ".join(conditions)
    return f"Matched {rule.get('name', 'rule')} ({joined})"


def build_natural_rule_plan(
    prompt: str,
    source_root: str,
    parsed_rule: dict | None = None,
    provider_key: str = "",
) -> dict:
    """Compile a rule and build a local, reviewable action DAG."""
    root = _root_directory(source_root)
    if parsed_rule is None:
        rule, provider_key = parse_natural_rule(prompt)
    else:
        rule = normalize_natural_rule(parsed_rule, prompt=prompt)
    files = list(_iter_rule_files(root))
    actions = []
    reserved = set()
    matched_count = 0
    skipped_count = 0
    reason = _condition_reason(rule)
    for source in files:
        try:
            stat = os.stat(source)
            item = SimpleNamespace(
                name=os.path.basename(source),
                size=stat.st_size,
                full_src=source,
                metadata={},
            )
            matched = RuleEngine.match(item, [rule], metadata={})
        except (OSError, ValueError, TypeError):
            matched = None
        if matched is None:
            continue
        matched_count += 1
        try:
            relative_folder = expand_destination_template(
                rule["action_destination"], source, root
            )
            destination_folder = os.path.join(root, *relative_folder.split("/"))
            destination_name = os.path.basename(source)
            if rule.get("action_rename"):
                destination_name = RenameTemplateEngine.preview(
                    rule["action_rename"], source, {}, rule.get("action_category", "")
                )
            destination_name = _safe_component(destination_name, os.path.basename(source))
            desired = os.path.join(destination_folder, destination_name)
            if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(desired)):
                skipped_count += 1
                continue
            destination = _collision_free_path(desired, reserved)
            if not _real_path_within(destination_folder, root):
                raise NaturalRuleError("The destination folder leaves the selected root.")
            reserved.add(os.path.normcase(destination))
            actions.append({
                "id": f"action-{len(actions) + 1:05d}",
                "source": source,
                "relative_source": os.path.relpath(source, root).replace(os.sep, "/"),
                "destination": destination,
                "relative_destination": os.path.relpath(destination, root).replace(os.sep, "/"),
                "reason": reason,
                "confidence": rule.get("confidence", 90),
            })
        except NaturalRuleError:
            skipped_count += 1

    return build_action_plan(
        source_root=root,
        actions=actions,
        prompt=prompt,
        provider=provider_key,
        nodes=[
            {"id": "discover", "type": "scan", "depends_on": []},
            {"id": "match", "type": "rule_filter", "depends_on": ["discover"]},
            {"id": "route", "type": "destination_resolve", "depends_on": ["match"]},
            {"id": "review", "type": "preview", "depends_on": ["route"], "requires_approval": True},
            {"id": "apply", "type": "move", "depends_on": ["review"], "requires_approval": True},
        ],
        stats={
            "scanned": len(files),
            "matched": matched_count,
            "actions": len(actions),
            "skipped": skipped_count,
        },
        rule=rule,
    )


def _validate_plan(plan: dict) -> tuple[str, list[dict]]:
    try:
        normalized = normalize_action_plan(plan)
    except ActionPlanError as exc:
        raise NaturalRuleError(str(exc)) from exc
    return normalized["source_root"], normalized["actions"]


def apply_natural_rule_plan(
    plan: dict,
    *,
    approved: bool = False,
    action_ids: list[str] | None = None,
    log_cb=None,
) -> dict:
    """Apply selected natural-rule actions through the shared transaction."""
    try:
        return apply_action_plan(
            plan,
            approved=approved,
            action_ids=action_ids,
            log_cb=log_cb,
        )
    except ActionPlanError as exc:
        raise NaturalRuleError(str(exc)) from exc


__all__ = [
    "NATURAL_RULE_SCHEMA",
    "NaturalRuleError",
    "apply_natural_rule_plan",
    "build_natural_rule_plan",
    "expand_destination_template",
    "normalize_natural_rule",
    "parse_natural_rule",
]
