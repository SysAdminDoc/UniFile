"""Field type normalization and validation for per-library entry fields."""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from unifile.tagging.models import FieldTypeEnum

FIELD_TYPE_ALIASES = {
    "text": FieldTypeEnum.TEXT_LINE,
    "text_line": FieldTypeEnum.TEXT_LINE,
    "text line": FieldTypeEnum.TEXT_LINE,
    "short text": FieldTypeEnum.TEXT_LINE,
    "long_text": FieldTypeEnum.TEXT_BOX,
    "long text": FieldTypeEnum.TEXT_BOX,
    "text_box": FieldTypeEnum.TEXT_BOX,
    "text box": FieldTypeEnum.TEXT_BOX,
    "date": FieldTypeEnum.DATETIME,
    "datetime": FieldTypeEnum.DATETIME,
    "date/time": FieldTypeEnum.DATETIME,
    "currency": FieldTypeEnum.CURRENCY,
    "money": FieldTypeEnum.CURRENCY,
    "enum": FieldTypeEnum.ENUM,
    "status": FieldTypeEnum.ENUM,
    "status/enum": FieldTypeEnum.ENUM,
    "checkbox": FieldTypeEnum.BOOLEAN,
    "boolean": FieldTypeEnum.BOOLEAN,
    "bool": FieldTypeEnum.BOOLEAN,
}


def normalize_field_type(value: Any) -> FieldTypeEnum | None:
    """Return the supported field enum for a user or API supplied type."""
    if isinstance(value, FieldTypeEnum):
        return value
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for field_type in FieldTypeEnum:
        if raw.casefold() in {field_type.name.casefold(), field_type.value.casefold()}:
            return field_type
    return FIELD_TYPE_ALIASES.get(raw.casefold())


def _decimal(value: Any, label: str) -> tuple[Decimal | None, str | None]:
    """Parse a finite decimal and return a user-facing validation error."""
    if isinstance(value, bool):
        return None, f"{label} must be a number"
    raw = str(value).strip().replace(",", "")
    for symbol in ("$", "€", "£"):
        raw = raw.replace(symbol, "")
    raw = raw.strip()
    if not raw:
        return None, f"{label} must be a number"
    try:
        result = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None, f"{label} must be a number"
    if not result.is_finite():
        return None, f"{label} must be a finite number"
    return result, None


def normalize_schema(
    field_type: FieldTypeEnum | str,
    schema: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and normalize schema options stored with a value type."""
    normalized_type = normalize_field_type(field_type)
    if normalized_type is None:
        return None, "Choose a supported field type"
    if schema is None:
        schema = {}
    if not isinstance(schema, dict):
        return None, "Field rules must be an object"

    normalized: dict[str, Any] = {}
    if normalized_type is FieldTypeEnum.ENUM:
        options = schema.get("options", [])
        if isinstance(options, str):
            options = [item.strip() for item in options.split(",")]
        if not isinstance(options, (list, tuple)):
            return None, "Status options must be a list"
        clean_options: list[str] = []
        seen: set[str] = set()
        for option in options:
            value = str(option).strip()
            if not value:
                continue
            folded = value.casefold()
            if folded not in seen:
                clean_options.append(value)
                seen.add(folded)
        if not clean_options:
            return None, "Add at least one status option"
        normalized["options"] = clean_options

    if normalized_type is FieldTypeEnum.CURRENCY:
        bounds: dict[str, str] = {}
        for name in ("min", "max"):
            if schema.get(name) in (None, ""):
                continue
            parsed, error = _decimal(schema[name], f"Currency {name}")
            if error:
                return None, error
            assert parsed is not None
            bounds[name] = format(parsed, "f")
        if "min" in bounds and "max" in bounds:
            if Decimal(bounds["min"]) > Decimal(bounds["max"]):
                return None, "Currency minimum cannot exceed the maximum"
        normalized.update(bounds)

    return normalized, None


def _parse_date(value: Any) -> tuple[str | None, str | None]:
    raw = str(value).strip()
    if not raw:
        return None, "Date must be an ISO date such as 2026-08-03"
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        try:
            parsed_datetime = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None, "Date must be an ISO date such as 2026-08-03"
        parsed = parsed_datetime.date()
    return parsed.isoformat(), None


def validate_field_value(
    field_type: FieldTypeEnum | str,
    raw_value: Any,
    schema: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Validate a field value and return its canonical string representation."""
    normalized_type = normalize_field_type(field_type)
    if normalized_type is None:
        return None, "Choose a supported field type"
    normalized_schema, schema_error = normalize_schema(normalized_type, schema)
    if schema_error:
        return None, schema_error
    assert normalized_schema is not None

    if normalized_type in (FieldTypeEnum.TEXT_LINE, FieldTypeEnum.TEXT_BOX):
        if raw_value is None:
            return None, "Text value is required"
        return str(raw_value), None

    if normalized_type is FieldTypeEnum.DATETIME:
        return _parse_date(raw_value)

    if normalized_type is FieldTypeEnum.CURRENCY:
        parsed, error = _decimal(raw_value, "Currency")
        if error:
            return None, error
        assert parsed is not None
        if "min" in normalized_schema and parsed < Decimal(normalized_schema["min"]):
            return None, f"Currency must be at least {normalized_schema['min']}"
        if "max" in normalized_schema and parsed > Decimal(normalized_schema["max"]):
            return None, f"Currency must be at most {normalized_schema['max']}"
        rounded = parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return format(rounded, ".2f"), None

    if normalized_type is FieldTypeEnum.ENUM:
        value = str(raw_value).strip()
        for option in normalized_schema["options"]:
            if value.casefold() == option.casefold():
                return option, None
        return None, "Choose one of: " + ", ".join(normalized_schema["options"])

    if normalized_type is FieldTypeEnum.BOOLEAN:
        if isinstance(raw_value, bool):
            return ("true" if raw_value else "false"), None
        if isinstance(raw_value, int) and raw_value in (0, 1):
            return ("true" if raw_value else "false"), None
        value = str(raw_value).strip().casefold()
        if value in {"true", "yes", "y", "1", "on"}:
            return "true", None
        if value in {"false", "no", "n", "0", "off"}:
            return "false", None
        return None, "Checkbox must be true or false"

    return None, "Unsupported field type"


def schema_summary(field_type: FieldTypeEnum | str, schema: dict[str, Any] | None) -> str:
    """Format compact validation rules for the schema management table."""
    normalized_type = normalize_field_type(field_type)
    normalized_schema, _ = normalize_schema(normalized_type or "", schema)
    if not normalized_schema:
        return "Built-in" if normalized_type else "Invalid"
    parts: list[str] = []
    if normalized_schema.get("options"):
        parts.append("Options: " + ", ".join(normalized_schema["options"]))
    if normalized_schema.get("min") is not None:
        parts.append(f"Min {normalized_schema['min']}")
    if normalized_schema.get("max") is not None:
        parts.append(f"Max {normalized_schema['max']}")
    return "; ".join(parts) or "No additional rules"
