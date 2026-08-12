"""Small dependency-free cron scheduler for headless UniFile jobs."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, tzinfo
from datetime import timezone as dt_timezone
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe
from unifile.credentials import (
    delete_credential,
    get_credential,
    keyring_available,
    set_credential,
)
from unifile.network import NetworkError, send_smtp

DEFAULT_SCHEDULE_FILE = os.path.join(_APP_DATA_DIR, "headless_jobs.json")
CRON_FIELDS = ("minute", "hour", "day", "month", "weekday")
LOCAL_TIMEZONE = "local"
UTC_TIMEZONE = "UTC"
_log = logging.getLogger(__name__)


class CronExpressionError(ValueError):
    """Raised when a five-field cron expression is not supported."""


def normalize_timezone(value: Any) -> str:
    """Validate and normalize a job timezone name.

    ``local`` follows the host's configured local timezone and ``UTC`` is
    portable across hosts.  Any other value must be an IANA zone name that
    ``zoneinfo`` can resolve.
    """
    text = str(value or LOCAL_TIMEZONE).strip()
    if not text or text.casefold() == LOCAL_TIMEZONE:
        return LOCAL_TIMEZONE
    if text.casefold() in {"utc", "z"}:
        return UTC_TIMEZONE
    try:
        ZoneInfo(text)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise CronExpressionError(
            "timezone must be 'local', 'UTC', or a resolvable IANA name "
            "such as 'America/New_York'"
        ) from exc
    return text


class _LocalTimezone(tzinfo):
    """A DST-aware local timezone using the host C runtime timezone rules."""

    @staticmethod
    def _offset_seconds(local_time) -> int:
        if local_time.tm_isdst > 0 and time.daylight:
            return -time.altzone
        return -time.timezone

    @classmethod
    def _valid_offsets(cls, naive: datetime) -> list[timedelta]:
        fields = list(naive.timetuple())
        offsets: dict[int, timedelta] = {}
        for is_dst in (0, 1):
            fields[-1] = is_dst
            local_time = time.localtime(time.mktime(tuple(fields)))
            if tuple(local_time[:6]) == tuple(naive.timetuple()[:6]):
                seconds = cls._offset_seconds(local_time)
                offsets[seconds] = timedelta(seconds=seconds)
        return [offsets[key] for key in sorted(offsets)]

    def utcoffset(self, value: datetime | None) -> timedelta:
        if value is None:
            return timedelta(seconds=-time.timezone)
        naive = value.replace(tzinfo=None)
        offsets = self._valid_offsets(naive)
        if offsets:
            return offsets[min(value.fold, len(offsets) - 1)]
        # A nonexistent wall time is rejected by CronExpression.localize;
        # return the C runtime's best-effort offset for ordinary conversions.
        fields = list(naive.timetuple())
        fields[-1] = -1
        local_time = time.localtime(time.mktime(tuple(fields)))
        return timedelta(seconds=self._offset_seconds(local_time))

    def dst(self, value: datetime | None) -> timedelta:
        offset = self.utcoffset(value)
        return offset - timedelta(seconds=-time.timezone)

    def tzname(self, value: datetime | None) -> str:
        return time.tzname[1 if self.dst(value) else 0]


_LOCAL_TZ = _LocalTimezone()


def _timezone_info(name: str):
    if name == LOCAL_TIMEZONE:
        return _LOCAL_TZ
    if name == UTC_TIMEZONE:
        return dt_timezone.utc
    return ZoneInfo(name)


def _parse_field(value: str, minimum: int, maximum: int, field: str) -> tuple[set[int], bool]:
    text = str(value).strip()
    if not text:
        raise CronExpressionError(f"{field} cannot be empty")
    values: set[int] = set()
    is_wildcard = text == "*"
    for token in text.split(","):
        token = token.strip()
        if not token:
            raise CronExpressionError(f"invalid {field} field: {value}")
        step = 1
        if "/" in token:
            base, step_text = token.split("/", 1)
            try:
                step = int(step_text)
            except ValueError as exc:
                raise CronExpressionError(f"invalid {field} step: {step_text}") from exc
            if step < 1:
                raise CronExpressionError(f"{field} step must be positive")
        else:
            base = token
        if base == "*":
            start, end = minimum, maximum
            is_wildcard = True
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            try:
                start, end = int(start_text), int(end_text)
            except ValueError as exc:
                raise CronExpressionError(f"invalid {field} range: {base}") from exc
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise CronExpressionError(f"invalid {field} value: {base}") from exc
        if start < minimum or end > maximum or start > end:
            raise CronExpressionError(f"{field} must stay between {minimum} and {maximum}")
        values.update(range(start, end + 1, step))
    return values, is_wildcard


class CronExpression:
    """Parse and match a five-field cron expression in an explicit timezone.

    Naive datetimes are interpreted as wall-clock values in ``timezone``.
    A nonexistent spring-forward wall time never matches.  An ambiguous
    fall-back wall time matches both folds; callers that execute jobs should
    retain the offset-aware timestamp to distinguish the two occurrences.
    """

    def __init__(self, expression: str, *, timezone: str = LOCAL_TIMEZONE):
        parts = str(expression).split()
        if len(parts) != 5:
            raise CronExpressionError("cron expression must have five fields")
        self.timezone = normalize_timezone(timezone)
        self.tzinfo = _timezone_info(self.timezone)
        ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
        parsed = [
            _parse_field(value, low, high, field)
            for value, (low, high), field in zip(parts, ranges, CRON_FIELDS, strict=True)
        ]
        self.expression = " ".join(parts)
        weekday_values, weekday_wildcard = parsed[-1]
        weekday_values = {0 if value == 7 else value for value in weekday_values}
        self.values = tuple(item[0] for item in parsed[:-1]) + (weekday_values,)
        self.wildcards = tuple(item[1] for item in parsed)
        # Retain the normalized flag explicitly because the values tuple has
        # already transformed the Sunday alias.
        self.wildcards = (*self.wildcards[:-1], weekday_wildcard)

    def localize(self, value: datetime) -> datetime | None:
        """Convert *value* to the schedule timezone, rejecting gaps."""
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value.astimezone(self.tzinfo)
        naive = value.replace(tzinfo=None)
        candidates = []
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=self.tzinfo, fold=fold)
            round_trip = candidate.astimezone(dt_timezone.utc).astimezone(self.tzinfo)
            if round_trip.replace(tzinfo=None) == naive:
                candidates.append(candidate)
        if not candidates:
            return None
        return candidates[0]

    def matches(self, value: datetime) -> bool:
        value = self.localize(value)
        if value is None:
            return False
        minute, hour, day, month, weekday = self.values
        if value.minute not in minute or value.hour not in hour or value.month not in month:
            return False
        day_match = value.day in day
        # Python uses Monday=0; cron uses Sunday=0.  Sunday=7 was normalized
        # during parsing, so both aliases follow the same match path.
        cron_weekday = (value.weekday() + 1) % 7
        weekday_match = cron_weekday in weekday
        # Cron treats day-of-month and day-of-week as an OR when both are
        # restricted; otherwise the unrestricted field contributes no filter.
        if not self.wildcards[2] and not self.wildcards[4]:
            return day_match or weekday_match
        return day_match and weekday_match


def _valid_job(job: Any) -> bool:
    return isinstance(job, dict) and isinstance(job.get("id"), str) and isinstance(
        job.get("schedule"), str
    )


def _smtp_credential_name(job_id: str) -> str:
    return f"scheduler:smtp:{job_id}"


def _secure_email_settings(
    raw_email: Any,
    job_id: str,
    *,
    strict: bool,
) -> dict[str, Any]:
    """Strip SMTP passwords and move them to the OS keyring."""
    if not isinstance(raw_email, dict) or not raw_email:
        return {}
    email = {
        key: raw_email[key]
        for key in ("host", "from", "to", "port", "starttls", "username")
        if key in raw_email
    }
    password = str(raw_email.get("password", ""))
    password_ref = _smtp_credential_name(job_id)
    if password:
        if not set_credential(password_ref, password):
            if strict:
                raise ValueError("SMTP password cannot be persisted without an OS keyring")
            _log.warning(
                "Discarding an unsecured SMTP password for job %s; OS keyring required.",
                job_id,
            )
    elif "password" in raw_email:
        if not keyring_available():
            if strict:
                raise ValueError("SMTP password cannot be cleared without an OS keyring")
        elif not delete_credential(password_ref) and strict:
            raise ValueError("SMTP password could not be cleared from the OS keyring")
    return email


def _sanitize_job_for_storage(job: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    normalized = dict(job)
    job_id = str(normalized.get("id", "")).strip()
    try:
        normalized["timezone"] = normalize_timezone(normalized.get("timezone", LOCAL_TIMEZONE))
    except CronExpressionError:
        if strict:
            raise
        # Keep a legacy invalid value visible so the scheduler can disable the
        # job with an actionable status instead of silently changing intent.
        normalized["timezone"] = str(normalized.get("timezone", LOCAL_TIMEZONE))
    normalized["email"] = _secure_email_settings(
        normalized.get("email"),
        job_id,
        strict=strict,
    )
    return normalized


def load_jobs(path: str = DEFAULT_SCHEDULE_FILE) -> list[dict[str, Any]]:
    jobs = load_json_safe(path, [], expected_type=list)
    cleaned: list[dict[str, Any]] = []
    changed = False
    for job in jobs:
        if not _valid_job(job):
            continue
        normalized = _sanitize_job_for_storage(dict(job), strict=False)
        cleaned.append(normalized)
        if normalized != job:
            changed = True
    if changed:
        save_json_safe(path, cleaned)
    return cleaned


def save_jobs(jobs: list[dict[str, Any]], path: str = DEFAULT_SCHEDULE_FILE) -> bool:
    try:
        cleaned = [_sanitize_job_for_storage(dict(job), strict=True) for job in jobs]
    except (TypeError, ValueError):
        return False
    return save_json_safe(path, cleaned)


def validate_job(job: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(job, dict):
        raise ValueError("job must be an object")
    name = str(job.get("name", "")).strip()
    if not name or len(name) > 120:
        raise ValueError("job name is required and must be at most 120 characters")
    schedule = str(job.get("schedule", "")).strip()
    timezone_name = normalize_timezone(job.get("timezone", LOCAL_TIMEZONE))
    CronExpression(schedule, timezone=timezone_name)
    action = str(job.get("action", "scan")).strip().lower()
    if action not in {"scan", "tag", "verify"}:
        raise ValueError("job action must be scan, tag, or verify")
    path = str(job.get("path", "")).strip()
    if not path or "\x00" in path:
        raise ValueError("job path is required")
    job_id = str(job.get("id") or uuid.uuid4())
    normalized = {
        "id": job_id,
        "name": name,
        "schedule": schedule,
        "timezone": timezone_name,
        "action": action,
        "path": path,
        "enabled": bool(job.get("enabled", True)),
        "tag": str(job.get("tag", "")).strip(),
        "health_log": str(job.get("health_log", "")).strip(),
        "log_format": str(job.get("log_format", "")).strip().lower(),
        "last_run": str(job.get("last_run", "")),
        "last_status": str(job.get("last_status", "")),
        "created_at": str(job.get("created_at") or datetime.now().isoformat()),
    }
    if action == "tag" and not normalized["tag"]:
        raise ValueError("tag jobs require a tag value")
    if action == "verify" and normalized["log_format"] not in {"", "json", "csv", "txt", "text"}:
        raise ValueError("verify log format must be json, csv, or text")
    normalized["email"] = _secure_email_settings(
        job.get("email", {}),
        job_id,
        strict=True,
    )
    return normalized


def _same_minute(first: str, second: datetime, cron: CronExpression | None = None) -> bool:
    """Compare execution instants at minute precision in a schedule zone."""
    if not first:
        return False
    try:
        previous = datetime.fromisoformat(first)
    except ValueError:
        return False
    if cron is not None:
        previous = cron.localize(previous)
        second = cron.localize(second)
        if previous is None or second is None:
            return False
    elif previous.tzinfo is None and second.tzinfo is not None:
        previous = previous.replace(tzinfo=second.tzinfo)
    elif previous.tzinfo is not None and second.tzinfo is None:
        second = second.replace(tzinfo=previous.tzinfo)
    if previous.tzinfo is not None and second.tzinfo is not None:
        previous = previous.astimezone(dt_timezone.utc)
        second = second.astimezone(dt_timezone.utc)
    return previous.replace(second=0, microsecond=0) == second.replace(second=0, microsecond=0)


def send_digest_email(settings: dict[str, Any], subject: str, body: str) -> bool:
    """Send an optional digest without logging SMTP credentials."""
    host = str(settings.get("host", "")).strip()
    sender = str(settings.get("from", "")).strip()
    recipient = str(settings.get("to", "")).strip()
    if not host or not sender or not recipient:
        return False
    message = EmailMessage()
    message["Subject"] = subject[:200]
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body[:20_000])
    port = int(settings.get("port", 587) or 587)
    username = str(settings.get("username", "")).strip()
    password = str(settings.get("password", ""))
    if not password:
        job_id = str(settings.get("_job_id", "")).strip()
        if job_id:
            password = get_credential(_smtp_credential_name(job_id))
    send_smtp(
        host,
        port,
        message,
        username=username,
        password=password,
        starttls=bool(settings.get("starttls", True)),
        provider="smtp",
    )
    return True


class JobScheduler:
    """Run validated jobs once per matching cron minute in their timezones."""

    def __init__(
        self,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        path: str = DEFAULT_SCHEDULE_FILE,
        poll_seconds: float = 20.0,
        now_fn: Callable[[], datetime] | None = None,
    ):
        self.handler = handler
        self.path = path
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.now_fn = now_fn or (lambda: datetime.now().astimezone())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def run_pending(self, now: datetime | None = None) -> list[dict[str, Any]]:
        current = now or self.now_fn()
        outcomes = []
        with self._lock:
            jobs = load_jobs(self.path)
            changed = False
            for job in jobs:
                if not job.get("enabled", True):
                    continue
                try:
                    cron = CronExpression(job["schedule"], timezone=job.get("timezone", LOCAL_TIMEZONE))
                    local_current = cron.localize(current)
                    due = (
                        local_current is not None
                        and cron.matches(local_current)
                        and not _same_minute(job.get("last_run", ""), local_current, cron)
                    )
                except CronExpressionError as exc:
                    job["enabled"] = False
                    job["last_status"] = f"invalid schedule: {exc}"
                    changed = True
                    continue
                if not due:
                    continue
                job["last_run"] = local_current.isoformat()
                try:
                    result = self.handler(job) or {}
                    job["last_status"] = "completed"
                    if result.get("changed") and job.get("email"):
                        try:
                            send_digest_email(
                                {**job["email"], "_job_id": job["id"]},
                                f"UniFile job changed: {job['name']}",
                                json.dumps(result, indent=2, ensure_ascii=False),
                            )
                        except (NetworkError, OSError, ValueError) as exc:
                            job["last_status"] = f"completed; email failed: {type(exc).__name__}"
                    outcomes.append({"job": job["id"], "status": job["last_status"], "result": result})
                except Exception as exc:
                    job["last_status"] = f"failed: {type(exc).__name__}: {exc}"[:500]
                    outcomes.append({"job": job["id"], "status": job["last_status"], "result": {}})
                changed = True
            if changed:
                save_jobs(jobs, self.path)
        return outcomes

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="unifile-scheduler", daemon=True)
        self._thread.start()
        return True

    def _run(self):
        while not self._stop.is_set():
            self.run_pending()
            self._stop.wait(self.poll_seconds)

    def stop(self, timeout: float = 5.0):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(max(0.1, timeout))
        self._thread = None
