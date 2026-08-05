from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.time_range import resolve_time_range as _resolve_time_range


def test_default_is_upcoming_unbounded():
    time_min, time_max = _resolve_time_range(None, None, None)
    now = datetime.now(timezone.utc)
    assert abs((time_min - now).total_seconds()) < 5
    assert time_max is None


def test_range_today_ends_at_midnight_tonight():
    time_min, time_max = _resolve_time_range(None, None, "today")
    assert time_max.hour == 23 and time_max.minute == 59
    assert time_max.date() == time_min.date()


def test_range_week_is_seven_days_out():
    time_min, time_max = _resolve_time_range(None, None, "week")
    assert (time_max - time_min) == timedelta(days=7)


def test_range_month_is_thirty_days_out():
    time_min, time_max = _resolve_time_range(None, None, "month")
    assert (time_max - time_min) == timedelta(days=30)


def test_explicit_from_and_to_are_used_directly():
    from_ = datetime(2026, 8, 1, tzinfo=timezone.utc)
    to = datetime(2026, 8, 31, tzinfo=timezone.utc)
    time_min, time_max = _resolve_time_range(from_, to, None)
    assert time_min == from_
    assert time_max == to


def test_naive_from_to_are_assumed_utc():
    from_ = datetime(2026, 8, 1)  # no tzinfo
    time_min, _ = _resolve_time_range(from_, None, None)
    assert time_min.tzinfo == timezone.utc


def test_to_without_from_defaults_from_to_now():
    to = datetime(2026, 12, 31, tzinfo=timezone.utc)
    time_min, time_max = _resolve_time_range(None, to, None)
    now = datetime.now(timezone.utc)
    assert abs((time_min - now).total_seconds()) < 5
    assert time_max == to


def test_from_without_to_is_unbounded():
    from_ = datetime(2026, 8, 1, tzinfo=timezone.utc)
    time_min, time_max = _resolve_time_range(from_, None, None)
    assert time_min == from_
    assert time_max is None


def test_combining_range_with_from_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        _resolve_time_range(datetime(2026, 8, 1, tzinfo=timezone.utc), None, "today")
    assert exc_info.value.status_code == 400


def test_combining_range_with_to_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        _resolve_time_range(None, datetime(2026, 8, 1, tzinfo=timezone.utc), "week")
    assert exc_info.value.status_code == 400
