"""Cron parsing, timezone, and daylight-saving behavior."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from unifile.scheduler import CronExpression, CronExpressionError, JobScheduler, validate_job


def test_sunday_zero_and_seven_are_aliases_and_or_semantics_remain_standard():
    sunday = datetime(2026, 8, 2, 3, 15)  # Sunday
    monday = datetime(2026, 8, 3, 3, 15)
    assert CronExpression("15 3 * * 0").matches(sunday)
    assert CronExpression("15 3 * * 7").matches(sunday)
    assert not CronExpression("15 3 * * 7").matches(monday)

    restricted_both = CronExpression("15 3 1 * 7")
    assert restricted_both.matches(datetime(2026, 8, 1, 3, 15))
    assert restricted_both.matches(sunday)
    assert not restricted_both.matches(datetime(2026, 8, 3, 3, 15))


def test_aware_values_are_converted_to_the_schedule_timezone():
    expression = CronExpression("0 9 * * 1-5", timezone="America/New_York")
    assert expression.matches(datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc))
    assert not expression.matches(datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc))


def test_dst_spring_forward_skips_nonexistent_wall_time():
    expression = CronExpression("30 2 * * *", timezone="America/New_York")
    assert not expression.matches(datetime(2026, 3, 8, 2, 30))
    assert expression.matches(datetime(2026, 3, 9, 2, 30))


def test_dst_fall_back_matches_both_actual_occurrences():
    expression = CronExpression("30 1 * * *", timezone="America/New_York")
    zone = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    assert first.utcoffset() != second.utcoffset()
    assert expression.matches(first)
    assert expression.matches(second)


def test_scheduler_deduplicates_same_instant_but_not_fall_back_occurrences(tmp_path):
    zone = ZoneInfo("America/New_York")
    jobs_path = tmp_path / "jobs.json"
    job = validate_job({
        "id": "dst-job",
        "name": "DST check",
        "schedule": "30 1 * * *",
        "timezone": "America/New_York",
        "action": "scan",
        "path": str(tmp_path),
    })
    jobs_path.write_text(__import__("json").dumps([job]), encoding="utf-8")
    seen = []
    scheduler = JobScheduler(lambda current: seen.append(current["last_run"]) or {}, path=str(jobs_path))
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    assert len(scheduler.run_pending(first)) == 1
    assert scheduler.run_pending(first) == []
    assert len(scheduler.run_pending(second)) == 1
    assert len(seen) == 2


def test_invalid_timezone_and_weekday_have_actionable_errors():
    with pytest.raises(CronExpressionError, match="IANA"):
        CronExpression("0 0 * * *", timezone="Mars/Olympus")
    with pytest.raises(CronExpressionError, match="weekday.*0 and 7"):
        CronExpression("0 0 * * 8")
    with pytest.raises(ValueError, match="timezone"):
        validate_job({
            "name": "Bad timezone",
            "schedule": "0 0 * * *",
            "timezone": "Mars/Olympus",
            "action": "scan",
            "path": "/tmp",
        })
