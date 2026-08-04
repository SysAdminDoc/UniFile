"""Small dependency-free cron scheduler for headless UniFile jobs."""
from __future__ import annotations

import json
import os
import smtplib
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from unifile.config import _APP_DATA_DIR, load_json_safe, save_json_safe

DEFAULT_SCHEDULE_FILE = os.path.join(_APP_DATA_DIR, "headless_jobs.json")
CRON_FIELDS = ("minute", "hour", "day", "month", "weekday")


class CronExpressionError(ValueError):
    """Raised when a five-field cron expression is not supported."""


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
    """Parse and match the standard five-field local-time cron form."""

    def __init__(self, expression: str):
        parts = str(expression).split()
        if len(parts) != 5:
            raise CronExpressionError("cron expression must have five fields")
        ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
        parsed = [
            _parse_field(value, low, high, field)
            for value, (low, high), field in zip(parts, ranges, CRON_FIELDS, strict=True)
        ]
        self.expression = " ".join(parts)
        self.values = tuple(item[0] for item in parsed)
        self.wildcards = tuple(item[1] for item in parsed)

    def matches(self, value: datetime) -> bool:
        minute, hour, day, month, weekday = self.values
        if value.minute not in minute or value.hour not in hour or value.month not in month:
            return False
        day_match = value.day in day
        # Python uses Monday=0; cron uses Sunday=0 (and accepts Sunday=7 in
        # some implementations, which this compact parser intentionally omits).
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


def load_jobs(path: str = DEFAULT_SCHEDULE_FILE) -> list[dict[str, Any]]:
    jobs = load_json_safe(path, [], expected_type=list)
    return [dict(job) for job in jobs if _valid_job(job)]


def save_jobs(jobs: list[dict[str, Any]], path: str = DEFAULT_SCHEDULE_FILE) -> bool:
    return save_json_safe(path, jobs)


def validate_job(job: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(job, dict):
        raise ValueError("job must be an object")
    name = str(job.get("name", "")).strip()
    if not name or len(name) > 120:
        raise ValueError("job name is required and must be at most 120 characters")
    schedule = str(job.get("schedule", "")).strip()
    CronExpression(schedule)
    action = str(job.get("action", "scan")).strip().lower()
    if action not in {"scan", "tag", "verify"}:
        raise ValueError("job action must be scan, tag, or verify")
    path = str(job.get("path", "")).strip()
    if not path or "\x00" in path:
        raise ValueError("job path is required")
    normalized = {
        "id": str(job.get("id") or uuid.uuid4()),
        "name": name,
        "schedule": schedule,
        "action": action,
        "path": path,
        "enabled": bool(job.get("enabled", True)),
        "tag": str(job.get("tag", "")).strip(),
        "health_log": str(job.get("health_log", "")).strip(),
        "log_format": str(job.get("log_format", "")).strip().lower(),
        "email": dict(job.get("email", {})) if isinstance(job.get("email"), dict) else {},
        "last_run": str(job.get("last_run", "")),
        "last_status": str(job.get("last_status", "")),
        "created_at": str(job.get("created_at") or datetime.now().isoformat()),
    }
    if action == "tag" and not normalized["tag"]:
        raise ValueError("tag jobs require a tag value")
    if action == "verify" and normalized["log_format"] not in {"", "json", "csv", "txt", "text"}:
        raise ValueError("verify log format must be json, csv, or text")
    return normalized


def _same_minute(first: str, second: datetime) -> bool:
    if not first:
        return False
    try:
        previous = datetime.fromisoformat(first)
    except ValueError:
        return False
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
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if bool(settings.get("starttls", True)):
            smtp.starttls()
        username = str(settings.get("username", "")).strip()
        password = str(settings.get("password", ""))
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


class JobScheduler:
    """Run validated jobs once per matching local cron minute in a daemon thread."""

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
        self.now_fn = now_fn or datetime.now
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
                    cron = CronExpression(job["schedule"])
                    due = cron.matches(current) and not _same_minute(job.get("last_run", ""), current)
                except CronExpressionError as exc:
                    job["enabled"] = False
                    job["last_status"] = f"invalid schedule: {exc}"
                    changed = True
                    continue
                if not due:
                    continue
                job["last_run"] = current.isoformat()
                try:
                    result = self.handler(job) or {}
                    job["last_status"] = "completed"
                    if result.get("changed") and job.get("email"):
                        try:
                            send_digest_email(
                                job["email"],
                                f"UniFile job changed: {job['name']}",
                                json.dumps(result, indent=2, ensure_ascii=False),
                            )
                        except (OSError, smtplib.SMTPException, ValueError) as exc:
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
